# NAS 사진 정리 앱 — 개발 핸드오프 명세서

> Claude Code에서 이 문서를 그대로 읽고 1단계 개발을 시작하기 위한 명세입니다.
> 컨셉·아키텍처·UI·데이터·API·배포·로드맵을 모두 포함합니다.

---

## 1. 한 줄 요약

Synology NAS(Intel Plus 계열) 위에서 **Docker 웹앱**으로 동작하는 사진 정리 도구. 가족 구성원이 각자 DSM 계정으로 로그인해, **공용 폴더와 개인 폴더의 사진을 타임라인으로 보고 / 드래그앤드롭으로 이동·복사·삭제 / 폴더를 만들어 분류**한다. 모든 이동·삭제는 기록되고 **즉시 되돌리기(Undo)** 가능하다.

---

## 2. 핵심 의사결정 (확정됨)

| 항목 | 결정 | 이유 |
|---|---|---|
| 실행 위치 | **NAS Docker 웹앱** | 파일이 있는 곳에서 조작해야 이동·해시·썸네일이 빠름. 항상 켜져 있어 Mac·폰 어디서나 접근. 데이터 외부 유출 없음 |
| 대상 NAS | Intel/AMD Plus 계열 | Docker + 일부 이미지 처리 가능 |
| 주 사용 기기 | Mac/데스크톱 (반응형은 2순위) | 넓은 그리드·폴더 패널·단축키 중심 설계 |
| 인증 | **DSM 계정 로그인** (`SYNO.API.Auth`) | 가족 각자 로그인, 권한을 DSM이 자동 enforce |
| 역할 | **일반(member) / 관리자(admin)** 구분 | 관리자 계정은 다른 가족 개인 폴더까지 접근 |
| 사진 소스 | **Synology Photos 재활용** | 기존 썸네일·EXIF 사용해 빠르게 표시 |
| 주 조작 | **드래그앤드롭** (+버튼 대체) | 직관적, 익숙함 |
| 메인 화면 | **B안 타임라인형** (기본) + **A안 폴더 트리형** (보기 모드 토글) | 날짜로 훑으며 정리 + 특정 폴더 관리 둘 다 |
| 상세 보기 | **큰 라이트박스 + EXIF** | 한 장 크게 보고 좌우로 넘기며 정리 |
| 안전장치 | **이동·삭제 기록 + Undo**, 삭제는 휴지통으로 | 가족 공용 폴더라 실수 복구 필수 |
| 1단계 범위 | 보기 · 이동/복사 · 폴더 생성/분류 · **개인↔공용 이동** · Undo | 중복제거·AI분류는 2~3단계 |

---

## 3. 1단계 기능 범위 (MVP)

포함:
- DSM 로그인 / 세션 유지
- 공용 폴더(Team space) ↔ 내 개인 폴더(Personal space) 탭 전환
- 타임라인 뷰(촬영일 그룹) — 기본 화면
- 폴더 트리 뷰 — 보기 모드 토글
- 사진 다중 선택 (클릭·shift·드래그 박스), 날짜 헤더 단위 선택
- 드래그앤드롭으로 폴더에 이동 / 버튼으로 이동·복사·삭제
- **개인 폴더 → 공용 폴더 이동** (cross-space, 4번 항목 참조)
- **관리자 계정의 가족 전체 개인 폴더 접근** (4.5번 항목 참조)
- 새 폴더 생성, 폴더 이름변경
- 라이트박스(크게 보기) + EXIF(촬영일·카메라·해상도·용량·경로)
- 작업 기록 패널 + Undo (이동/복사/삭제/폴더생성)
- 대량 대비 가상 스크롤 + 페이지네이션

제외(후속 단계):
- 중복 사진 탐지/제거 (2단계)
- AI 자동 분류(인물·장소·사물) (3단계)
- 영상 관리, 공유 링크 생성

---

## 4. ★ 개인 폴더 → 공용 폴더 이동 (핵심 요구)

가족 각자의 개인 폴더에 있는 사진을 공용 폴더로 쉽게 올리는 흐름. 기술적으로 Synology Photos의 **개인 공간(Personal, `SYNO.Foto.*`, 경로 `/homes/<user>/Photos`)** 에서 **공유 공간(Team, `SYNO.FotoTeam.*`, 경로 `/photo`)** 으로 넘기는 cross-space 작업이다.

