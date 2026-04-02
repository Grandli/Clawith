#!/bin/bash
# Clawith — Stop Script
# Usage: ./stop.sh [--source] [--all]
#   --source  Force source (non-Docker) mode stop
#   --all     Also try to stop local PostgreSQL

set -e

# ═══════════════════════════════════════════════════════
# 配置 (与 restart.sh 保持一致)
# ═══════════════════════════════════════════════════════
ROOT="$(cd "$(dirname "$0")" && pwd)"
DATA_DIR="$ROOT/.data"
PID_DIR="$DATA_DIR/pid"

BACKEND_PORT=8008
FRONTEND_PORT=3008
BACKEND_PID="$PID_DIR/backend.pid"
FRONTEND_PID="$PID_DIR/frontend.pid"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'; CYAN='\033[0;36m'; NC='\033[0m'

# 参数解析
FORCE_SOURCE=false
STOP_POSTGRES=false
for arg in "$@"; do
    case $arg in
        --source) FORCE_SOURCE=true ;;
        --all) STOP_POSTGRES=true ;;
    esac
done

# ═══════════════════════════════════════════════════════
# 停止 Docker 模式
# ═══════════════════════════════════════════════════════
stop_docker_mode() {
    if [ "$FORCE_SOURCE" = true ]; then return 1; fi

    if command -v docker &>/dev/null && docker ps --filter 'name=clawith' -q 2>/dev/null | grep -q .; then
        echo -e "${YELLOW}🛑 Stopping Clawith Docker containers...${NC}"
        cd "$ROOT"
        docker compose down || docker-compose down || true
        echo -e "${GREEN}✅ Docker containers stopped.${NC}"
        return 0
    fi
    return 1
}

# ═══════════════════════════════════════════════════════
# 停止源码模式服务
# ═══════════════════════════════════════════════════════
stop_source_services() {
    echo -e "${YELLOW}🔄 Stopping source services...${NC}"

    # 1. 通过 PID 文件停止
    for service in "Backend" "Frontend"; do
        pidfile=""
        [ "$service" == "Backend" ] && pidfile="$BACKEND_PID"
        [ "$service" == "Frontend" ] && pidfile="$FRONTEND_PID"

        if [ -f "$pidfile" ]; then
            PID=$(cat "$pidfile")
            echo -e "  Stopping $service (PID: $PID)..."
            kill "$PID" 2>/dev/null || kill -9 "$PID" 2>/dev/null || true
            rm -f "$pidfile"
        fi
    done

    # 2. 通过端口二次检查 (确保彻底杀死)
    for port in $BACKEND_PORT $FRONTEND_PORT; do
        if command -v lsof &>/dev/null; then
            PIDS=$(lsof -ti:$port)
            if [ -n "$PIDS" ]; then
                echo -e "  Cleaning up remaining processes on port $port..."
                echo "$PIDS" | xargs kill -9 2>/dev/null || true
            fi
        elif command -v fuser &>/dev/null; then
            fuser -k $port/tcp 2>/dev/null || true
        fi
    done

    echo -e "${GREEN}✅ Backend and Frontend services stopped.${NC}"
}

# ═══════════════════════════════════════════════════════
# 停止 PostgreSQL (仅当使用 --all 参数时)
# ═══════════════════════════════════════════════════════
stop_postgres() {
    if [ "$STOP_POSTGRES" = false ]; then
        return 0
    fi

    echo -e "${YELLOW}🐘 Attempting to stop local PostgreSQL...${NC}"
    
    # 尝试使用 pg_ctl 停止 (Clawith 默认方式)
    if [ -f "$ROOT/.pgdata/postmaster.pid" ] && command -v pg_ctl &>/dev/null; then
        pg_ctl -D "$ROOT/.pgdata" stop -m fast >/dev/null 2>&1 || true
        echo -e "  ${GREEN}✅ Local PostgreSQL (.pgdata) stopped.${NC}"
    # 尝试使用 systemctl (系统级方式)
    elif command -v systemctl &>/dev/null && systemctl is-active --quiet postgresql; then
        echo -e "  Stopping system-wide PostgreSQL via systemctl..."
        sudo systemctl stop postgresql 2>/dev/null || true
        echo -e "  ${GREEN}✅ System PostgreSQL stopped.${NC}"
    else
        echo -e "  ${CYAN}ℹ️ No active local PostgreSQL found to stop.${NC}"
    fi
}

# ═══════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════
main() {
    echo -e "${CYAN}═══════════════════════════════════════${NC}"
    echo -e "${CYAN}   Clawith Shutdown Procedure${NC}"
    echo -e "${CYAN}═══════════════════════════════════════${NC}"

    # 优先尝试停止 Docker
    if ! stop_docker_mode; then
        # 如果不是 Docker 或强制源码模式，则停止源码进程
        stop_source_services
    fi

    # 停止数据库（可选）
    stop_postgres

    echo -e "\n${GREEN}✨ All specified Clawith services have been shut down.${NC}"
}

main "$@"