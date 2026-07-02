# 개선 필요사항 종합 (전체 리뷰 결과 — 2026-07-02)

> 이 문서는 **코드 리뷰 + 오픈소스 벤치마크**(Immich·PhotoPrism·LibrePhotos·Photoview·Damselfly·Czkawka·dupeGuru·synology-api)
> **+ UI/UX 벤치마크**(Google Photos·Immich·Synology Photos·Finder·NN/g)의 결과를 통합한 **작업 기준 문서**입니다.
>
> **규칙: 모든 구현 작업은 착수 전에 이 문서의 관련 절을 확인하고, 해당 항목을 반드시 반영한 뒤 체크박스를 갱신합니다.**
> (프로젝트 `CLAUDE.md`에 강제 규칙으로 명시됨)

---

## A. 백엔드 수정 — 1단계 기능 개발 전 선행

### A-1. [HIGH] 로그인 자격증명이 GET 쿼리스트링으로 전송됨
- [x] 수정 (2026-07-02) — `_send`에 POST 지원 추가, `login()`을 POST 폼으로 전환
- 위치: `backend/app/dsm/client.py` — `_send()`가 항상 `http.get(url, params=...)` → 로그인 시 비밀번호가 URL에 실려 DSM 웹서버·리버스 프록시 로그에 남을 수 있음.
- 수정: `_send`에 POST(form body) 지원 추가, 최소한 `login()`은 POST로 전환. DSM 7 `SYNO.API.Auth`는 POST 지원.

