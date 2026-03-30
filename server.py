"""
AI Sound Sync — 로컬 프록시 서버
-----------------------------------
실행: python server.py
접속: http://localhost:5000

필요 패키지:
  pip install flask flask-cors anthropic
"""

import os, json, base64
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import anthropic

app = Flask(__name__)
CORS(app)  # 브라우저 CORS 허용

# ── API 키 설정 ─────────────────────────────────────────────────────────────
# 여기에 발급받은 Claude API 키를 입력하세요
API_KEY = os.environ.get('API_KEY', '')

# ── 프롬프트 전문 ──────────────────────────────────────────────────────────

FOLEY_SYSTEM = """You are a professional Foley supervisor AI with expertise in film and game post-production.

Your sole task is to analyze the provided video frames and extract a precise Foley event
timeline covering only what is VISUALLY CONFIRMED on screen.

You do NOT analyze music, dialogue, hard SFX, or ambience.
You focus exclusively on physical performance sounds:
footsteps, body/cloth movement, and hand/prop interactions.

DEFINITIONS — BODY VISIBILITY CLASSIFICATION:
[ON-SCREEN] — Foley coverage REQUIRED
  - FULL_BODY   : Ankle or foot clearly visible
    → timing_source must be "foot_visible"
    → timing_confidence: "high" is only valid for FULL_BODY scenes
  - PARTIAL_BODY: Camera captures character but feet not visible
    → Timing must be inferred from visible body movement signals
    → Using "foot_visible" in a PARTIAL_BODY scene is a critical error.
[OFF_SCREEN] — Foley coverage EXCLUDED
  → No Foley coverage needed. Exclude from all event output.

COVERAGE RULE:
All ON-SCREEN characters must be covered with Foley, regardless of which body parts
are visible. Only OFF-SCREEN characters are excluded.

Output must be valid JSON only. No explanation, no markdown, no extra text."""

FOLEY_USER_TEMPLATE = """Analyze the provided video frames and extract a complete Foley event timeline.

ANALYSIS WORKFLOW — TWO PASS REQUIRED

PASS 1 — Full Context Survey
1. Character identification
   - Identify ALL characters. Assign CHAR_A, CHAR_B, etc.
   - Note appearance, clothing, footwear
   - character entering frame ≠ first foot contact

2. Scene structure
   - Shot boundaries, camera movement
   - Visibility class per character: FULL_BODY / PARTIAL_BODY / OFF_SCREEN

3. Foley coverage map
   - Available timing signals per PARTIAL_BODY scene
   - Flag GAIT_MODIFIER conditions

PASS 2 — Event Extraction

FOOTSTEP TIMING — SIGNAL DETECTION (PARTIAL_BODY):

SIGNAL A — HEAD_DIP: vertical oscillation, foot contact = local minimum. Reduced with GAIT_MODIFIER.
SIGNAL B — SHOULDER_OSCILLATION: front/3-4 tilts left/right, side rises/falls.
SIGNAL C — TORSO_SWAY: torso front shifts left/right. Front-facing shots only.

Confidence:
- 2+ signals → timing_confidence: "estimated", timing_source: "multi_signal"
- 1 signal   → timing_confidence: "low"
- 0 signals  → timing_confidence: "low", timing_source: "stride_extrapolated"

GAIT_MODIFIER — reduce HEAD_DIP weight when:
- Character holds weapon in aimed/ready position
- Character is crouching or in tactical stance
- Character carries heavy object with both arms

CRITICAL — GAIT_MODIFIER does NOT determine whether a character is moving.
Movement vs static: judge ONLY by body position change relative to background.
Weak signal ≠ not walking.

STRIDE INTERVAL EXTRAPOLATION:
If first 2-3 contacts confirmed with consistent rhythm:
- Calculate average_step_interval_ms, extrapolate subsequent contacts
- Stop if: gait changes / camera cut / off-screen / rhythm disruption

CLOTH_MOVEMENT TYPE A (LINKED): parent FOOTSTEP/HAND offset. Default: FS pre=80ms post=300ms, HAND pre=50ms post=250ms
CLOTH_MOVEMENT TYPE B (INDEPENDENT): start=beginning of movement, end=fully settled
HAND events: only for distinct physical interactions (grab, tap, knock, slide, press). Not passive movement.

Frame timestamps (ms): {timestamps}
Video duration: {duration_ms}ms

Return this JSON structure:
{{
  "analysis_meta": {{
    "video_duration_ms": {duration_ms},
    "detected_fps": 4,
    "total_foley_events": 0,
    "characters_detected": 0,
    "analysis_approach": "two_pass_on_screen_only",
    "pass1_summary": ""
  }},
  "characters": [{{
    "character_id": "CHAR_A",
    "description": "",
    "footwear": "",
    "clothing_material": "",
    "first_clearly_identifiable_ms": 0,
    "visibility_segments_ms": [{{"class": "FULL_BODY", "start_ms": 0, "end_ms": {duration_ms}}}]
  }}],
  "sequences": [{{
    "sequence_id": "SEQ_001",
    "character_id": "CHAR_A",
    "sequence_type": "walk",
    "sequence_start_ms": 0,
    "sequence_end_ms": {duration_ms},
    "step_count_visible": 0,
    "step_count_method": "signal_inferred",
    "average_step_interval_ms": 500,
    "visibility_class": "PARTIAL_BODY",
    "signals_available": ["shoulder_oscillation"],
    "gait_modifier": "none"
  }}],
  "events": [{{
    "event_id": "FOL_001",
    "sequence_id": "SEQ_001",
    "character_id": "CHAR_A",
    "category": "FOOTSTEP",
    "start_ms": 0,
    "end_ms": 80,
    "estimated_duration_ms": 80,
    "timing_confidence": "estimated",
    "timing_note": null,
    "timing_range_ms": null,
    "on_screen_confirmed": true,
    "description": "",
    "category_fields": {{
      "surface_material": "concrete",
      "weight_class": "medium",
      "gait_type": "walk",
      "character_material": "hard_shoe",
      "foot_side": "unknown",
      "visibility_class": "PARTIAL_BODY",
      "signals_used": ["shoulder_oscillation"],
      "gait_modifier": "none",
      "timing_source": "multi_signal"
    }}
  }}]
}}
Fill all fields based on visual analysis. Return only JSON."""


