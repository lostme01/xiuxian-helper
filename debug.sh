#!/bin/bash
set -e

# --- 配置 ---
COMPOSE_DEBUG_FILE="docker-compose.debug.yml"
COMPOSE_TEST_FILE="docker-compose.test.yml"
COMPOSE_PROD_FILE="docker-compose.yml"
CONFIG_FILE="config/prod.yaml"

# --- 颜色定义 ---
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

# --- 清理函数 ---
cleanup() {
    echo -e "\n${GREEN}检测到终止信号 (Ctrl+C)，正在清理容器...${NC}"
    docker compose -f ${COMPOSE_DEBUG_FILE} down --remove-orphans
    echo -e "${GREEN}✅ 清理完成。${NC}"
}

# --- 设置 trap 来捕获中断信号 ---
trap cleanup INT TERM

echo -e "${GREEN}========== 开始 Docker Compose 调试会话 ========== ${NC}"

if [ ! -f "$CONFIG_FILE" ]; then
    echo -e "${RED}错误: 配置文件 '$CONFIG_FILE' 未找到!${NC}"
    exit 1
fi
echo ">> 1. 配置文件检查通过。"

echo -e ">> 2. 正在停止其他环境的容器以避免冲突..."
docker compose -f ${COMPOSE_TEST_FILE} down --remove-orphans > /dev/null 2>&1 || true
docker compose -f ${COMPOSE_PROD_FILE} down --remove-orphans > /dev/null 2>&1 || true
echo ">>    其他环境已清理。"

echo -e ">> 3. 正在从本地代码构建并启动调试容器..."
echo -e "${YELLOW}(按 Ctrl+C 停止会话并自动清理容器)${NC}"
echo -e "--------------------------------------------------"

# --- 核心修改：在此处添加 --no-log-prefix 标志 ---
docker compose -f ${COMPOSE_DEBUG_FILE} up --build --no-log-prefix

