#!/bin/bash
set -e

# --- 配置 ---
IMAGE_NAME="lostme01/tg-game-helper:latest"
COMPOSE_DEBUG_FILE="docker-compose.debug.yml"
COMPOSE_TEST_FILE="docker-compose.test.yml"
COMPOSE_PROD_FILE="docker-compose.yml"
CONFIG_FILE="config/prod.yaml"

# --- 颜色定义 ---
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}========== 开始生产环境部署 ========== ${NC}"

if [ ! -f "$CONFIG_FILE" ]; then
    echo -e "${RED}!! 错误: 核心配置文件 '$CONFIG_FILE' 未找到! 无法部署。${NC}"
    exit 1
fi
echo ">> 0. 配置文件检查通过。"

# --- 核心修改：启动前，自动停止其他环境的容器 ---
echo -e ">> 1. 正在停止其他环境的容器以避免冲突..."
docker compose -f ${COMPOSE_DEBUG_FILE} down --remove-orphans > /dev/null 2>&1 || true
docker compose -f ${COMPOSE_TEST_FILE} down --remove-orphans > /dev/null 2>&1 || true
echo ">>    其他环境已清理。"

echo ">> 2. 正在从 Docker Hub 拉取最新稳定镜像: ${YELLOW}${IMAGE_NAME}${NC}"
docker pull ${IMAGE_NAME}

echo ">> 3. 正在以分离模式 (-d) 启动生产容器..."
docker compose -f ${COMPOSE_PROD_FILE} up -d

echo ">> 4. (可选) 清理悬空的旧镜像..."
docker image prune -f

echo -e "\n${GREEN}✅ 部署完成！${NC}"
echo "您现在可以使用 'docker logs -f tg-game-helper-prod' 来查看实时日志。"
