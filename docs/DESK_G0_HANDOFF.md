# Photo Desk G0 인계서

> 상태: **Desk P0 인계 완료**
> 작성일: 2026-09-02
> Gallery 기준 HEAD: `30af37e` + G-A 전환 안전장치
> 실행 가이드: [Gallery↔Desk 세션 분리 실행 가이드](GALLERY_DESK_SESSION_GUIDE.md)

## 1. Gallery에서 준비한 것

- `GALLERY_WRITE_MODE=legacy|drain|curation`
- `GALLERY_LEGACY_DATE_REPAIR` 관리자 전용 임시 스위치
- `/api/system/info`의 effective capability 응답
- 새 파일·폴더/정리 작업의 중앙 서버 guard
- `drain`의 기존 undo·개별 휴지통 복원 허용
- `curation`의 원본/폴더 및 복구 차단
- 모든 모드에서 Synology 일반 앨범과 인물 이름·병합 유지
- capability 기반 프론트 액션·DnD·폴더 도구·복구 버튼 제어
- 첫 운영 배포를 `legacy`로 고정하는 compose/env 예시

현재 운영 설정, 마운트와 배포 상태는 바꾸지 않았다. `drain`, `curation`, homes
`ro`, Manage 제거는 Desk P0와 종단간 파일럿 뒤 Gallery 세션에서만 진행한다.

## 2. 서버 정책 표

| 작업 | `legacy` | `drain` | `curation` |
|---|---:|---:|---:|
| 신규 파일·폴더 이동/복사/삭제/생성/이름변경 | 허용 | 403 | 403 |
| 중복 스캔·정리 마법사 상태 변이 | 허용 | 403 | 403 |
| 기기 백업 구역 등록·삭제 | 허용 | 403 | 403 |
| 기존 operation undo·휴지통 개별 복원 | 허용 | 허용 | 403 |
| 휴지통 영구 비우기 | 관리자 허용 | 403 | 403 |
| 파일 EXIF/mtime 교정 | 허용 | 403 | 403 |
| Synology item time 레거시 교정 | 관리자+별도 스위치 | 관리자+별도 스위치 | 403 |
| Synology 앨범·인물 큐레이션 | 허용 | 허용 | 허용 |
| 감상·검색·다운로드 | 허용 | 허용 | 허용 |

## 3. 검증 결과

```text
python -m pytest -q
221 passed

npm run build
TypeScript + Vite production build 성공

python -m pytest -q tests/test_write_policy.py
17 passed
```

저장소의 `backend/.venv` 실행기는 이전 절대경로를 가리켜 사용할 수 없었다. 위 결과는
현재 pyenv Python 3.12의 동일 프로젝트 의존성으로 실행했다. 테스트 실패는 없고 기존
Pillow/FastAPI deprecation warning만 남아 있다.

## 4. Desk P0 표본 계약

실제 가족 원본을 자동 테스트에 사용하지 않는다. Desk 테스트가 임시 디렉터리에 다음
표본을 생성하거나, 검토된 파일 **복사본**을 사용한다.

| ID | 표본 | 기대 동작 |
|---|---|---|
| DATE-01 | 정상 `DateTimeOriginal` JPEG | 자동 교정 기본 선택에서 제외 |
| DATE-02 | EXIF 없음, `YYYYMMDD_HHMMSS.jpg` | 파일명 근거 시각 제안 |
| DATE-03 | `1502088228879113.jpg` 형태 | 첫 13자리 ms epoch만 채택, 순번 무시 |
| DATE-04 | 임의 10자리 숫자 파일명 | epoch seconds로 자동 채택하지 않음 |
| DATE-05 | 자정 전후·UTC와 Asia/Seoul 9시간 차이 | 미리보기에 해석과 wall-clock 명시 |
| DATE-06 | 기존 EXIF와 파일명 불일치 | 자동 덮어쓰기 금지, 수동 확인 필요 |
| DATE-07 | PNG/HEIC/RAW/영상 | 실제 기록 범위와 mtime-only 여부 표시 |
| DATE-08 | 배치 중 쓰기 실패 1건 | 성공분 journal 유지, 실패분 명확히 분리 |
| MOVE-01 | 같은 이름 파일과 sidecar | 실행 전 충돌·sidecar 처리와 undo |
| MOVE-02 | 내사진→공용 2회 실행 | 개인 원본 유지, 공용 중복 사본 없음 |
| FOLDER-01 | 중첩·빈 폴더·부모→자식 대상 | 정상 작업과 순환 차단 |
| FOLDER-02 | cross-volume 중간 실패 | 성공분 기록·정확한 부분 undo |

각 케이스는 아래 before/after 필드를 남긴다.

```text
case_id | relative_path | size | sha256 | mtime | embedded_capture_time
        | proposed_time/source | write_result | rescan_time/source | undo_result
```

Gallery의 참고 구현과 회귀 사례:

- `backend/app/photos/capture_date.py`
- `backend/app/photos/capture_fix.py`
- `backend/tests/test_capture_date.py`
- `frontend/src/components/CaptureDateDialog.tsx`
- `backend/app/operations.py`

코드를 그대로 복사하지 않고 Desk의 `taken_at`, 경로 안전판, DB 동기화와 batch
journal/undo를 기준으로 구현한다.

## 5. Desk가 제출할 G1 증거

1. `PD-P0-01~03` 기능별 커밋 SHA와 변경 파일
2. Rust·프론트 테스트와 production build 결과
3. 위 표본의 before→write→rescan→undo manifest
4. 포맷별 embedded metadata/mtime 지원표
5. 같은/cross-volume 이동·복사와 부분 실패·undo 결과
6. 내사진→공용 재실행 중복 방지 결과
7. DB migration·설정 변경·롤백 방법
8. 남은 제한과 실환경 확인 항목

Desk 세션은 Gallery 코드를 수정하거나 Gallery를 배포하지 않는다. G1 결과 제출에서
멈추고, 종단간 파일럿과 `drain` 전환은 Gallery 세션으로 돌려보낸다.

## 6. 아직 하지 않은 것

- G-A 변경 커밋·푸시·배포
- 운영 mode 변경
- `data/app.db`·operation 운영 백업
- 실제 NAS/Drive 종단간 파일럿
- homes 마운트 `ro`
- Gallery 레거시 제거

이 항목들은 Desk P0 구현을 시작하는 데는 방해되지 않지만, G2 이후 전환에는 반드시
필요하다.
