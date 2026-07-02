# 배포 가이드 (GHCR → NAS)

`my_portal`과 동일한 흐름입니다: **로컬에서 빌드·GHCR 푸시 → NAS에서 pull·배포**.
`nas_photo`는 단일 이미지(멀티스테이지: 프론트 빌드 → FastAPI가 정적 서빙)입니다.

이미지: `ghcr.io/hyunjoonkwak/nas-photo:latest`

## 1. 로컬 — 빌드 & GHCR 푸시

```bash
# 최초 1회: GHCR 로그인 (GitHub PAT, write:packages 권한)
./manage.sh ghcr:login

# 이미지 빌드 + 푸시 (기본 linux/amd64 — Synology Intel/AMD NAS 대상)
./manage.sh ghcr:push            # tag=latest
./manage.sh ghcr:push v1         # 특정 태그
```

> GitHub PAT: github.com → Settings → Developer settings → Personal access tokens
> → `write:packages`(푸시) 권한. NAS pull 전용은 `read:packages`면 충분.
> 패키지를 public으로 두면 NAS에서 로그인 없이 pull 가능.

## 2. NAS — 배포

NAS에 이 리포를 클론(또는 `deploy.sh` + `docker-compose.prod.yml` + `.env`만 복사)한 뒤:

```bash
cp .env.prod.example .env        # DSM 주소 등 채우기
./deploy.sh login                # 최초 1회 (패키지가 private일 때만)
IMAGE_TAG=latest ./deploy.sh update   # pull + 배포
```

이후 업데이트는 로컬에서 `ghcr:push` → NAS에서 `deploy.sh update` 반복.

명령:
- `deploy.sh update` — pull + 재배포 (일반적인 업데이트)
- `deploy.sh status` / `logs` / `restart` / `stop`

접속: `http://<NAS_IP>:9800`

## 3. 운영 권장

- **HTTPS**: DSM 제어판 → 로그인 포털 → 리버스 프록시로 `nas-photo:9800`을
  HTTPS 도메인 뒤에 두고, `.env`에 `COOKIE_SECURE=true`.
- **타임존**: 이미지에 `TZ=Asia/Seoul` 내장(타임라인 날짜 그룹핑 기준). 다른
  지역이면 compose의 `TZ`를 바꾸세요.
- **DSM Auto Block**: 제어판 → 보안 → 자동 차단 허용 목록에 도커 게이트웨이
  IP 추가(앱이 로그인 프록시이므로).
- **데이터**: SQLite는 배포 디렉터리의 `./data`에 보존(세션/작업로그/사진 해시).
- `MOCK_MODE`는 운영에서 반드시 `false`.

## 4. 트러블슈팅

- pull 403/denied → 패키지가 private이면 `deploy.sh login`(read:packages PAT).
- 아키텍처 오류(exec format) → `manage.sh ghcr:push`가 amd64로 빌드했는지 확인
  (`BUILD_PLATFORMS` 기본 `linux/amd64`).
- 타임라인 날짜가 하루 밀림 → 컨테이너 TZ 확인(`docker exec nas-photo date`).