UX 설계:
- 개인 폴더를 보는 중에도 **드롭 대상 패널에 "공용 폴더" 섹션이 항상 보임.** 사진을 골라 공용 폴더로 그대로 끌어다 놓으면 됨.
- 또는 선택 후 하단 액션바의 **"공용으로 보내기"** 버튼 → 공용 폴더 목적지 선택 다이얼로그.
- 이동/복사 선택 가능: 기본은 **복사**(개인 원본 보존)를 추천값으로, 토글로 이동 선택. (가족 공용 올리기는 보통 원본을 남기고 싶어함 — 단, 최종 추천값은 사용자 확인 후 확정)

구현 주의:
- cross-space 이동은 파일시스템상 다른 share로의 이동이므로, **Foto API의 자체 이동이 안 되면 FileStation `CopyMove`로 처리 후 양쪽 공간 재인덱싱 트리거**가 필요할 수 있음. 두 경로 모두 검증할 것.
- 공유 공간 쓰기 권한이 있는 계정인지 확인(없으면 버튼 비활성 대신 사유 안내).
- 이동 후 Synology Photos 인덱스 동기화 상태 확인(썸네일이 잠깐 비어 보일 수 있음 → 낙관적 UI + 백그라운드 재조회).

---

## 4.5 ★ 관리자 권한 — 가족 전체 개인 폴더 접근 (핵심 요구)

DSM **관리자 그룹(administrators)** 계정으로 로그인하면, 본인 폴더뿐 아니라 **다른 가족 구성원의 개인 폴더까지** 보고 정리할 수 있어야 한다.

역할 판별:
- 로그인 후 `SYNO.API.Auth` / 사용자 정보 조회로 **administrators 그룹 소속 여부**를 확인해 `role = admin | member` 결정.

UX 설계:
- 관리자에게만 상단에 **"가족 구성원 선택" 드롭다운**(또는 사이드 목록)이 보임 → 특정 구성원을 고르면 그 사람의 개인 폴더가 개인 탭에 로드됨.
- 일반 사용자는 이 UI 자체가 없음(본인 개인 + 공용만).
- 관리자가 남의 폴더를 보는 중임을 화면 상단에 **명확히 표시**(예: "보는 중: 아빠의 개인 폴더") — 실수로 남의 사진을 건드리지 않도록.

구현 주의:
- 다른 사용자의 개인 공간은 본인 스코프인 `SYNO.Foto.*` 로는 못 볼 수 있음(개인 Photos는 로그인 사용자 자기 것 기준). 따라서 관리자가 타인 개인 폴더를 볼 때는 **FileStation으로 `/homes/<user>/Photos` 경로를 직접 List**하고, 썸네일은 FileStation 썸네일 API 또는 자체 생성으로 처리하는 경로가 필요.
- 즉 데이터 소스가 두 갈래가 됨: ① 본인/공용 = Foto/FotoTeam API, ② 관리자가 보는 타인 개인 = FileStation `/homes/<user>` 경로. 추상화 레이어로 동일한 화면이 두 소스를 모두 그릴 수 있게 설계.
- `/homes` 접근은 DSM 관리자 권한 + "사용자 홈" 서비스 활성화 전제 → 검증 항목에 포함.
- 모든 관리자 작업도 동일하게 작업로그·Undo 적용(대상 사용자 기록).

---

## 5. 아키텍처

```
[브라우저(Mac/폰)]  ──HTTPS──>  [Docker 컨테이너: 웹앱]
                                   │
                          ┌────────┴─────────┐
                          │ Backend (API)    │
                          │  - DSM 인증 프록시 │
                          │  - 파일 작업       │
                          │  - 작업로그/Undo   │
                          │  - SQLite 인덱스   │
                          └────────┬─────────┘
                                   │ HTTP (DSM Web API)
                          [Synology DSM]
                           - SYNO.API.Auth
                           - SYNO.FileStation.*
                           - SYNO.Foto.* / SYNO.FotoTeam.*
```

핵심 원칙: **파일 자체는 DSM Web API를 통해 조작**한다(직접 볼륨 마운트로 권한을 우회하지 않음 → 가족 멀티유저 권한을 DSM이 enforce). 앱은 그 위에 **작업로그·Undo·앱 상태**만 SQLite로 얹는다.

---

## 6. 권장 기술 스택 (Claude Code 개발용)

