# 배포 가이드 (GHCR → NAS)

`my_portal`과 동일한 흐름입니다: **로컬에서 빌드·GHCR 푸시 → NAS에서 pull·배포**.
`nas_photo`는 단일 이미지(멀티스테이지: 프론트 빌드 → FastAPI가 정적 서빙)입니다.

이미지: `ghcr.io/<GHCR_USERNAME>/nas-photo:latest`

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

- **HTTPS (Nginx Proxy Manager 사용 — 확정)**: NPM에 Proxy Host 등록:
  - Domain: 사용할 도메인 / Scheme: `http` / Forward IP: NAS IP / Port: `9800`
  - SSL 탭에서 인증서 발급(Let's Encrypt) + `Force SSL` 권장
  - NPM 기본 `X-Real-IP` 덮어쓰기를 유지하세요. 앱은 운영에서 이 값을 IP별
    로그인 제한에 사용합니다(`LOGIN_TRUST_PROXY_HEADERS=true`). 임의 클라이언트
    헤더를 그대로 통과시키는 커스텀 설정은 넣지 마세요.
  - Websockets 불필요(사용 안 함), `Block Common Exploits` 켜도 무방
  - **Custom Nginx Configuration에 타임아웃 연장 필수** — 대량 이동/삭제/
    되돌리기 요청은 수 분까지 걸리는데 NPM 기본(60s)이 중간에 끊어버림.
    편집 창의 Advanced 탭(구버전) 또는 **우측 톱니바퀴(⚙) 아이콘**(v2.13+)
    에서 입력:
    ```nginx
    proxy_read_timeout 600s;
    proxy_send_timeout 600s;
    ```
  - 프로덕션 compose 기본은 `COOKIE_SECURE=true`입니다. 기존 NAS `.env`에
    `COOKIE_SECURE=false`가 남아 있으면 HTTPS 확인 후 `true`로 바꾸고
    `./deploy.sh restart` 하세요.
  - 이후 접속은 HTTPS 도메인으로만; `http://IP:9800` 직접 접속은 쿠키가
    Secure라 로그인 불가(정상)
- **타임존**: 이미지에 `TZ=Asia/Seoul` 내장(타임라인 날짜 그룹핑 기준). 다른
  지역이면 compose의 `TZ`를 바꾸세요.
- **DSM Auto Block**: 제어판 → 보안 → 자동 차단 허용 목록에 도커 게이트웨이
  IP 추가(앱이 로그인 프록시이므로).
- **Cloudflare**: 가족사진 호스트만 정확한 `photo` A 레코드를 DNS-only(회색
  구름)로 두고, `*.specialrisk.me` 등 다른 호스트 설정은 유지합니다. 썸네일은
  인증 응답이라 Cloudflare `Cache Everything`/공용 캐시 규칙을 적용하지 않습니다.
  외부 공개 포트는 NPM의 443만 두고 앱 포트 9800은 공유기에서 포워딩하지 마세요.
- **데이터**: SQLite는 배포 디렉터리의 `./data`에 보존(세션/작업로그/사진 해시).
- `MOCK_MODE`는 운영에서 반드시 `false`.

## 4. 트러블슈팅

- 컨테이너가 `Restarting`(exit 3) → `./data` 볼륨 쓰기 권한. 컨테이너는
  비root(uid 10001)라 `chown -R 10001:10001 data`가 필요(`deploy.sh`가 자동
  수행하지만, 수동은 `chown -R 10001:10001 data && ./deploy.sh restart`).
- pull 403/denied → 패키지가 private이면 `deploy.sh login`(read:packages PAT).
- 아키텍처 오류(exec format) → `manage.sh ghcr:push`가 amd64로 빌드했는지 확인
  (`BUILD_PLATFORMS` 기본 `linux/amd64`).
- 타임라인 날짜가 하루 밀림 → 컨테이너 TZ 확인(`docker exec nas-photo date`).
