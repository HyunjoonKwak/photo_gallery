# Claude Code 킥오프 프롬프트

> 아래 블록 전체를 복사해 Claude Code에 붙여넣으세요.
> `NAS_사진정리앱_개발명세서.md` 파일을 같은 작업 폴더에 함께 두는 것을 권장합니다.

---

```
나는 Synology NAS(Intel Plus 계열) 위에서 Docker로 돌아가는 "가족 사진 정리 웹앱"을 만들려고 한다.
전체 컨셉·아키텍처·UI·API·데이터모델·로드맵은 같은 폴더의 `NAS_사진정리앱_개발명세서.md`에 정리돼 있다.
먼저 그 문서를 읽고 시작해라. 문서가 곧 단일 진실 소스(Single Source of Truth)다.

[기술 스택 — 명세서 6장 따른다]
- Backend: Python FastAPI
- Frontend: React + Vite + TypeScript + Tailwind, 드래그앤드롭 @dnd-kit/core, 가상스크롤 @tanstack/react-virtual, 서버상태 React Query, UI상태 Zustand
- 앱 DB: SQLite (작업로그·Undo·캐시)
- 배포: 단일 Docker 이미지(멀티스테이지) + docker-compose

[작업 원칙]
1. 파일 조작은 직접 볼륨 마운트가 아니라 DSM Web API(SYNO.API.Auth / FileStation / Foto / FotoTeam)를 통해서 한다. 권한은 DSM이 enforce한다.
2. 가장 불확실한 부분은 Synology Photos API(비공식 문서 기반)다. 그래서 "DSM 로그인 + SYNO.API.Info로 실제 엔드포인트·버전 확인"을 1순위로 구현하고 실제 NAS로 검증한 뒤 다음으로 넘어간다. 추측으로 코드를 쌓지 마라.
3. 모든 파괴적 작업(이동/삭제)은 작업로그에 역연산 정보를 남기고 즉시 Undo가 가능해야 한다. 삭제는 영구삭제가 아니라 NAS 휴지통(#recycle)으로 보낸다.
4. 환경설정(NAS 주소·포트·시크릿)은 .env / 환경변수로 빼고, 자격증명을 코드·로그에 남기지 마라.

[1단계(MVP) 범위 — 명세서 3장]
보기(타임라인 기본 + 폴더 트리 토글) · 다중선택 · 드래그앤드롭 이동/복사 · 폴더 생성/이름변경 · 삭제 · 개인↔공용 cross-space 이동 · 관리자 계정의 가족 전체 개인 폴더 접근 · 라이트박스+EXIF · 작업로그+Undo.
중복제거(2단계)·AI분류(3단계)는 지금 구현하지 않는다.

[특히 주의할 두 기능]
- 개인 폴더 → 공용 폴더 이동: 개인공간(SYNO.Foto, /homes/<user>/Photos) ↔ 공유공간(SYNO.FotoTeam, /photo)을 가로지른다. Foto API 자체 이동이 안 되면 FileStation CopyMove + 양쪽 재인덱싱 경로로 처리. 두 경로 모두 검증.
- 관리자 권한: administrators 그룹이면 role=admin. 관리자는 "가족 구성원 선택"으로 타인 개인 폴더(/homes/<user>/Photos)를 FileStation으로 List해서 볼 수 있어야 한다. 남의 폴더를 보는 중엔 화면에 "보는 중: ○○의 개인 폴더" 배너를 명확히 표시.

[이번 세션에서 너가 할 일 — 순서대로, 명세서 12장]
1. 먼저 명세서 13장 "개발 시작 전 NAS에서 확인할 것"을 나에게 질문해서 채워라(DSM 버전, Photos 설치 여부, 공용 share 이름/경로, 2단계 인증 사용 여부, 휴지통/홈서비스 활성 여부 등). 모르면 내가 직접 NAS에서 확인하도록 시켜라.
2. 리포 스캐폴딩: backend/ (FastAPI), frontend/ (Vite React TS), docker/ + docker-compose.yml + README + .env.example
3. DSM API 클라이언트 + 로그인(SYNO.API.Auth)부터 구현하고, 내가 실제 NAS로 테스트할 수 있는 최소 동작 지점을 만들어라.
4. 그 다음은 타임라인 뷰 → 선택/드래그앤드롭 → CopyMove/Delete/CreateFolder + BackgroundTask 폴링 → 작업로그/Undo → cross-space 이동 → 관리자 기능 → 라이트박스/EXIF → 폴더 뷰 토글 → Docker 패키징 순서로 진행.

각 단계가 끝날 때마다 멈추고 내가 실제 NAS에서 확인할 수 있게 실행 방법을 알려줘. 한 번에 전부 만들지 말고 검증하며 단계적으로 가자.

먼저 명세서를 읽고, 1번(확인 질문)부터 시작해라.
```

---

## 사용 팁
- Claude Code를 명세서가 있는 폴더에서 실행하면 `NAS_사진정리앱_개발명세서.md`를 바로 읽을 수 있습니다.
- NAS 주소·계정은 프롬프트에 직접 적지 말고, Claude Code가 물어볼 때 `.env`에 넣도록 하세요(자격증명 노출 방지).
- 단계가 끝날 때마다 "다음 단계로" 라고만 해도 명세서 순서대로 이어갑니다.
