# Photo Gallery ↔ Photo Desk 세션 분리 실행 가이드

> 상태: G2 완료, Gallery `drain` 복구 유예 중
> 기준일: 2026-09-02
> 상세 기능 명세: [Photo Gallery → Photo Desk 기능 이관 및 전환 기준](https://github.com/HyunjoonKwak/photo_desk/blob/main/docs/GALLERY_TRANSITION.md)

이 문서는 기능 이관을 **현재 Photo Gallery 세션**과 **별도 Photo Desk 세션**으로
나누기 위한 실행용 가이드다. 기능 범위와 합격 조건은 상세 명세가 정본이며, 이 문서는
누가 어느 저장소를 만지고 언제 다음 단계로 넘어가는지를 정한다.

## 1. 한눈에 보는 순서

```text
현재 Gallery 세션
  G-A. 전환 장치 구현·테스트 (운영값은 legacy 유지)
  G-B. 테스트 표본·기준선·Desk 인계 자료 준비
          │
          ▼ G0 인계
별도 Desk 세션
  D-A. 촬영일 감사·교정
  D-B. 임의 이동·복사와 공용 발행
  D-C. 일반 폴더 작업
  D-D. 자동 테스트·앱 빌드·파일럿 패키지 제출
          │
          ▼ G1 인계
현재 Gallery 세션 재개
  G-C. 종단간 파일럿
  G-D. Gallery legacy 배포 → drain 전환
  G-E. 최소 7일 복구 유예 → curation + 원본 ro
  G-F. 30일 안정화 뒤 레거시 제거
```

`PD-P1`인 폴더 이름 감사와 이벤트 자동 발견은 유용하지만 읽기 전용 전환을 막는
기능은 아니다. `PD-P0-01~03`을 먼저 끝내고 안정화 뒤 별도 작업으로 진행한다.

## 2. 저장소 소유권

| 구분 | 수정할 저장소 | 수정하지 않을 저장소 |
|---|---|---|
| 현재 Gallery 세션 | `photo_gallery` | `photo_desk` 애플리케이션 코드, `photo_backup` 코드 |
| 별도 Desk 세션 | `photo_desk` | `photo_gallery` 코드와 운영 설정, `photo_backup` 코드 |
| 전환 파일럿 | 양쪽 결과를 읽고 실행하되 수정은 담당 저장소에서 각각 수행 | 상대 저장소 코드를 임시로 고쳐 통과시키지 않음 |

공통 계약은 NAS 경로·Drive 동기화·파일 결과뿐이다. 두 앱이 서로의 런타임 API를
호출하는 새 결합은 만들지 않는다. 동시에 작업할 때 상대 저장소의 미커밋 변경을
정리·포맷·되돌리거나 한 커밋에 섞지 않는다.

## 3. 현재 Photo Gallery 세션에서 진행할 단계

### G-A. 안전한 전환 장치 구현

이 단계는 Desk P0 구현과 병행할 수 있다. 단, 기본값과 운영값은 계속 `legacy`다.

- `GALLERY_WRITE_MODE=legacy|drain|curation` 런타임 설정 추가
- `GALLERY_LEGACY_DATE_REPAIR=false` 관리자 전용 스위치 추가
- 물리 파일 변이 라우트에 공통 서버 guard 적용
- `/api/system/info`에 아래 capability 노출
  - `physical_mutations`
  - `undo_drain`
  - `synology_curation`
  - `legacy_date_repair`
- 프론트의 정리 액션을 compile-time 플래그가 아니라 capability로 구성
- `drain`에서는 신규 변이와 영구 비우기를 막고 기존 undo·복원만 허용
- `curation`에서는 원본/폴더 변이와 복구를 모두 막되 앨범·인물 큐레이션은 유지
- 모드별 mutation 라우트의 `200/403` 표 기반 테스트 추가

완료 증거:

- 기본값 `legacy`에서 기존 기능 회귀 없음
- `drain`에서 신규 물리 mutation이 모두 403
- `drain`에서 기존 undo·개별 복원 성공, 영구 비우기는 403
- `curation`에서 감상·검색·다운로드·앨범·인물 작업 정상
- 설정 누락 시 안전하게 `legacy`로 동작하는 첫 배포 호환성 확인

### G-B. Desk 세션에 넘길 표본과 기준선 준비

원본 사진을 테스트 재료로 직접 사용하지 않는다. 임시 폴더에 **복사본**을 만들고
테스트가 끝나면 별도 삭제한다.

- 정상 EXIF JPEG
- EXIF 없는 `YYYYMMDD_HHMMSS` 파일
- Kakao 13자리 millisecond epoch+순번 파일
- 자정 전후와 EXIF/파일명이 9시간 어긋나는 파일
- PNG/HEIC/RAW/영상 각 1개 이상
- 같은 이름 충돌, sidecar, 중첩 폴더, 빈 폴더 표본
- 작업대→내사진, 작업대→공용, 내사진→공용 흐름용 폴더

각 표본의 before manifest를 남긴다.

```text
relative_path | size | sha256 | mtime | embedded capture time | expected action
```

Gallery 세션의 G0 인계물:

1. Gallery 전환 장치 커밋 SHA와 변경 파일 목록
2. Gallery 백엔드·프론트 테스트 명령과 결과
3. 라우트별 모드 기대값 표
4. 테스트 표본 위치와 before manifest
5. 세 앱의 실제 공용·개인·1차 구역 경로 확인 결과

### 이 단계에서 하지 않는 것

- 운영 `GALLERY_WRITE_MODE`를 `drain` 또는 `curation`으로 변경
- `THUMB_HOMES_HOST` 마운트를 `ro`로 변경
- Manage 탭과 레거시 코드를 제거
- 휴지통을 비우거나 기존 operation을 일괄 정리
- Desk P0 완료를 문서나 UI 모양만 보고 인정

## 4. 별도 Photo Desk 세션에서 진행할 단계

Desk 세션은 먼저 현재 worktree의 기존 미커밋 변경을 확인하고 보존한다. 이 작업 전용
커밋에는 아래 기능과 관련 테스트만 포함한다.

### D-A. `PD-P0-01` 촬영일 감사·교정

- 기존 `taken_at` 판독 체인을 재사용한 재귀/선택 감사와 dry-run UI
- 자동·수동·일괄 교정
- JPEG EXIF 세 필드와 mtime 기록
- 다른 포맷은 실제 기록 가능한 범위를 UI에 명시
- 원본 또는 metadata segment 백업, journal, 배치 undo
- 13자리 epoch+0~6자리 순번의 엄격한 날짜 범위 검증
- 쓰기 후 재스캔과 DB 정렬 갱신

필수 합격 조건:

- dry-run에서 파일·DB hash가 변하지 않음
- write→재스캔 결과가 미리보기와 일치
- undo 후 원본 SHA-256과 원래 메타시각 복원
- 정상 EXIF는 자동 기본 선택에서 제외
- 부분 실패, 자정, 시간대 경계 테스트 통과

### D-B. `PD-P0-02` 임의 이동·복사와 공용 발행

- 선택 사진의 기존/새 목적지 폴더 선택
- `move`와 `copy` 분리
- 작업대→내사진/공용은 이동 기본
- 내사진→공용은 **복사 기본**이며 원본 유지
- sidecar, cross-volume, 부분 실패, undo 지원
- source/destination hash 기반 공용 발행 원장과 재실행 중복 방지
- 실행 전 충돌 미리보기와 `건너뜀/이름변경` 정책

### D-C. `PD-P0-03` 일반 폴더 작업

- 생성·이름변경·같은/다른 라이브러리 이동·복사·휴지통
- 라이브러리 루트, 부모→자식 순환, 오프라인 볼륨 차단
- 같은 이름 충돌을 실행 전에 표시
- batch journal과 undo
- 중첩/빈/대용량 폴더와 cross-volume 부분 실패 테스트

Gallery의 DSM 전용 코드나 듀얼 패널 UI를 그대로 복사하지 않는다. Desk의 경로 안전판,
DB 동기화, journal, AlbumTree와 목적지 선택 흐름 위에 기능을 구현한다.

### D-D. Gallery 세션으로 넘길 완료 패키지

Desk 세션은 “구현 완료”라는 설명 대신 다음 증거를 제출한다.

1. 기능별 커밋 SHA와 변경 파일 목록
2. Rust·프론트 테스트와 production build 결과
3. 포맷별 촬영일 write/undo 지원표
4. 표본별 before→write→rescan→undo manifest 비교
5. 이동/복사/폴더 작업의 성공·부분 실패·undo 결과
6. 내사진→공용 재실행 시 중복이 생기지 않는 결과
7. DB migration 또는 설정 변경과 롤백 방법
8. 남은 제한·실패 항목·운영에서 확인할 항목

이 패키지가 모두 있어야 G1을 통과한다. Desk 세션은 Gallery 설정을 바꾸거나 배포하지
않고 여기서 멈춘다.

## 5. Desk 완료 뒤 현재 Gallery 세션에서 재개할 단계

### G-C. G1 검수와 종단간 파일럿

Desk의 실제 JPEG 및 서로 다른 물리 볼륨 파일럿 뒤, 같은 SHA의 사본으로
Drive→NAS→Gallery 경로까지 확인했다. 첫 Gallery 확인에서 Synology의 floating
wall-clock을 실제 epoch로 해석해 KST를 두 번 더하는 9시간 오차가 발견됐고,
`093934f`에서 읽기·일자 범위·버킷·레거시 시간 쓰기를 같은 규칙으로 교정했다.
재검증 결과 경로·장수·SHA·촬영일이 모두 일치해 G2를 통과했다.

- Desk 커밋과 테스트를 확인하고, 제공된 표본으로 핵심 테스트 재실행
- 복사본 파일럿에서 Desk의 write와 undo를 먼저 확인
- 제한된 실제 테스트 폴더로 아래 흐름을 1회 검증

```text
Photo Backup/1차 구역 → Desk 수집 → 촬영일 교정 → 내사진/공용 정리
→ Drive 동기화 → NAS 색인 → Gallery 날짜·경로·장수 확인
```

- before/after manifest로 경로·장수·hash·mtime 비교
- 내사진→공용은 원본과 사본이 모두 존재하는지 확인
- Synology의 기존 item date 재색인 한계를 신규 유입과 레거시 백로그로 분리

하나라도 불일치하면 `legacy`를 유지하고 Desk 단계로 되돌린다.

### G-D. Gallery 배포와 `drain`

1. 전환 장치 코드를 `legacy` 설정으로 먼저 배포
2. 감상·앨범·인물·기존 정리 기능 회귀 확인
3. `data/app.db`, operation 목록, 휴지통 통계, 현재 이미지 태그 백업
4. 운영값만 `drain`으로 변경해 재배포
5. 신규 mutation 403, 기존 undo/복원, 앨범/인물 큐레이션을 실환경 확인

문제가 생기면 마운트는 `rw` 상태로 둔 채 즉시 `legacy`로 되돌린다.

### G-E. 복구 유예 뒤 `curation`과 읽기 전용

- `drain`을 최소 7일 유지
- 기한 없는 move/copy/mkdir operation도 전부 검토
- 휴지통 복구 대상과 의도하지 않은 미완료 작업이 0인지 확인
- `curation`으로 전환
- `THUMB_HOMES_HOST`를 `ro`로 변경
- 컨테이너 내부 직접 쓰기 실패와 썸네일/EXIF 읽기 성공 확인
- Manage의 물리 작업 UI를 제거하고 논리 앨범·인물 기능만 유지

### G-F. 안정화 뒤 정리

30일 동안 회귀가 없고 레거시 Synology 날짜 교정 백로그가 0일 때만 Gallery의
`dedup`, `organize`, zones와 물리 operation UI/API를 제거한다. 그 전에는 롤백을 위해
코드를 남긴다.

## 6. 인계 판단표

| 상태 | Gallery 세션 | Desk 세션 | 전환 가능 여부 |
|---|---|---|---|
| 현재 | 전환 장치 구현 가능, 운영은 `legacy` | P0 구현 필요 | 불가 |
| Gallery G0 완료 | 표본·guard·테스트 전달 | P0 구현/검증 | 불가 |
| Desk G1 완료 | 증거 검수·파일럿 | Gallery에 결과 전달 후 대기 | 파일럿만 가능 |
| G2 파일럿 완료 | `legacy` 배포 후 `drain` | 결함 대응 | `drain` 가능 |
| 7일 복구 유예 완료 | `curation`+`ro` | 정상 흐름 관찰 | 읽기 전용 가능 |
| 30일 안정화 완료 | 레거시 제거 | P1 작업 가능 | 최종 전환 완료 |

## 7. 별도 Photo Desk 세션에 전달할 시작 프롬프트

아래 내용을 Photo Desk 프로젝트의 새 작업에 그대로 전달한다.

```text
photo_desk 저장소에서 Gallery→Desk 전환 P0 기능을 구현해줘.

먼저 다음 문서를 정본으로 읽어:
- docs/GALLERY_TRANSITION.md
- ../photo_gallery/docs/GALLERY_DESK_SESSION_GUIDE.md

소유 범위는 photo_desk의 애플리케이션 코드와 테스트뿐이야. photo_gallery 코드,
운영 설정, 배포 상태는 변경하지 마. 현재 worktree의 기존 미커밋 변경은 보존하고
이 작업과 섞이거나 되돌려지지 않게 해.

구현 순서는 PD-P0-01 촬영일 감사·교정, PD-P0-02 임의 이동·복사와 내사진→공용
복사, PD-P0-03 일반 폴더 작업이야. Gallery 구현을 그대로 복사하지 말고 Desk의
taken_at, 경로 안전판, DB 동기화, batch journal/undo 위에 구현해. 각 패키지의 완료
조건과 포맷·시간대·부분 실패 테스트를 모두 충족해.

마지막에는 커밋 SHA, 변경 파일, 테스트/build 결과, 포맷 지원표,
before→write→rescan→undo manifest, 이동/복사/undo 결과, migration과 롤백 방법,
남은 제한을 Gallery 세션에 인계해. Gallery를 전환하거나 배포하지 말고 결과 제출에서
멈춰.
```

## 8. 현재 Gallery 세션의 다음 작업

`G-A`와 Desk G1/G2가 완료됐고 Gallery 운영 모드는 2026-09-02부터 `drain`이다.
원본 마운트는 복구를 위해 `rw`로 유지하고 신규 물리 변이는 서버에서 차단한다.
현재 undo 가능 작업과 휴지통 항목을 검토하며 최소 7일 유예한 뒤, 복구 대상이 0일
때만 `curation`과 `ro`로 넘어간다. 레거시 코드는 30일 안정화 전까지 제거하지 않는다.