AMBIENCE_SYSTEM = """You are a professional sound designer AI with expertise in film and game post-production.

Your sole task is to analyze the provided video frames and extract a complete Ambience sound timeline.

You do NOT analyze music, dialogue, SFX, or Foley sounds.
You focus exclusively on background ambience:
room tones, environmental atmosphere, nature sounds, crowd presence, weather, and spatial characteristics.

COVERAGE RULE — MANDATORY:
Every millisecond of the video must be covered by at least one ambience layer.
There must be NO silent gaps in the ambience timeline.
If a scene is ambiguous, default to a neutral room tone rather than leaving it empty.

CROSSFADE RULE — MANDATORY:
At every scene transition, ambience layers must overlap by 1 frame (~33ms at 30fps):
- Outgoing layer: end_ms += 1 frame beyond the cut point
- Incoming layer: start_ms -= 1 frame before the cut point

Output must be valid JSON only. No explanation, no markdown, no extra text."""

AMBIENCE_USER_TEMPLATE = """Analyze the provided video frames and extract a complete Ambience sound timeline.

ANALYSIS WORKFLOW — TWO PASS REQUIRED

PASS 1 — Full Context Survey
1. Scene structure: all shot boundaries, camera movement, lighting
2. Per-scene space analysis:
   - space_type: interior/exterior
   - location, space_size (intimate/small/medium/large/vast)
   - acoustic_character: dry/live/reverberant/echo
   - background_activity, weather, time_of_day
3. Layer plan per scene: PRIMARY (mandatory) + SECONDARY (optional, max 2). Max 3 layers per scene.
4. Transition map + crossfade overlap planning

PASS 2 — Layer Extraction

AMBIENCE CATEGORIES:
  ROOM_TONE   — enclosed space acoustic presence
  ENVIRONMENT — outdoor/indoor atmosphere with character
  NATURE      — birds, wind, insects, rain, water
  CROWD       — human background presence
  WEATHER     — rain, thunder, wind, snow silence
  MECHANICAL  — HVAC, engine, server room

Frame timestamps (ms): {timestamps}
Video duration: {duration_ms}ms

Return this JSON structure:
{{
  "analysis_meta": {{
    "video_duration_ms": {duration_ms},
    "detected_fps": 4,
    "total_ambience_layers": 0,
    "scene_count": 0,
    "analysis_approach": "two_pass_ambience",
    "pass1_summary": ""
  }},
  "scenes": [{{
    "scene_id": "SCN_001",
    "start_ms": 0,
    "end_ms": {duration_ms},
    "location": "",
    "space_type": "interior",
    "space_size": "medium",
    "acoustic_character": "dry",
    "lighting": "day",
    "notes": ""
  }}],
  "transitions": [],
  "layers": [{{
    "layer_id": "AMB_001",
    "scene_id": "SCN_001",
    "layer_role": "primary",
    "ambience_type": "ROOM_TONE",
    "start_ms": 0,
    "end_ms": {duration_ms},
    "duration_ms": {duration_ms},
    "crossfade_in_ms": 0,
    "crossfade_out_ms": 0,
    "description": "",
    "location_detail": "",
    "intensity": "moderate",
    "stereo_field": "stereo",
    "distance": "mid",
    "notes": ""
  }}]
}}
Fill all fields based on visual analysis. Return only JSON."""


