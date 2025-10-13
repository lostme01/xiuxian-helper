#!/bin/bash
set -e

# --- 配置 ---
COMPOSE_DEBUG_FILE="docker-compose.debug.yml"
COMPOSE_PROD_FILE="docker-compose.yml"
CONFIG_FILE="config/prod.yaml"

# --- 颜色定义 ---
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

# --- 清理函数 (用于捕获 Ctrl+C) ---
cleanup() {
    echo -e "\n${GREEN}检测到终止信号 (Ctrl+C)，正在清理调试容器...${NC}"
    docker compose -f ${COMPOSE_DEBUG_FILE} down --remove-orphans
    echo -e "${GREEN}✅ 清理完成。${NC}"
}
trap cleanup INT TERM

echo -e "${GREEN}========== 开始 Docker Compose 调试会话 ========== ${NC}"

# 1. 检查核心配置文件
if [ ! -f "$CONFIG_FILE" ]; then
    echo -e "${RED}!! 错误: 核心配置文件 '$CONFIG_FILE' 未找到! 无法启动。${NC}"
    exit 1
fi
echo ">> 1. 配置文件检查通过。"

# 2. 【核心】互相清理：停止并移除对方(prod)和自己(debug)可能存在的残留容器
echo -e ">> 2. 正在清理所有环境的残留容器以避免冲突..."
docker compose -f ${COMPOSE_PROD_FILE} down --remove-orphans > /dev/null 2>&1 || true
docker compose -f ${COMPOSE_DEBUG_FILE} down --remove-orphans > /dev/null 2>&1 || true
echo ">>    所有旧容器已清理。"

# 3. 从本地代码构建并启动调试容器
echo -e ">> 3. 正在从本地代码构建并启动调试容器 (前台附加模式)..."
echo -e "${YELLOW}(按 Ctrl+C 停止会话并自动清理容器)${NC}"
echo -e "--------------------------------------------------"

# --no-log-prefix 参数可以使日志更简洁
docker compose -f ${COMPOSE_DEBUG_FILE} up --build --no-log-prefix
