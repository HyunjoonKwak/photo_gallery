# 정리 워크플로우(마법사) 설계 — "정리하기"

> 2026-07-04 설계 확정 전 초안. 목적: 4개 기기에서 개인 공간(`/homes/<user>/Photos`)에
> 모인 사진을 **중복 제거 → 잡동사니 분리 → 이벤트 단위 공용 앨범화**의 반복 가능한
> 흐름으로 정리한다. 새 백업이 유입될 때마다 재실행하는 것을 전제로 한다.

## 0. 설계 원칙

| 원칙 | 내용 |
|------|------|
| 공간 역할 분리 | 개인 = 원본 아카이브(`YYYY-MM` 시간축, 전부 보관) / 공용 = 엄선본 이벤트 앨범 |
| 개인 구조 불가침 | 마법사는 개인 공간의 `YYYY-MM` 구조를 **재배치하지 않는다**. 이벤트 묶기는 "공용으로 복사할 후보 선별" 도구다 (개인에 이벤트 폴더를 만들면 아카이브가 깨짐) |
| 공용 반영은 복사 | 명세 4장 — 개인 원본 보존이 기본값 |
| 파괴적 작업 가역 | 기존 원칙 그대로: 앱 휴지통 + 작업로그 + Undo |
| 기존 자산 재사용 | 중복 정리 뷰·이동/복사+Undo·폴더 생성·전역 선택 모델·job 워커 패턴을 그대로 씀 |

## 1. 사용자 흐름 (마법사 3단계 + 요약)

```
[정리하기 진입 (개인 공간 고정)]
  Step 1 중복 정리     ← 기존 DedupView 재사용 (space=personal)
  Step 2 잡동사니 분리  ← 신규: 스크린샷/EXIF없음 후보 자동 추출 → 일괄 이동/삭제
  Step 3 이벤트 → 공용 앨범 ← 신규: 시간 갭 클러스터 제안 → 검토 → 공용에 폴더 생성+복사
  요약   처리 통계 + 다음에 이어하기 안내
```

- 각 단계는 [건너뛰기] 가능. 단계 상태는 SQLite에 저장해 **이어하기** 지원.
- 진입점: 헤더(및 라이브러리 셀렉터가 개인일 때 배너). 모바일 하단 탭은 4탭 유지 —
  마법사는 헤더 진입(데스크톱 우선, 모바일도 동작은 하되 탭 추가 안 함).

---

## Phase 0 — 실 NAS 선행 검증 (개발 전 전제) `[S]`

마법사의 실행 액션이 전부 여기 걸려 있으므로 가장 먼저 확인한다.

- [ ] **0-1 cross-space 복사/이동**: 개인 사진 1~2장 → 공용 폴더 복사·이동·undo
      (기존 `/ops/move`가 이미 지원하는 경로 — 실 NAS에서 FotoTeam 재인덱싱 지연 여부 확인)
- [ ] **0-2 폴더째 이동/복사**(47e1ac9): 공용 내 실검증 + 개인→공용 cross-space 폴더 복사
- [ ] **0-3 개인 공간 dedup 스캔**: `space=personal` 스캔이 실 NAS에서 photo_cache를
      채우는지 (Phase 1·2의 데이터 기반이 photo_cache)
- 완료 기준: 세 항목 모두 성공 + IMPROVEMENTS.md에 결과 기록. 실패 시 해당 Phase 설계 조정.

## Phase 1 — 잡동사니 분리 (Step 2 엔진) `[M]`

**데이터 기반**: dedup 스캔이 채우는 `photo_cache`(filename·taken_at·camera·width/height·size)를
재사용한다. 스캔 전이면 화면에서 "먼저 스캔"을 안내 (Step 1에서 자연히 채워짐).

### 백엔드
- `GET /api/photos/junk-candidates?space=personal` → `{groups: [{reason, items[]}]}`
- 판별 룰 (`backend/app/organize/junk.py`, 순수 함수로 단위테스트):
  - `screenshot`: 파일명 `Screenshot*|스크린샷*|SCR_*` 또는 PNG+EXIF 카메라 없음+기기 화면 해상도
  - `messenger`: 파일명 `KakaoTalk_*|IMG_KAKAO*|FB_IMG*|Telegram*`
  - `no_exif`: camera IS NULL AND taken_at이 파일시간 추정 (다운로드/저장 이미지)
  - 룰은 상수 테이블로 시작, 추후 설정화. **각 후보에 사유 태그 필수**(사용자 신뢰)
- 실행은 기존 `/ops/move`(잡동사니 폴더로) 또는 `/ops/delete`(휴지통) 재사용 — 신규 실행 API 없음