### A-2. [HIGH] DSM sid 만료 처리 부재 (앱 세션과 수명 불일치)
- [x] 수정 (2026-07-02) — `main.py`에 `DsmError` 예외 핸들러 추가. 세션 무효 코드 → 401 + 세션/쿠키 삭제, 그 외 → 502. `system.py`는 핸들러에 위임.
- 앱 세션 TTL 8h(`config.py`) vs DSM sid는 DSM 보안 설정에 따라 **15분 만에 만료 가능**(기본 최대 7일 — [DSM Login Web API Guide](https://kb.synology.com/en-global/DG/DSM_Login_Web_API_Guide/2)).
- 현재 `api/system.py`는 DSM 오류를 502로 반환 → 프론트가 재로그인 유도 불가.
- 수정: `DsmError` 세션 무효 코드 **106(timeout)/107(중복 로그인)/119(sid 무효)**를 공용 예외 핸들러로 잡아 **앱 세션 삭제 + 401 반환**. (당초 105도 포함했으나 105는 "권한 부족"이라 재로그인으로 풀리지 않아 제외 — `errors.SESSION_INVALID_CODES` 참조.) 이후 모든 엔드포인트가 자동 혜택.

### A-3. [MED] 역할 판별을 `is_manager` 기반으로 교체
- [x] 수정 (2026-07-02) — `detect_role`을 `SYNO.FileStation.Info`의 `is_manager` 기반으로 교체, `/homes` 접근은 `detect_can_browse_homes`로 분리. 세션·`UserInfo`·프론트 타입에 `can_browse_homes` 추가(스키마 마이그레이션 포함).
- 현재 `api/auth.py detect_role()` — `/homes` 목록 성공 여부로 admin 판별. **user home 서비스가 꺼져 있으면 진짜 관리자도 member로 오판**.
- 수정: `SYNO.FileStation.Info`(get)의 **`is_manager`** 필드로 role 판별. `/homes` 접근 가능 여부는 별도 capability(`can_browse_homes`)로 분리 — 관리자 UI 활성화 조건과 역할을 분리(명세 4.5의 "사유 안내"와 연결).

### A-4. [MED] 로그인 시도 제한 + DSM Auto Block 대응
- [x] 수정 (2026-07-02) — `rate_limit.py`(SQLite `login_attempt`) + `config` 설정(기본 10분/5회), login 라우터에 429 적용. README에 DSM 허용 IP 안내 추가.
- 앱이 로그인 프록시라서 가족 누군가 비밀번호를 반복해 틀리면 **DSM Auto Block이 도커 컨테이너/게이트웨이 IP를 차단 → 전 가족 로그인 불가** ([DSM Auto Block](https://kb.synology.com/en-global/DSM/help/DSM/AdminCenter/connection_security_account?version=6)).
- 수정: ① 앱 레벨 로그인 시도 제한(예: 계정당 5회/10분, SQLite로 충분) ② README에 "DSM 허용 IP 목록에 도커 게이트웨이 IP 추가" 안내 ③ sid 재사용 철저(매 요청 로그인 금지 — 현 구조는 이미 준수).

### A-5. [LOW] 인프라/품질 묶음
- [x] `config.py` `session_secret` — 미사용이라 제거(쿠키가 무작위 토큰이라 서명 불필요). `.env.example`도 정리.
- [x] `docker/Dockerfile` — `npm install` → **`npm ci`**, **non-root USER**(appuser) 추가.
- [x] `docker-compose.yml` — `/api/health` 기반 **healthcheck** 추가(python urllib).
- [x] `db.py` — `PRAGMA journal_mode=WAL` 설정. (2단계 해시 저장 시 sync SQLite → 스레드풀 오프로딩 재검토)
- [x] `session_store.purge_expired` — 시작 시 1회 + **로그인마다 정리**(별도 백그라운드 스위퍼 없이 주기화).
- [x] `errors.py` — `SYNO.Foto.*`/`SYNO.FotoTeam.*` 에러코드 테이블 추가(실 NAS로 검증 필요).
- [x] 단위 테스트 추가 — `errors.message_for`, `session_store`, `rate_limit`, `DsmClient`(httpx `MockTransport`). **26개 통과**. `requirements-dev.txt`/`pytest.ini` 추가.

---

## B. 프론트 UI/UX 설계 결정 — 화면 구현 시 적용

> **구현 현황(2026-07-02, 1단계 타임라인 마일스톤)**: B-1·B-3 완료, B-2·B-4·B-5·B-6 부분 완료(파일 작업 API/작업기록과 함께 완성되는 항목은 다음 단계). 미체크 항목의 사유는 각 절 참조. NAS 없이 개발 가능하도록 백엔드 **MOCK_MODE** 추가(결정적 가짜 데이터 + SVG 썸네일). DSM 실연동 코드는 `backend/app/photos/dsm_source.py`에 있으며 **실 NAS 미검증**(파일 상단 검증 목록 참조).

### B-1. 타임라인
- [x] 월/일 버킷 **count-first** 방식: 개수 메타데이터만 먼저 받아 섹션 높이 사전 할당 → 스크롤바가 전체 아카이브를 대표 ([Building the Google Photos Web UI](https://medium.com/google-design/building-the-google-photos-web-ui-45b714dfbed1), [Immich Timeline](https://deepwiki.com/immich-app/immich/3.5-timeline-and-asset-display)) — `GET /api/photos/buckets` + `lib/rowModel.ts` 플레이스홀더 행
- [x] 우측 **날짜 스크러버**(드래그 시 연/월 라벨)로 임의 시점 점프 — `Scrubber.tsx`
- [x] **justified layout**(행 높이 균등, 원본 비율 유지·크롭 없음) — square grid 비권고(가족 사진은 세로/가로 혼재)
- [x] ⚠️ 큰 버킷의 geometry **동기 일괄 계산 금지** — **일 단위 버킷 + 버킷별 지연 계산·메모이제이션**으로 구조적으로 회피 ([Immich #28861](https://github.com/immich-app/immich/issues/28861) 프리즈 사례)
- [x] 공용 공간도 **모든 구성원에게 타임라인 제공** — 공용/개인 동일한 타임라인 UI(권한은 DSM이 enforce)

### B-2. 썸네일 로딩
- [ ] (부분) 3단계: **thumbhash(즉시 블러) → 소형 webp → 대형 프리뷰**. 현재는 `placeholder_color`(단색) → 소형 → 대형 **2단계+색상**으로 구현. thumbhash는 이미지 픽셀 접근이 필요해 **photo_cache 파이프라인(D절)과 함께** 도입 — API 응답에 `placeholder_color` 슬롯을 이미 마련해 교체만 하면 됨
- [x] 1단계에서는 Synology Photos 썸네일(`SYNO.Foto.Thumbnail`) 재활용이 우선 — `dsm_source.thumbnail()` 프록시로 구현(실 NAS 미검증)

### B-3. 다중 선택 (Google Photos 패턴)
- [x] 호버 시 좌상단 **체크 서클** — 별도 "선택 모드 버튼" 불필요
- [x] **사진 클릭=열기 / 체크 클릭=선택** 분리 유지(선택 모드에선 클릭=토글)
- [x] **Shift 호버 시 범위 프리뷰 하이라이트** — `store/timeline.ts` previewIds
- [x] 날짜 헤더 체크의 전체/부분 상태는 **선택 집합에서 파생**(이중 상태 관리 금지 — [Immich #17304](https://github.com/immich-app/immich/issues/17304) 버그 사례)
- [x] 작업 완료 시 선택 자동 해제 + Undo 토스트 (`useFileOps` afterOperation) + ESC/X 해제
- [x] 드래그 박스 선택은 벤치마크 초과 스펙(Google Photos·Immich에 없음) — `@air/react-drag-to-select` 좌표 기반, 배경 드래그만 시작(셀 드래그는 DnD)

### B-4. 드래그앤드롭 (Finder 관례 — 주 사용층 Mac)
- [x] 드래그 기본=**이동**, **Option(⌥)=복사** — 고스트에 모드 라이브 표시(실제 복사/이동 동작은 파일 작업 단계)
- [x] 고스트: 대표 썸네일 스택 + **"n장" 배지** (dnd-kit `DragOverlay` 커스텀)
- [ ] (부분) 유효 드롭 폴더 하이라이트 구현 / 무효 대상 not-allowed 커서는 후속
- [ ] 폴더 hover 시 자동 펼침(spring-loaded folders) — 폴더 트리 뷰와 함께 후속
- [x] **드롭 확인 다이얼로그 금지** — 즉시 실행 + Undo (명세 원칙 그대로)

### B-5. 라이트박스 (Google Photos/Immich 표준)
- [x] 단축키: `←/→` 넘기기 · `i` 정보 패널 · `Delete` 휴지통 · `ESC` 닫기 · `Shift+?` 도움말
- [x] EXIF 패널은 **우측 슬라이드-인**(`i` 토글), 열림 상태는 다음 사진에도 유지 (하단 패널 비권고)
- [x] **삭제 시 닫지 않고 다음 사진으로 자동 전진** — 연속 정리(culling) 워크플로의 핵심
- [x] 다음/이전 이미지 프리페치
- [x] 라이트박스 내 "폴더로 이동" 버튼 — 삭제·이동(FolderPickerDialog) 버튼 구현됨

### B-6. Undo / 확인 / 진행률 (NN/g + Gmail)
- [x] 가역 작업(이동/휴지통행 삭제)은 **확인 팝업 없이 Undo 토스트** ([NN/g Confirmation Dialogs](https://www.nngroup.com/articles/confirmation-dialog/)) — 이동/복사/삭제/폴더생성 전부 즉시 실행 + "되돌리기" 액션 토스트
- [x] 액션 버튼 있는 토스트는 **7–10초** 유지 + 호버 시 타이머 정지 (3초는 너무 짧음) — 8초 + 호버 정지(`Toasts.tsx`)
- [x] **작업 기록 패널이 토스트의 안전망** — OperationsPanel에 항목별 [되돌리기] 구현됨
- [ ] **10초 초과 벌크 작업은 개수 기반 진행 바**("34/120장 이동 중") + 백그라운드 진행 ([NN/g Progress Indicators](https://www.nngroup.com/articles/progress-indicators/))
- [ ] **영구 삭제만** 확인 다이얼로그("n장 영구 삭제" 명시) — 휴지통 30일 보존 후 영구삭제는 Immich 패턴
- [ ] 파괴적 버튼은 일반 버튼과 색·간격으로 분리(인접 배치가 사고 유발)

### B-7. 관리자 모드 (impersonation 배너 표준)
- [x] "보는 중: ○○의 개인 폴더" 배너 — ImpersonationBanner 구현됨(주황 고정 + 원클릭 복귀)
- [x] 해당 모드의 모든 작업을 작업 기록에 **"관리자 수행"으로 명시** — OperationsPanel에 `대상: ○○ (관리자 수행)` 표기 구현됨
- [ ] 타인 컨텍스트에서 고위험 작업(영구 삭제)은 **추가 확인**

---

## C. 프론트 스택 확정 + 구현 함정

| 역할 | 라이브러리 | 주의점 |
|---|---|---|
| justified 계산 | `flickr/justified-layout` | 순수 계산 라이브러리(렌더 무관). 가상화 단위는 사진 1장이 아니라 **justified 행/일(day) 섹션** |
| 가상 스크롤 | `@tanstack/react-virtual` | [공식 sticky 예제](https://tanstack.com/virtual/v3/docs/framework/react/examples/sticky)가 날짜 헤더 패턴 그대로. 행 높이를 `estimateSize`에 사전 주입 |
| DnD | `@dnd-kit/core` | **멀티 드래그 네이티브 미지원**([#120](https://github.com/clauderic/dnd-kit/issues/120)) → 선택 상태 + `DragOverlay` 커스텀. **가상 리스트에선 DragOverlay 필수**(원본 언마운트 대비). 폴더 드롭은 `useDroppable`만으로 충분 — SortableContext 트리 구현 금지 |
| 드래그 박스 선택 | `@air/react-drag-to-select` | 좌표만 넘겨주는 설계 → 가상화와 호환(좌표→그리드 인덱스 역산). DnD와의 충돌은 PointerSensor `activationConstraint.distance`로 분리(빈 영역=박스 선택, 썸네일 위=드래그) |
| 블러 플레이스홀더 | `thumbhash` | BlurHash보다 작고 디테일 좋음 |

**피해야 할 함정 3가지** — 전부 회피 구현됨(2026-07-02)
1. 큰 버킷 geometry 동기 일괄 계산 → 브라우저 프리즈 (Immich #28861) → **일 단위 버킷 + 버킷별 지연 계산·메모이제이션**(`lib/rowModel.ts`)
2. dnd-kit 멀티 드래그를 기본 기능으로 착각 / DragOverlay 없이 가상 리스트에서 드래그 → **선택 스냅샷 + DragOverlay 커스텀 고스트**(`TimelineScreen.tsx`)
3. 드래그 박스 선택과 DnD 드래그 시작 충돌 → **activation distance 8px + 시작점 분기**(셀=DnD, 배경=박스 선택, `shouldStartSelecting`)

**v1 한계 해소 현황(2026-07-02)**:
- ~~위쪽 버킷 로드 시 스크롤 밀림~~ → **스크롤 앵커링 구현**(첫 가시 행의 날짜 헤더 키에 앵커, useLayoutEffect에서 오프셋 델타 보정 — Google Photos 기법)
- ~~드래그 중 엣지 자동 스크롤~~ → dnd-kit **기본 autoScroll**이 스크롤 가능 조상을 자동 감지(별도 코드 불필요 확인)
- ~~라이트박스 이동 버튼~~ → 폴더 피커 연결 구현
- ~~spring-loaded 폴더~~ → 폴더 뷰 목록에서 드래그 호버 600ms 시 자동 열림
- (유지) 박스 선택은 화면에 마운트된 셀만 대상 — 가상화 특성상 의도된 트레이드오프

---

## D. 2단계(중복 제거) 설계 확정 — **구현 완료 (2026-07-02)**

명세 11장 방향(체크섬 + imagehash)이 벤치마크로 검증됨. 구체화:

- [x] **2단계 탐지**: SHA-256(정확 중복) + **pHash 64bit**(near-duplicate, **Hamming ≤ 5** 기본 — 0~2 사실상 동일, ~5 유사, 10+ 다른 사진). 임계값은 사용자 조절 슬라이더(0~7)로 노출(Czkawka 패턴)
  - **편차 기록**: `imagehash` 패키지 대신 **자체 pHash 구현**(`photos/hashing.py`, Pillow만 의존) — imagehash는 numpy+scipy를 끌고 와 NAS 컨테이너가 무거워짐. 알고리즘 동일(32×32 그레이스케일→DCT-II→8×8 저주파→중앙값 비트), 실이미지 단위 테스트로 검증(재압축=지각적 동일, 소규모 편집=near, 구조 다름=far). DSM 스캔 규모에서 필요 시 numpy 전환
- [x] 해시는 **Synology 썸네일 다운로드본에 계산**(원본 전송 회피) — DSM 소스는 sm 썸네일 bytes로 실계산(실 NAS 검증 항목: 동일 원본→동일 썸네일 전제), mock은 중복 클러스터를 심은 결정적 시뮬레이션(복사본은 원본 해시 상속 → 복사→스캔→정확 중복 검출 데모)
- [x] `photo_cache`에 `sha256`, `phash` 컬럼 추가 + `taken_at`/`space` 인덱스 — **해시 영속화로 재스캔 시 재계산 회피**(중단된 스캔도 자연 재개)
- [x] 전수 쌍 비교(O(n²), dupeGuru 반면교사) 대신 **멀티 인덱스 버킷팅**(8밴드×8비트 — 비둘기집으로 Hamming ≤ 7 재현율 보장) + union-find
- [x] **잡 처리**: Redis 없이 **SQLite `job` 테이블 + asyncio 워커 태스크**. 진행률(processed/total) 폴링, 취소, 서버 재시작 시 running→failed 전환+해시 영속화 기반 재개. (썸네일은 Synology 재활용이라 스캔→해시 단일 단계로 충분 — 체이닝 불필요)
- [x] **UX**: 그룹 목록 자체가 dry-run(삭제 예정 표시 + 절약 용량) → 그룹별 **기준(reference) 파일 자동 선택**(해상도→용량→촬영일, 클릭으로 뒤집기 — dupeGuru 패턴) → 기존 삭제 플로우 재사용(휴지통 + 작업로그 + **되돌리기 토스트**). 그룹은 절약량 상위 N개 페이지네이션(수천 카드 렌더 방지)
- [ ] PhotoPrism식 Stacking(비파괴 대안) — 옵션 검토 항목으로 유지(미구현)
- [x] CLIP 임베딩 기반 탐지(Immich 방식)는 NAS 사양·목적상 **비권고** — 도입하지 않음(설계 준수)

---

## E. DSM 연동 참고 (구현 시 상시 참조)

- 조회·메타데이터·썸네일 = `SYNO.Foto.*`(개인) / `SYNO.FotoTeam.*`(공유 — **네임스페이스 분기가 최대 함정**), 삭제·이동 = `SYNO.FileStation.*` 역할 분담. Photos item ↔ 실제 파일 경로 매핑 관리 필요
- 2FA: `otp_code` + **device_name/device_id 저장으로 "신뢰 장치" 등록 → 이후 OTP 생략** 흐름 지원 검토 ([N4S4/synology-api](https://github.com/N4S4/synology-api) 참고 — 단 requests 기반 sync라 직접 의존은 비권고, 현 async 클라이언트 유지)
- 비공식 Photos API 문서: [zeichensatz/SynologyPhotosAPI](https://github.com/zeichensatz/SynologyPhotosAPI)
- API 버전은 런타임 `SYNO.API.Info` 조회(현 구조 유지 — 하드코딩 금지)

---

## 반영 현황

- [x] 명세서(`NAS_사진정리앱_개발명세서.md`) 6·9·11·13장에 위 결정 반영 (2026-07-02)
- [x] README에 이 문서 링크 추가
- [x] 프로젝트 `CLAUDE.md`에 강제 참조 규칙 명시
- [x] A절 백엔드 수정 구현 (2026-07-02) — A-1~A-5 완료, 단위 테스트 26개 통과
- [x] B·C절 기반 **타임라인 마일스톤** 구현 (2026-07-02) — count-first 버킷 API + MOCK_MODE(NAS 불필요), justified 행 가상화, 스크러버, 선택 3종(체크서클/Shift 프리뷰/박스), DnD 셸(DragOverlay·폴더 드롭), 미니 라이트박스, 토스트
- [x] **파일 작업 + 작업로그/Undo 마일스톤** 구현 (2026-07-02) —
  - 백엔드: PhotoSource 변이 프로토콜(move/copy/delete/undo 프리미티브), mock 상태 오버레이(cross-space 이동·복사·휴지통·복원이 실제로 동작), `operations.py` 작업로그 서비스(역연산 payload, 7일 undo 기한), `/api/photos/ops/*`·`/api/ops` 라우터, target_user 감사 로깅(관리자만 허용)
  - 프론트: `useFileOps` 훅(선택 자동 해제 + 정밀 무효화 + **되돌리기 액션 토스트**), 폴더 드롭→실제 이동(⌥=복사), 액션바+폴더 피커(공용 보내기는 복사 기본 — spec ch.4), **작업 기록 패널**(항목별 되돌리기), 라이트박스 완성(`i` EXIF 패널·Delete 자동 전진·Shift+? 도움말), **폴더 뷰**(spec 9.3), 관리자 셸(멤버 선택 + 주황 배너 + 감사 로깅)
  - 검증: pytest 56개 통과, tsc+vite 빌드 통과, mock 서버 e2e 스모크(이동→폴더→삭제→undo→복원), **Docker 이미지 빌드+컨테이너 기동 검증**(헬스체크·정적 프론트·non-root)
- [x] **D절 기반 2단계(중복 제거) 구현** (2026-07-02) — 자체 pHash(Pillow만)+SHA-256, photo_cache 해시 영속화, SQLite 잡+asyncio 워커(진행률/취소/재개), 8밴드 버킷팅+union-find 그룹핑, 중복 정리 뷰(스캔 진행바·임계값 슬라이더·reference 뒤집기·dry-run·기존 삭제/undo 재사용). v1 한계 4건 해소(스크롤 앵커링, 라이트박스 이동, spring-loaded, autoScroll 확인). 테스트 69개 통과
- [~] DSM 실연동 검증 (실 NAS 192.168.1.113, DSM 7.2 — 진행 중)
  - [x] 조회: 로그인·역할판별(is_manager)·folders·Timeline(v1 고정)·KST buckets(62636장)·items·thumbnail — 전부 정확 동작
  - [x] **파일 작업(공용 공간): 이동/복사/삭제/폴더생성 + 각 undo 전부 실 NAS 검증** (iPad 폴더에서 실행 후 원상복구). 발견·해결: photo 휴지통 비활성→앱 관리 휴지통(`/photo/#trash/t<ns>/`)으로 삭제/복원, `#`폴더는 계층별 생성, 순수숫자 폴더명 금지(`t` 접두), item→경로는 Browse.Item get+folder
  - [x] **개인 공간(SYNO.Foto) 검증** — 프리픽스 `/home/Photos`(=`/homes/<user>/Photos`) 확정. buckets/items(29047장) count 정확, `/home/Photos`에서 CopyMove/CreateFolder/Delete 이동→복구 실동작(s.png). **발견·수정한 버그**: 하루 2148장(모바일 백업) 날짜에서 `items()`가 limit 1000에 잘림 → 페이지네이션으로 전량 반환
  - [x] **cross-space 이동(개인↔공용)** — `/photo` ↔ `/home/Photos` 양방향 CopyMove 실검증(에러 없음, 원상복구). 앱 `move`는 src/dest space별 프리픽스 계산으로 지원
  - [x] **폴더 트리 lazy 구현** — 실 NAS 폴더가 **1500+**, 전량 재귀는 40초라 비현실적. `SYNO.Foto.Browse.Folder`는 계층적(`id`로 직속 하위)이므로 **한 레벨씩 lazy 로드**(`folders(parent_id)`)로 재구현. 최상위(느림 11초)는 캐시+병렬, 하위는 즉시(0.03초). id→(space,path) 메타캐시로 파일작업 경로 해석. 프론트 `FolderTree` 재귀 컴포넌트(펼칠 때 하위 fetch, 드롭 대상). 실 NAS 이동→undo 통합 검증
  - **동작 노트**: 파일 이동/undo 후 Photos 재인덱싱으로 item id가 바뀜(예 1692→92388). 실사용은 작업마다 프론트가 buckets/items/folder-items 무효화·재조회하므로 새 id를 받아 정상. stale id 재사용만 주의
  - [x] **2단계 dedup 실스캔** — 개인 공간 29047장 스캔(28529 해시, ~518 broken 썸네일 skip, ~9분 @ 동시8·청크100). 결과 **8214 그룹, 24GB 절약가능**(exact 정확중복 + similar 유사). 연속촬영/버스트가 pHash로 정확히 묶임 — 자체 pHash 실데이터 검증 완료. **개선**: 스캔 병렬화(동시8)+청크(100)단위 진행률·저장, 개별 썸네일 실패는 skip(전체 실패 방지)
  - [~] **관리자 타인 폴더** — members 조회·`/homes` 접근·권한·UI 셸(멤버선택/배너/target_user 감사로깅) 검증 완료. 단 이 NAS의 타인들(cosmos/jason/ruthie/tmbackup/admin)은 개인 Photos가 없어(홈 비어있음) **실데이터 검증 대상 부재**. 타인 개인 사진 데이터 소스(FileStation `/homes/<user>/Photos`) 구현은 대상 데이터가 생길 때 진행
  - [x] **공용 공간 dedup 스캔** — 62626장 해시(~25분), **10582 그룹, 66GB 절약가능**. 대용량 영상의 정확 중복(원본명+날짜명으로 이중 저장된 mp4/MOV)이 다수 검출 — SHA-256 정확중복이 실데이터에서 큰 효과. 두 공간(공용+개인) 해시가 photo_cache에 영속(브라우저 중복정리 탭에서 즉시 조회)
  - [x] **폴더 뷰 우측 메인 드릴인(Finder식)** (2026-07-02) — 좌측 트리뿐 아니라 우측 메인창에서도 하위 폴더 카드로 탐색. 브레드크럼 + `FolderCard`(클릭=드릴인, 드롭 대상) + 직속 사진. 좌측 트리 선택 시 경로 리셋
  - **동작 노트(사진 표시 범위)**: `folder_items`(SYNO.Foto.Browse.Item, folder_id 필터)는 **해당 폴더 직속 사진만** 반환(하위 폴더 사진 미포함, 실 NAS 확인). 따라서 하위 폴더만 있는 **중간 폴더는 사진 0** — 로딩 문제 아님. 리프 폴더로 드릴인하면 사진이 보임. UX: 중간 폴더에서 "직접 담긴 사진 없음, 하위 폴더를 열어 보세요" 안내 추가
  - [x] **`folder_items` 페이지네이션 버그 수정** (2026-07-02) — 리프 폴더가 1000장을 넘으면 limit 1000에 잘리던 문제를 `items()`와 동일하게 전체 페이지 순회로 수정
  - [x] **폴더 뷰 리스트/아이콘 전환 + 사진 수 배지 + 패널 리사이즈** (2026-07-02) — ① 하위 폴더 섹션에 `▦ 아이콘/☰ 리스트` 토글(localStorage 유지, 두 페인 공통). ② 폴더별 직속 사진 수 배지: 백엔드 `folder_count`(DSM `SYNO.Foto.Browse.Item`의 `count` 메서드 — 전체 페이징 없이 1콜) + `GET /api/photos/folder-counts?ids=`(레벨당 1회 배치, 병렬, 실패 id는 생략해 배지만 숨김; **실 NAS에서 count 메서드 응답 확인 필요**). ③ 좌측 패널(폴더 뷰 트리 + 타임라인 패널) 드래그 리사이즈 — `useResizableWidth` 훅(pointer capture, 160–480px, localStorage 유지)
  - [x] **타임라인 빈 화면 버그 수정** (2026-07-02) — `TimelineView`의 ResizeObserver 부착 effect가 `[]` 의존성이라, buckets 로딩 스피너 조기 반환 중에 한 번 실행되고 끝나 그리드 마운트 후에도 width=0 → 행이 전혀 안 그려지는 잠복 버그(마운트·쿼리 타이밍에 따라 간헐 발생). `scrollEl` 상태(콜백 ref)를 deps로 걸어 그리드 실마운트 시 재부착으로 수정
  - [x] **타임라인 좌측 폴더 패널에 내비게이션 역할 부여** (2026-07-02) — 기존엔 드롭 대상 역할만 있어 클릭해도 무반응(무의미해 보임). 폴더 클릭 시 **폴더 보기로 전환 + 해당 폴더 열기**(store `pendingFolderPath`/`openFolderView` → FolderView가 소비해 pane A에 적용). 안내 문구도 두 역할(클릭=열기, 드래그=이동) 명시로 갱신. mock e2e 확인
  - [x] **폴더 뷰 분할(듀얼 페인) 정리 모드** (2026-07-02) — commander 패턴: 폴더 뷰에 `▤ 단일/▥ 분할` 토글. 분할 시 두 `FolderPane`이 독립 탐색(각자 브레드크럼·드릴인), 클릭한 페인이 활성(전역 선택 소유·파란 테두리), 가운데 액션바(**이동 →/←·복사·삭제**, 방향은 활성 페인 기준)로 반대쪽 폴더에 즉시 실행+Undo 토스트. DnD도 페인 간 동작(비활성 페인 배경+폴더 카드가 드롭 대상, droppable `data.folderId`로 페인별 id 충돌 회피). 메인 페인을 `FolderPane.tsx`로 추출해 단일/분할 공용. **부수 수정**: `PhotoItem.space?` 아이템 단위 space 전파 — 폴더 뷰가 개인 폴더 사진을 범위=공용 상태에서 보여줄 때 썸네일/이동/삭제가 잘못된 네임스페이스를 쓰던 문제(PhotoCell·Lightbox·DragOverlay·useFileOps 추론). 모바일: 분할은 상하 스택(lg 미만). mock e2e 검증: 분할 토글→양쪽 탐색→선택→이동→삭제→undo 전부 통과
  - [x] **상단 메뉴 IA 재편** (2026-07-02) — 성격이 다른 두 축(범위/보기)이 동일 알약 그룹으로 나란해 5개 평면 메뉴처럼 보이던 문제 해결. **보기**(📅타임라인/📁폴더/🔁중복정리)를 아이콘 주 메뉴로, **범위**(공용/개인)는 `범위` 라벨+세그먼트로 구분선 뒤 분리. `공용 폴더/내 개인 폴더`→`공용/개인`으로 개명해 '폴더' 단어 3중 충돌 제거. 폴더 보기는 공용·개인 트리를 동시에 노출하므로 범위 칩을 숨김(문맥 일치)
- [ ] 3단계(AI 자동 분류) — 미착수
