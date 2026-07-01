# NAS 사진 정리 앱

Synology NAS(DSM 7.2+) 위에서 Docker로 동작하는 가족 사진 정리 웹앱.
가족 구성원이 각자 DSM 계정으로 로그인해 공용·개인 사진을 타임라인으로 보고,
드래그앤드롭으로 이동·복사·삭제하며, 모든 작업은 기록·Undo 가능합니다.

> 전체 명세는 [`NAS_사진정리앱_개발명세서.md`](./NAS_사진정리앱_개발명세서.md)가 단일 진실 소스입니다.
> 전체 리뷰(코드 + 오픈소스/UI/UX 벤치마크)에서 도출된 개선 필요사항은
> [`docs/IMPROVEMENTS.md`](./docs/IMPROVEMENTS.md)에 있으며, **모든 작업 시 반드시 반영**합니다.

## 현재 진행 상태 (1단계 / MVP)

- [x] 리포 스캐폴딩 (backend / frontend / docker)
- [x] DSM API 클라이언트 + 로그인 (`SYNO.API.Info` 프로브 → `SYNO.API.Auth`)
- [ ] 타임라인 뷰 → 선택/DnD → CopyMove/Delete/CreateFolder → 작업로그/Undo
- [ ] cross-space 이동 → 관리자 기능 → 라이트박스/EXIF → 폴더 뷰 → Docker 검증

## 아키텍처

```
브라우저 ── /api ──> FastAPI(백엔드) ── DSM Web API ──> Synology DSM
                       │  세션(HttpOnly 쿠키) ↔ DSM sid 매핑은 서버에만 저장
                       └  SQLite: 세션 / 작업로그·Undo / 사진 캐시
```

파일 조작은 직접 볼륨 마운트가 아니라 **DSM Web API**(Auth / FileStation /
Foto / FotoTeam)로만 수행합니다. 권한은 DSM이 enforce합니다.

## 사전 준비

1. `.env.example`을 `.env`로 복사하고 NAS 주소·포트를 채웁니다.
   ```bash
   cp .env.example .env
   ```
   - `DSM_BASE_URL`, `DSM_PORT` 설정 (HTTPS·자체서명이면 `DSM_VERIFY_TLS=false`)
   - **DSM 계정/비밀번호는 `.env`에 넣지 않습니다.** 로그인 화면에서 입력합니다.

## 로컬 개발 실행

두 개의 터미널이 필요합니다.

### 1) 백엔드 (FastAPI)

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# .env는 리포 루트에 있으므로 루트에서 실행하거나 env를 export 합니다.
cd ..
uvicorn app.main:app --app-dir backend --reload --port 9800
```

헬스체크: <http://localhost:9800/api/health> → `{"status":"ok"}`

### 2) 프론트엔드 (Vite)

```bash
cd frontend
npm install
npm run dev
```

브라우저에서 <http://localhost:5173> → DSM 계정으로 로그인.
`/api` 요청은 Vite 프록시가 백엔드(9800)로 전달합니다.

로그인에 성공하면 화면에 **실제 NAS의 `SYNO.API.Info` 프로브 결과**(각 API의
path/version/사용가능 여부)가 표로 표시됩니다 — 1단계 검증 지점입니다.

## Docker 실행 (NAS Container Manager)

단일 멀티스테이지 이미지(프론트 빌드 → FastAPI가 정적 서빙).

```bash
docker compose up --build -d
```

- 접속: `http://<NAS_IP>:9800`
- SQLite는 `nas-photo-data` 볼륨에 보존됩니다.
- 운영 시 DSM 리버스 프록시(HTTPS) 뒤에 두고 `.env`의 `COOKIE_SECURE=true` 권장.

## 프로젝트 구조

```
backend/
  app/
    main.py            # FastAPI 진입점 (lifespan, CORS, 정적 서빙)
    config.py          # 환경설정 (.env)
    db.py              # SQLite 스키마 (session / operation / photo_cache)
    session_store.py   # 쿠키 토큰 ↔ DSM sid 매핑 (서버측)
    schemas.py         # 요청/응답 모델
    dsm/
      client.py        # DSM Web API 클라이언트 (Info 프로브 / 로그인)
      errors.py        # DSM 오류코드 → 한국어 메시지
    api/
      deps.py          # 공용 의존성 (현재 세션 등)
      auth.py          # /api/auth/login, /logout, /me
      system.py        # /api/system/info (API.Info 프로브)
frontend/
  src/
    api/               # 백엔드 호출 클라이언트 + 타입
    components/        # LoginForm, ApiInfoPanel
    store/             # Zustand (auth UI 상태)
    App.tsx, main.tsx
docker/Dockerfile
docker-compose.yml
```

## 보안 메모

- DSM `sid`는 브라우저에 노출하지 않습니다. 서버가 HttpOnly 쿠키(불투명 토큰)로
  래핑하고 sid는 SQLite `session` 테이블에만 보관합니다.
- 자격증명은 코드·로그·`.env`에 남기지 않습니다.
- 삭제는 영구삭제가 아니라 NAS 휴지통(`#recycle`)으로 보냅니다(후속 단계).