# ── API 엔드포인트 ──────────────────────────────────────────────────────────

def recover_truncated_json(text):
    """잘린 JSON에서 마지막 완전한 항목까지 복구"""
    # events 또는 layers 배열 찾기
    for key in ('"events"', '"layers"'):
        ei = text.rfind(key)
        if ei == -1:
            continue
        as_ = text.find('[', ei)
        if as_ == -1:
            continue
        # 마지막 완전한 } 찾기
        last_obj = -1
        for i in range(len(text) - 1, as_, -1):
            if text[i] == '}':
                last_obj = i
                break
        if last_obj == -1:
            continue
        # 잘린 부분을 닫아서 파싱 시도
        for attempt in [
            text[:last_obj + 1] + '\n]}',
            text[:last_obj + 1] + '\n]}'
        ]:
            try:
                parsed = json.loads(attempt)
                arr = parsed.get('events') or parsed.get('layers')
                if arr and len(arr) > 0:
                    return parsed
            except Exception:
                pass
    return None


@app.route('/analyze', methods=['POST'])
def analyze():
    data = request.json
    api_key  = API_KEY  # 서버에 저장된 키 사용
    frames   = data.get('frames', [])       # [{b64, ms}, ...]
    timestamps = data.get('timestamps', [])
    duration_ms = data.get('duration_ms', 0)
    analysis_type = data.get('type', 'ambience')  # 'foley' | 'ambience'

    if not api_key or api_key == "여기에_API_키_입력":
        return jsonify({'error': 'server.py에 API_KEY를 설정하세요'}), 400
    if not frames:
        return jsonify({'error': 'No frames provided'}), 400

    client = anthropic.Anthropic(api_key=api_key)

    # 프롬프트 선택
    if analysis_type == 'foley':
        system_prompt = FOLEY_SYSTEM
        user_prompt   = FOLEY_USER_TEMPLATE.format(
            timestamps=json.dumps(timestamps),
            duration_ms=duration_ms
        )
    else:
        system_prompt = AMBIENCE_SYSTEM
        user_prompt   = AMBIENCE_USER_TEMPLATE.format(
            timestamps=json.dumps(timestamps),
            duration_ms=duration_ms
        )

    # 이미지 + 텍스트 content 빌드
    content = []
    for f in frames:
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": f['b64']
            }
        })
    content.append({"type": "text", "text": user_prompt})

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=8192,
            system=system_prompt,
            messages=[{"role": "user", "content": content}]
        )
        text = response.content[0].text.strip()
        if text.startswith('```'):
            text = text.split('\n', 1)[1].rsplit('```', 1)[0]

        # 트런케이션 복구: JSON이 잘렸을 경우 마지막 완전한 객체까지만 파싱
        try:
            result = json.loads(text)
        except json.JSONDecodeError:
            # events/layers 배열의 마지막 완전한 항목까지 복구
            recovered = recover_truncated_json(text)
            if recovered:
                result = recovered
                result['_truncated'] = True
            else:
                return jsonify({'error': 'JSON parse error — 결과가 너무 깁니다. 영상을 짧게 잘라 다시 시도하세요.', 'raw': text[:300]}), 500

        return jsonify(result)

    except json.JSONDecodeError as e:
        return jsonify({'error': f'JSON parse error: {str(e)}', 'raw': text[:500]}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/ping', methods=['GET'])
def ping():
    return jsonify({'status': 'ok'})


if __name__ == '__main__':
    print("\n" + "="*40)
    print("AI Sound Sync 서버가 시작되었습니다.")
    print("접속 주소: http://localhost:5000")
    print("="*40 + "\n")
    app.run(host='0.0.0.0', port=5000, debug=True)
