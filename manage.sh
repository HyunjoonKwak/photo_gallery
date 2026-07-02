#!/bin/bash

# NAS 사진 정리 앱 — 로컬 개발 및 GHCR 배포 관리 스크립트
# 로컬에서 이미지를 빌드해 GHCR에 푸시하고, NAS에서는 deploy.sh로 배포한다.

set -e

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"

# GHCR 설정
GHCR_USERNAME="${GHCR_USERNAME:-hyunjoonkwak}"
GHCR_USERNAME=$(echo "$GHCR_USERNAME" | tr '[:upper:]' '[:lower:]')
IMAGE_TAG="${IMAGE_TAG:-latest}"
IMAGE_NAME="nas-photo"
DOCKERFILE="docker/Dockerfile"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; BLUE='\033[0;34m'; NC='\033[0m'
log_info()    { echo -e "${BLUE}ℹ️  $1${NC}"; }
log_success() { echo -e "${GREEN}✅ $1${NC}"; }
log_warning() { echo -e "${YELLOW}⚠️  $1${NC}"; }
log_error()   { echo -e "${RED}❌ $1${NC}"; }

# ==================== 로컬 개발 (Docker) ====================

build() {
    log_info "로컬 이미지 빌드 중..."
    docker compose build ${1:+--no-cache}
    log_success "빌드 완료"
}

start() { docker compose up -d && log_success "시작됨 → http://localhost:9800"; }
stop()  { docker compose down && log_success "중지됨"; }
restart() { docker compose restart && log_success "재시작됨"; }
status()  { docker compose ps; }
logs()    { docker compose logs -f --tail=100 ${1:+"$1"}; }

# 로컬 수정 반영(빌드+재시작)
dev_update() {
    build "$1"
    docker compose up -d
    log_success "dev 업데이트 완료 → http://localhost:9800"
}

# ==================== GHCR 배포 ====================

check_ghcr_login() {
    grep -q "ghcr.io" ~/.docker/config.json 2>/dev/null
}

ghcr_login() {
    if check_ghcr_login; then
        log_success "GHCR 이미 로그인됨 (스킵)"
        return 0
    fi
    log_info "GHCR 로그인 (GitHub Personal Access Token 필요: write:packages 권한)"
    read -p "GitHub 사용자명 [$GHCR_USERNAME]: " input_username
    GHCR_USERNAME="${input_username:-$GHCR_USERNAME}"
    read -rsp "GitHub PAT: " token; echo
    echo "$token" | docker login ghcr.io -u "$GHCR_USERNAME" --password-stdin \
        && log_success "GHCR 로그인 성공" \
        || { log_error "GHCR 로그인 실패"; exit 1; }
}

setup_buildx() {
    local builder="nasphoto-builder"
    if ! docker buildx inspect "$builder" &>/dev/null; then
        log_info "멀티플랫폼 빌더 생성 중..."
        docker buildx create --name "$builder" --driver docker-container --bootstrap
    fi
    docker buildx use "$builder"
}

# 멀티플랫폼 빌드 및 GHCR 푸시 (단일 이미지, 멀티스테이지 Dockerfile)
ghcr_push() {
    local tag="${1:-$IMAGE_TAG}"
    # NAS(amd64)가 타깃이므로 기본 amd64. 다른 타깃은:
    #   BUILD_PLATFORMS="linux/amd64,linux/arm64" ./manage.sh ghcr:push
    local platforms="${BUILD_PLATFORMS:-linux/amd64}"
    local image="ghcr.io/${GHCR_USERNAME}/${IMAGE_NAME}:${tag}"

    log_info "GHCR 이미지 빌드·푸시: $image ($platforms)"
    ghcr_login
    setup_buildx

    docker buildx build \
        --platform "$platforms" \
        -f "$DOCKERFILE" \
        -t "$image" \
        --push \
        "$APP_DIR"

    log_success "빌드 및 푸시 완료: $image"
    echo ""
    log_info "NAS에서 배포하려면:"
    echo "  IMAGE_TAG=${tag} ./deploy.sh update"
}

show_help() {
    cat <<EOF

==========================================
  NAS 사진 정리 앱 — 관리 스크립트 (로컬)
==========================================
사용법: $0 [명령어]

$(echo -e "${BLUE}=== 로컬 개발 (Docker) ===${NC}")
  build [no-cache]     로컬 이미지 빌드
  start / stop / restart / status
  logs                 실시간 로그
  dev:update [no-cache] 빌드 + 재시작 (로컬 수정 테스트)

$(echo -e "${BLUE}=== GHCR 배포 (로컬 → NAS) ===${NC}")
  ghcr:login           GHCR 로그인 (PAT, write:packages)
  ghcr:push [tag]      이미지 빌드 및 GHCR 푸시 (기본 amd64)

$(echo -e "${YELLOW}환경 변수:${NC}")
  GHCR_USERNAME   GitHub 사용자명 (기본: hyunjoonkwak)
  IMAGE_TAG       이미지 태그 (기본: latest)
  BUILD_PLATFORMS 빌드 플랫폼 (기본: linux/amd64)
EOF
}

case "${1:-help}" in
    build)       build "$2" ;;
    start)       start ;;
    stop)        stop ;;
    restart)     restart ;;
    status)      status ;;
    logs)        logs "$2" ;;
    dev:update)  dev_update "$2" ;;
    ghcr:login)  ghcr_login ;;
    ghcr:push)   ghcr_push "$2" ;;
    help|--help|-h) show_help ;;
    *) log_error "알 수 없는 명령어: $1"; show_help; exit 1 ;;
esac
