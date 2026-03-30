# AI Sound Sync Pipeline

AI 기반 영상-사운드 자동 싱크 파이프라인  
영상 분석 → Foley/Ambience 타임라인 자동 배치

---

## 로컬 실행

```bash
pip install flask flask-cors anthropic
python server.py
# → http://localhost:5000
```

`server.py` 상단 `API_KEY = "여기에_API_키_입력"` 에 Claude API 키 입력

---

## 배포 구조

```
GitHub (index.html)  →  GitHub Pages  (정적 호스팅)
GitHub (server.py)   →  Render.com    (Flask API 서버)
```

### 1단계 — GitHub 저장소

1. GitHub에서 새 저장소 생성 (예: `ai-sound-sync`)
2. 이 폴더 파일 전체 업로드:
   - `index.html`
   - `server.py`
   - `requirements.txt`
   - `README.md`

### 2단계 — GitHub Pages (index.html 호스팅)

1. 저장소 → Settings → Pages
2. Source: `main` 브랜치, `/ (root)`
3. Save → `https://[username].github.io/ai-sound-sync` 생성

### 3단계 — Render.com (server.py 호스팅)

1. https://render.com 접속 → New Web Service
2. GitHub 저장소 연결
3. 설정:
   - **Runtime:** Python 3
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn server:app`
4. Environment Variables 추가:
   - Key: `API_KEY`
   - Value: `sk-ant-api03-...` (Claude API 키)
5. Deploy → `https://ai-sound-sync.onrender.com` 생성

### 4단계 — index.html에 Render URL 연결

`index.html` 내 아래 줄 찾아서 실제 Render URL로 수정:
```javascript
(window.RENDER_URL||'https://ai-sound-sync.onrender.com')
```
→ 실제 Render URL로 교체 후 GitHub에 다시 push

---

## 기술 스택

- Frontend: Vanilla HTML/CSS/JS (단일 파일)
- Backend: Python Flask + Anthropic SDK
- AI: Claude Sonnet 4 (claude-sonnet-4-20250514)
- 프롬프트: Foley v2.303 / Ambience v1.0
