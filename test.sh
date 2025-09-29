#!/bin/bash
set -e

# --- 配置 ---
IMAGE_NAME="tg-game-helper:local"
COMPOSE_DEBUG_FILE="docker-compose.debug.yml"
COMPOSE_TEST_FILE="docker-compose.test.yml"
COMPOSE_PROD_FILE="docker-compose.yml"
CONFIG_FILE="config/prod.yaml"

# --- 颜色定义 ---
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}========== 启动本地后台长时间测试 ========== ${NC}"

if [ ! -f "$CONFIG_FILE" ]; then
    echo -e "${RED}!! 错误: 核心配置文件 '$CONFIG_FILE' 未找到!${NC}"
    exit 1
fi
echo ">> 0. 配置文件检查通过。"

echo ">> 1. 正在检查本地镜像 ${YELLOW}${IMAGE_NAME}${NC} 是否存在..."
if [[ "$(docker images -q ${IMAGE_NAME} 2> /dev/null)" == "" ]]; then
  echo -e "${RED}!! 错误: 本地镜像 ${IMAGE_NAME} 不存在。${NC}"
  echo -e "${YELLOW}   请先运行 ./debug.sh 成功构建一次镜像后再试。${NC}"
  exit 1
fi
echo ">>    本地镜像检查通过。"

# --- 核心修改：启动前，自动停止其他环境的容器 ---
echo -e ">> 2. 正在停止其他环境的容器以避免冲突..."
docker compose -f ${COMPOSE_DEBUG_FILE} down --remove-orphans > /dev/null 2>&1 || true
docker compose -f ${COMPOSE_PROD_FILE} down --remove-orphans > /dev/null 2>&1 || true
echo ">>    其他环境已清理。"

echo -e ">> 3. 正在以后台模式启动测试容器..."
docker compose -f ${COMPOSE_TEST_FILE} up -d

echo -e "\n${GREEN}✅ 后台测试容器已成功启动！${NC}"
echo "您现在可以使用 'docker logs -f tg-game-helper-test' 来查看实时日志。"
echo "要停止后台测试，请运行 'docker compose -f ${COMPOSE_TEST_FILE} down'。"