- **Backend**: Python **FastAPI** (이미지/해시 처리에 유리, 2단계 중복제거 시 Pillow·imagehash 재사용). 대안: Node/Express.
- **Frontend**: **React + Vite + TypeScript**, **Tailwind**
  - 드래그앤드롭: `@dnd-kit/core` — 멀티 드래그는 선택 상태 + `DragOverlay` 커스텀("n장" 배지), 폴더 드롭은 `useDroppable` (SortableContext 트리 구현 금지)
  - 가상 스크롤: `@tanstack/react-virtual` — 가상화 단위는 사진 1장이 아니라 **justified 행/일(day) 섹션**, 행 높이를 `estimateSize`에 사전 주입
  - justified 레이아웃 계산: `flickr/justified-layout` (순수 계산 라이브러리)
  - 드래그 박스 선택: `@air/react-drag-to-select` (좌표 기반 → 가상화와 호환)
  - 썸네일 블러 플레이스홀더: `thumbhash`
  - 상태: React Query(서버상태) + Zustand(선택/뷰모드 등 UI상태)
  - 구현 함정·근거는 `docs/IMPROVEMENTS.md` B·C절 참조 (작업 시 필수 반영)
- **앱 DB**: SQLite (작업로그·Undo·캐시 인덱스). 단일 컨테이너에 적합.
- **배포**: 단일 **Docker** 이미지 (멀티스테이지: 프론트 빌드 → 백엔드가 정적 서빙). `docker-compose.yml` 제공.
- **인증**: DSM `SYNO.API.Auth`로 사용자 자격증명 검증 → SID 획득 → 서버가 HttpOnly 세션쿠키로 래핑(브라우저에 DSM SID 직접 노출 금지).

---

## 7. Synology DSM Web API 연동 메모

베이스: `http(s)://<NAS>:<port>/webapi/entry.cgi` (구버전은 `auth.cgi`, `FileStation/*.cgi`). 먼저 `SYNO.API.Info`로 각 API의 경로·버전 질의 후 호출.

인증
- `SYNO.API.Auth` (method=login) → `sid` 발급. 이후 모든 호출에 `_sid` 또는 쿠키.
- 로그아웃/세션 만료 처리. 2단계 인증(OTP) 사용 계정 대응 고려.

파일 작업 (FileStation)
- `SYNO.FileStation.List` — 폴더/파일 목록
- `SYNO.FileStation.CreateFolder` — 새 폴더
- `SYNO.FileStation.Rename` — 이름변경
- `SYNO.FileStation.CopyMove` — 복사/이동 (백그라운드 task 반환)
- `SYNO.FileStation.Delete` — 삭제 (백그라운드 task)
- `SYNO.FileStation.BackgroundTask` — 위 작업 진행상태 폴링
- `SYNO.FileStation.Search` — 검색

사진/썸네일/메타데이터 (Synology Photos)
- **개인 공간**: `SYNO.Foto.*` (예: `SYNO.Foto.Browse.Folder`, `SYNO.Foto.Browse.Item`)
- **공유 공간**: `SYNO.FotoTeam.*` (구조 동일, 공용 폴더에 해당)
- 썸네일: `SYNO.Foto.Thumbnail` — `id`, `cache_key`, `_sid` 파라미터로 이미지 URL 구성 (쿠키 없이 접근 가능)
- EXIF/메타: Browse 아이템 응답의 메타 필드 활용
- ⚠️ 비공식 문서이므로 실제 NAS에서 엔드포인트·파라미터를 반드시 검증할 것.

권한·인덱싱 주의
- 공용/개인 접근은 DSM 계정 권한을 따름 → 앱이 따로 권한검사 안 해도 됨(단, 에러 응답 친절히 처리).
- 파일을 FileStation으로 직접 옮기면 Photos 인덱스가 늦게 따라올 수 있음 → 이동 후 재인덱싱/재조회 전략 필요.

---

## 8. 데이터 모델 (SQLite, 앱 자체 상태)

```sql
-- 작업 로그 (Undo의 근거)
operation(
  id            INTEGER PK,
  user          TEXT,            -- 작업 실행자(DSM 사용자)
  target_user   TEXT,            -- 작업 대상 소유자(관리자가 타인 폴더 정리 시)
  type          TEXT,            -- move | copy | delete | mkdir | rename
  space_from    TEXT,            -- personal | team
  space_to      TEXT,
  payload_json  TEXT,            -- 원본/대상 경로 목록, 파일 ID 등
  status        TEXT,            -- pending | done | undone | failed
  created_at    DATETIME,
  undo_deadline DATETIME         -- 휴지통 보존/Undo 가능 기한
)

-- 표시 가속용 캐시(선택)
photo_cache(
  file_id     TEXT PK,
  space       TEXT,
  path        TEXT,
  taken_at    DATETIME,          -- 타임라인 그룹핑 키
  thumb_key   TEXT,
  width INT, height INT, size INT,
  camera      TEXT
)
```

