#!/bin/bash
set -e

# --- 配置 ---
COMPOSE_PROD_FILE="docker-compose.yml"
COMPOSE_DEBUG_FILE="docker-compose.debug.yml"
CONFIG_FILE="config/prod.yaml"

# --- 颜色定义 ---
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}========== 启动生产环境容器 (使用本地构建) ========== ${NC}"

# 1. 检查核心配置文件
if [ ! -f "$CONFIG_FILE" ]; then
    echo -e "${RED}!! 错误: 核心配置文件 '$CONFIG_FILE' 未找到! 无法启动。${NC}"
    exit 1
fi
echo ">> 1. 配置文件检查通过。"

# 2. 清理所有环境的残留容器
echo -e ">> 2. 正在清理所有环境的残留容器以避免冲突..."
docker compose -f ${COMPOSE_DEBUG_FILE} down --remove-orphans > /dev/null 2>&1 || true
docker compose -f ${COMPOSE_PROD_FILE} down --remove-orphans > /dev/null 2>&1 || true
echo ">>    所有旧容器已清理。"

# 3. [核心修改] 从本地代码构建最新的镜像
echo -e ">> 3. 正在从本地代码构建最新镜像 (tg-game-helper:local)..."
docker compose -f ${COMPOSE_DEBUG_FILE} build
echo ">>    镜像构建完成。"

# 4. 以后台分离模式 (-d) 启动生产容器
echo ">> 4. 正在以分离模式 (-d) 启动生产容器..."
docker compose -f ${COMPOSE_PROD_FILE} up -d

# 5. 清理悬空的旧镜像 (可选)
echo ">> 5. (可选) 清理构建过程中产生的悬空镜像..."
docker image prune -f

echo -e "\n${GREEN}✅ 部署完成！容器已使用最新的本地代码在后台长期运行。${NC}"
echo "   您现在可以使用 'docker logs -f tg-game-helper-prod' 来查看实时日志。"
echo "   使用 'docker compose -f ${COMPOSE_PROD_FILE} down' 来停止服务。"
