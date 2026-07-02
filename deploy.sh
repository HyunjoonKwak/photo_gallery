#!/bin/bash

# NAS 사진 정리 앱 — NAS 배포 스크립트 (GHCR 이미지 기반)
# 이 스크립트는 NAS에서 실행된다. 로컬에서 `manage.sh ghcr:push`로 올린
# 이미지를 pull 해서 docker-compose.prod.yml 로 배포한다.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

GHCR_USERNAME="${GHCR_USERNAME:-hyunjoonkwak}"
GHCR_USERNAME=$(echo "$GHCR_USERNAME" | tr '[:upper:]' '[:lower:]')
IMAGE_TAG="${IMAGE_TAG:-latest}"
IMAGE="ghcr.io/${GHCR_USERNAME}/nas-photo:${IMAGE_TAG}"
COMPOSE_FILE="docker-compose.prod.yml"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; BLUE='\033[0;34m'; NC='\033[0m'
print_header()  { echo -e "${BLUE}================================${NC}\n${BLUE}$1${NC}\n${BLUE}================================${NC}"; }
print_success() { echo -e "${GREEN}✅ $1${NC}"; }
print_warning() { echo -e "${YELLOW}⚠️  $1${NC}"; }
print_error()   { echo -e "${RED}❌ $1${NC}"; }

# docker compose(v2) 우선, 없으면 docker-compose(v1)
compose() {
    if docker compose version &>/dev/null; then
        GHCR_USERNAME="$GHCR_USERNAME" IMAGE_TAG="$IMAGE_TAG" docker compose -f "$COMPOSE_FILE" "$@"
    else
        GHCR_USERNAME="$GHCR_USERNAME" IMAGE_TAG="$IMAGE_TAG" docker-compose -f "$COMPOSE_FILE" "$@"
    fi
}

ghcr_login() {
    print_header "🔐 GHCR 로그인"
    read -p "GitHub 사용자명 [$GHCR_USERNAME]: " input_username
    GHCR_USERNAME="${input_username:-$GHCR_USERNAME}"
    read -rsp "GitHub PAT (read:packages): " token; echo
    echo "$token" | docker login ghcr.io -u "$GHCR_USERNAME" --password-stdin \
        && print_success "GHCR 로그인 성공" \
        || { print_error "GHCR 로그인 실패"; exit 1; }
}

pull_images() {
    print_header "📥 GHCR 이미지 풀"
    echo -e "${YELLOW}이미지: ${IMAGE}${NC}"
    docker pull "$IMAGE"
    print_success "풀 완료"
}

deploy() {
    print_header "🚀 배포"
    mkdir -p data
    # 컨테이너는 비root(uid 10001 appuser)로 동작 → SQLite 볼륨 쓰기 권한 필요.
    # 호스트 ./data 소유권을 appuser에게 주고, 안 되면 개방 권한으로 폴백.
    chown -R 10001:10001 data 2>/dev/null || chmod -R 777 data 2>/dev/null || true
    # .env 파일이 있으면 자동 로드(docker compose 기본 동작). 없으면 compose 기본값 사용.
    [ -f .env ] || print_warning ".env 없음 — compose 기본값 사용 (DSM_BASE_URL 등 확인)"
    echo -e "${YELLOW}기존 컨테이너 중지...${NC}"; compose down || true
    echo -e "${YELLOW}컨테이너 시작...${NC}";   compose up -d
    print_success "배포 완료"
    echo ""; status
}

update()  { print_header "🔄 업데이트"; pull_images; echo ""; deploy; }
start()   { compose up -d; print_success "시작됨"; }
stop()    { compose stop; print_success "중지됨"; }
restart() { compose restart; print_success "재시작됨"; }
status()  { compose ps; }
logs()    { compose logs -f --tail=100 ${1:+"$1"}; }

show_help() {
    cat <<EOF

==========================================
  NAS 사진 정리 앱 — NAS 배포 스크립트
==========================================
사용법: $0 [명령어]

  login              GHCR 로그인 (최초 1회, read:packages PAT)
  pull               GHCR 이미지 풀
  deploy             현재 이미지로 배포(down→up)
  update             풀 + 배포 (일반적인 업데이트)
  start / stop / restart / status
  logs [service]     실시간 로그

환경 변수:
  GHCR_USERNAME   GitHub 사용자명 (기본: hyunjoonkwak)
  IMAGE_TAG       이미지 태그 (기본: latest)

예) IMAGE_TAG=latest ./deploy.sh update
EOF
}

case "${1:-help}" in
    login)   ghcr_login ;;
    pull)    pull_images ;;
    deploy)  deploy ;;
    update)  update ;;
    start)   start ;;
    stop)    stop ;;
    restart) restart ;;
    status)  status ;;
    logs)    logs "$2" ;;
    help|--help|-h) show_help ;;
    *) print_error "알 수 없는 명령어: $1"; show_help; exit 1 ;;
esac
