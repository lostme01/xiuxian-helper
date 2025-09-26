#!/bin/bash
set -e
IMAGE_NAME="tg-game-helper-img"
CONTAINER_NAME="tg-game-helper-prod"
CONFIG_FILE="config/prod.yaml"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

echo -e "${GREEN}========== 启动生产模式容器 ========== ${NC}"
if [ ! -f "$CONFIG_FILE" ]; then
    echo -e "${RED}错误: 配置文件 '$CONFIG_FILE' 未找到!${NC}"
    exit 1
fi
if [ "$(docker ps -a -q -f name=^/${CONTAINER_NAME}$)" ]; then
    echo -e "${YELLOW}发现已存在的生产容器，正在移除...${NC}"
    docker stop ${CONTAINER_NAME} > /dev/null
    docker rm ${CONTAINER_NAME} > /dev/null
fi
echo -e "${YELLOW}正在构建最新镜像...${NC}"
docker build -t ${IMAGE_NAME} .
echo -e "${YELLOW}正在启动新的生产容器...${NC}"

# 恢复对 config, data, logs 三个目录的映射
docker run -d \
  --name ${CONTAINER_NAME} \
  --restart always \
  -v "$(pwd)/config/prod.yaml:/app/config/prod.yaml" \
  -v "$(pwd)/data:/app/data" \
  -v "$(pwd)/logs:/app/logs" \
  ${IMAGE_NAME}

echo -e "${GREEN}✅ 生产容器 '${CONTAINER_NAME}' 已成功启动。${NC}"
echo -e "您现在可以使用 'docker logs -f ${CONTAINER_NAME}' 来查看实时日志。"
