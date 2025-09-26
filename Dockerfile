# 使用官方 Python slim 镜像以减小体积
FROM python:3.10-slim

# 设置环境变量，禁止生成 .pyc 文件并开启无缓冲输出 (修正后的格式)
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# 设置容器内的工作目录
WORKDIR /app

# 复制依赖文件并安装
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制所有应用代码到工作目录
COPY . .

# 容器启动时执行的命令
CMD ["python", "main.py"]
