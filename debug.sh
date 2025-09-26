#!/bin/bash
set -e
IMAGE_NAME="tg-game-helper-img"
CONTAINER_NAME="tg-game-helper-debug"
CONFIG_FILE="config/prod.yaml"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'

echo -e "${GREEN}========== 开始原生Docker调试会话 ========== ${NC}"
if [ ! -f "$CONFIG_FILE" ]; then
    echo -e "${RED}错误: 配置文件 '$CONFIG_FILE' 未找到!${NC}"
    exit 1
fi
echo "配置文件检查通过。"
if [ "$(docker ps -a -q -f name=^/${CONTAINER_NAME}$)" ]; then
    echo -e "${YELLOW}发现已存在的容器 '${CONTAINER_NAME}'，正在停止并移除...${NC}"
    docker stop ${CONTAINER_NAME} > /dev/null
    docker rm ${CONTAINER_NAME} > /dev/null
    echo -e "${GREEN}旧容器已成功清理。${NC}"
else
    echo -e "未发现旧的 '${CONTAINER_NAME}' 容器，跳过清理。"
fi
echo -e "\n${YELLOW}正在构建 Docker 镜像: ${IMAGE_NAME}...${NC}"
docker build -t ${IMAGE_NAME} .
echo -e "${GREEN}镜像构建完成。${NC}"
echo -e "\n${YELLOW}正在启动新的调试容器... (按 Ctrl+C 停止)${NC}"
echo -e "--------------------------------------------------"

# 恢复对 config, data, logs 三个目录的映射
docker run --rm -it --name ${CONTAINER_NAME} \
  -v "$(pwd)/config/prod.yaml:/app/config/prod.yaml" \
  -v "$(pwd)/data:/app/data" \
  -v "$(pwd)/logs:/app/logs" \
  ${IMAGE_NAME}

echo -e "--------------------------------------------------"
echo -e "${GREEN}调试会话结束。容器已自动清理。${NC}"