Undo 원칙: 모든 파괴적 작업(이동/삭제)은 **역연산 정보**를 `payload_json`에 남긴다. 삭제는 즉시 영구삭제가 아니라 **NAS 휴지통(#recycle)** 으로 보내고, Undo는 원위치 복원. 이동 Undo는 반대 방향 `CopyMove`.

---

## 9. 화면 명세

### 9.1 공통 셸
- 상단바: 앱명 / 검색 / 로그인 사용자 아바타
- 탭: **[공용 폴더] [내 개인 폴더]** — 보는 공간(space) 전환
- (관리자만) **가족 구성원 선택** 드롭다운 + 남의 폴더 열람 시 "보는 중: ○○의 개인 폴더" 배너 — 상단 고정·고대비 색(주황) + **"내 보기로 돌아가기" 원클릭 버튼**, 해당 모드의 작업은 기록에 관리자 수행으로 명시
- 우상단 보기 토글: **[타임라인] [폴더]**
- 하단 액션바: 선택 매수 + [이동] [복사] [공용으로 보내기] [삭제]
- 우측(또는 슬라이드) **작업 기록 패널**: 최근 작업 + 각 항목 [되돌리기]

### 9.2 타임라인 뷰 (기본)
- 촬영일 기준 그룹, 날짜 헤더 + 그 아래 사진 그리드
- 날짜 헤더에 "이 날짜 전체 선택" — 전체/부분 체크 상태는 선택 집합에서 파생(이중 상태 관리 금지)
- 좌측 폴더/목적지 패널이 드롭 타깃 (개인 보는 중에도 공용 폴더 섹션 노출 → 4번 기능)
- 가상 스크롤로 수만 장 대응
- **justified layout**(행 높이 균등, 원본 비율 유지·크롭 없음) — square grid 비채택
- 데이터는 월/일 버킷 **count-first**: 개수 메타만 먼저 받아 섹션 높이 사전 할당 → 스크롤바가 전체 아카이브를 대표
- 우측 **날짜 스크러버**(드래그 시 연/월 라벨)로 임의 시점 점프
- ⚠️ 큰 버킷의 geometry 동기 일괄 계산 금지(브라우저 프리즈) — 청크/비동기 분할
- 썸네일 3단계 로딩: thumbhash(즉시 블러) → 소형 → 대형 프리뷰
- 공용 공간도 모든 구성원에게 타임라인 제공(Synology Photos는 Full Access 전용 → 차별화 지점)

### 9.3 폴더 뷰 (토글)
- 좌측 폴더 트리(파일탐색기 느낌), 우측 해당 폴더 사진 그리드
- 폴더 트리가 곧 드롭 타깃, "새 폴더"

### 9.4 라이트박스
- 사진 클릭 → 전체화면 크게 보기, ←/→ 로 넘기기
- EXIF 패널: 촬영일시, 카메라/렌즈, 해상도, 용량, 경로/공간 — **우측 슬라이드-인**(`i` 토글), 열림 상태는 다음 사진에도 유지
- 라이트박스에서도 이동/복사/삭제/공용으로 보내기 가능
- 표준 단축키: `←/→` 넘기기 · `i` 정보 · `Delete` 휴지통 · `ESC` 닫기 · `Shift+?` 도움말
- **삭제 시 닫지 않고 다음 사진으로 자동 전진**(연속 정리 워크플로), 다음/이전 이미지 프리페치

상호작용 규칙
- 다중 선택: 호버 체크 서클(**사진 클릭=열기 / 체크 클릭=선택** 분리) / Shift 범위(**Shift 호버 시 범위 프리뷰 하이라이트**) / 드래그 박스
- 작업 완료 시 선택 자동 해제, ESC/X로 명시적 해제
- 드래그 시작 시 "n장" 썸네일 스택 고스트, 유효 드롭 대상 하이라이트 + 무효 대상 not-allowed 커서, 폴더 hover 시 자동 펼침(spring-loaded)
- 드래그 기본=**이동**, **Option(⌥)=복사**(커서에 + 배지) — Finder 관례
- 파괴적 작업은 토스트로 "n장 이동됨 · [되돌리기]" 즉시 노출(확인 팝업 최소화, 대신 Undo로 안전 확보) — 액션 있는 토스트는 **7–10초** 유지 + 호버 시 타이머 정지
- 10초 초과 벌크 작업은 개수 기반 진행 바("34/120장 이동 중") + 백그라운드 진행
- **영구 삭제만 확인 다이얼로그**(관리자가 타인 폴더에서 수행 시 추가 확인), 파괴적 버튼은 일반 버튼과 색·간격 분리

---

## 10. Docker 배포

- 단일 이미지, 멀티스테이지 빌드(프론트 정적 → FastAPI가 서빙)
- `docker-compose.yml`:
  - 포트 매핑(예: 9800)
  - 환경변수: `DSM_BASE_URL`, `DSM_PORT`, 세션 시크릿 등
  - SQLite 보존용 볼륨 1개
- DSM의 Container Manager에서 바로 올릴 수 있게 README에 절차 명시
- HTTPS: DSM 리버스 프록시 뒤에 두는 구성 권장

---

## 11. 단계별 로드맵

- **1단계 (지금)**: 보기 · 이동/복사 · 폴더 분류 · 개인↔공용 이동 · Undo
- **2단계**: 중복 사진 탐지/제거 — 상세 설계는 `docs/IMPROVEMENTS.md` D절 (요약: SHA-256 정확 중복 + `imagehash` pHash 64bit Hamming ≤ 5 안팎·사용자 슬라이더. 해시는 Synology 썸네일본에 계산해 `photo_cache`에 영속화. 잡은 SQLite 잡 테이블 + 워커로 진행률·재개 지원. UX는 dry-run 미리보기 → 그룹별 기준(reference) 파일 자동 선택 → 휴지통 + Undo)
- **3단계**: AI 자동 분류 — 인물(얼굴)·장소(GPS)·사물 태깅으로 자동 앨범/폴더 제안. NAS 사양에 맞춰 경량 모델 또는 배치 처리

---

## 12. Claude Code 첫 작업 순서 (제안)

1. 리포 스캐폴딩: `backend/`(FastAPI), `frontend/`(Vite React TS), `docker/`
2. **DSM API 클라이언트 + 로그인** 먼저 구현하고 **실제 NAS로 검증**(엔드포인트·버전·필드 확인) — 가장 불확실한 부분이라 1순위
3. 타임라인 뷰: Foto/FotoTeam Browse → 날짜 그룹핑 → 썸네일 표시(가상 스크롤)
4. 선택 + 드래그앤드롭 + 폴더 패널
5. CopyMove/Delete/CreateFolder 연결 + BackgroundTask 폴링
6. 작업로그 + Undo + 휴지통 삭제
7. 개인→공용 cross-space 이동(두 경로 검증) + 관리자 역할/타인 폴더 접근(`/homes`)
8. 라이트박스 + EXIF
9. 폴더 뷰 토글
10. Docker 패키징 + compose + README

---

## 13. 개발 시작 전 NAS에서 확인할 것 (검증 항목)

- DSM 버전(7.x?) 및 Synology Photos 설치/버전
- `SYNO.API.Info` 응답으로 FileStation·Foto·FotoTeam의 실제 path/version
- 2단계 인증 사용 여부(로그인 흐름 영향)
- 공용 폴더 share 이름·경로, 개인 Photos 경로
- cross-space(개인→공용) 이동을 Foto API로 직접 가능한지, 아니면 FileStation+재인덱싱이 필요한지
- 휴지통(#recycle) 활성 여부(삭제 Undo 전제)
- DSM 로그인 타임아웃 설정값(제어판 보안) — sid 만료 주기가 앱 세션(8h)보다 짧을 수 있음(만료 시 401 처리 전제)
- DSM Auto Block 설정 — 앱(도커 게이트웨이 IP)이 로그인 실패 누적으로 차단되지 않도록 허용 IP 목록 등록
- **사용자 홈(user home) 서비스 활성 여부** 및 관리자 계정의 `/homes/<user>` 접근 권한 (관리자 기능 전제)
- 관리자가 타인 개인 Photos를 볼 때 Foto API로 가능한지, FileStation `/homes` 경로가 필요한지 확인
```
```

---

### 참고 출처
- [Synology File Station API Guide (공식 PDF)](https://global.download.synology.com/download/Document/Software/DeveloperGuide/Package/FileStation/All/enu/Synology_File_Station_API_Guide.pdf)
- [Copy or Move Files or Folders — Synology KB](https://kb.synology.com/en-global/DSM/help/FileStation/copymove?version=7)
- [Delete Files or Folders — Synology KB](https://kb.synology.com/en-global/DSM/help/FileStation/delete?version=7)
- [Synology Photos API (비공식 문서, GitHub)](https://github.com/zeichensatz/SynologyPhotosAPI)
- [synology-api 파이썬 래퍼 (참고 구현)](https://github.com/N4S4/synology-api)