### 프론트
- `frontend/src/components/organize/JunkStep.tsx`
- 사유별 섹션(스크린샷 n장 / 메신저 n장 / EXIF 없음 n장) + 썸네일 그리드(전역 선택 모델 재사용,
  섹션별 모두 선택)
- 액션: **[`_정리/스크린샷` 등 폴더로 이동]**(기본, 자동 생성) / [휴지통] — 둘 다 Undo 토스트
- 기본값은 이동(보관) — 삭제는 사용자가 명시적으로 선택

### 테스트/완료 기준
- 룰 단위테스트(파일명·EXIF 조합 매트릭스), API pytest(mock에 잡동사니 시드 추가), mock UI e2e
- 완료: 개인 공간에서 후보 추출→일괄 이동→undo가 mock+실 NAS에서 동작

## Phase 2 — 이벤트 제안 → 공용 앨범 (Step 3 엔진) `[M~L]`

### 백엔드
- `GET /api/photos/event-suggestions?space=personal&gap_hours=4&min_photos=8`
- `backend/app/organize/events.py`: photo_cache를 taken_at 정렬 → **시간 갭 클러스터링**
  (연속 사진 간격 > gap_hours면 분리) → `{start, end, count, item_ids, name_hint}`
- `name_hint`: `"YYYY-MM-DD~DD"` (단일일은 `"YYYY-MM-DD"`) + 장소 라벨(가능하면):
  분류 뷰의 지오코딩 데이터에서 클러스터 대표 아이템의 장소 조회 — **실 NAS에서
  아이템→장소 역매핑이 가능한지 프로브 후 결정**, 안 되면 v1은 날짜만
- 옵션: 이미 공용에 복사한 클러스터 제외(작업로그 대조) — v2
- 실행: 기존 API 조합 — 공용에 `create_folder` + cross-space `move(copy_mode=true)`.
  묶음 undo를 위해 두 작업의 operation_id를 응답에 함께 반환

### 프론트
- `frontend/src/components/organize/EventStep.tsx`
- 클러스터 카드: 대표 썸네일 4장 + 기간 + n장 + 이름 인라인 편집(기본 name_hint)
- 카드 펼치면 그리드 — 베스트컷만 남기게 개별 체크 해제 가능(전역 선택 모델)
- 액션: **[공용에 앨범 만들기]**(mkdir+복사, 토스트 2건 or 요약 1건) / [건너뛰기]
- gap_hours·min_photos는 상단 슬라이더(중복 정리 유사도 슬라이더와 같은 패턴)

### 테스트/완료 기준
- 클러스터링 단위테스트(갭 경계·자정 넘김·단일 사진·taken_at 결측), API pytest, mock e2e
- 완료: 제안→이름 수정→공용 앨범 생성+복사→양쪽 공간 확인이 실 NAS에서 동작

## Phase 3 — 마법사 셸 + 세션 `[M]`

- `ViewMode`에 `"organize"` 추가, `OrganizeView.tsx` = 스테퍼 셸
  (Step 1은 DedupView를 personal 고정으로 임베드, Step 2/3는 Phase 1·2 화면)
- 스테퍼: 완료 체크 표시·건너뛰기·이전/다음, 각 단계 하단에 "이 단계에서 한 일 n건" 카운터
- 세션: `workflow_session` 테이블 `(id, user, space, step, stats_json, updated_at)` —
  진입 시 미완료 세션 있으면 "이어하기" 배너. `db.py` additive migration
- 요약 화면: 중복 제거 n / 잡동사니 이동 n / 공용 앨범 m개·n장 (stats_json 집계)
- 테스트: 세션 저장/이어하기 pytest, 전체 흐름 mock e2e

---

## 진행 순서와 의존성

```
Phase 0 (실 NAS 검증, 사용자 참여 필요)
  ├→ Phase 1 (잡동사니)     ← Phase 0-3 (photo_cache)
  └→ Phase 2 (이벤트→공용)  ← Phase 0-1·0-2 (cross-space)   ※ 1·2는 상호 독립, 병행 가능
       └→ Phase 3 (셸+세션) ← 1·2 완료 후
```

- 커밋 단위: Phase당 1~2 커밋 (엔진+테스트 / 화면+e2e)
- Phase 1·2는 mock으로 개발 가능. Phase 0만 실 NAS 접속이 필요(사용자와 함께)

## 미결 사항 (구현 중 확인)

- [ ] 잡동사니 기본 처분 폴더명: `_정리/` 프리픽스 vs `기타/` — 사용자 취향 확인
- [ ] 지오코딩 아이템→장소 역매핑 가능 여부 (실 NAS 프로브) → name_hint 장소 포함 여부
- [ ] 이벤트 최소 장수 기본값(8장 가정) — 실데이터로 튜닝
- [ ] 마법사 진입점 문구/아이콘 (`✨ 정리하기` 가안)
