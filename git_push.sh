#!/bin/bash
# -----------------------------
# 一键更新 GitHub 仓库脚本
# -----------------------------

# 配置区
REPO_DIR="$HOME/tg-game-helper"   # 本地仓库路径
COMMIT_MSG="$1"                   # 提交信息，来自命令行参数
CACHE_TIMEOUT=360000              # HTTPS 缓存时间（秒）
BRANCH="main"                     # 默认分支

# 如果没输入提交信息，使用默认
if [ -z "$COMMIT_MSG" ]; then
    COMMIT_MSG="Auto update $(date '+%Y-%m-%d %H:%M:%S')"
fi

# 进入项目目录
cd "$REPO_DIR" || { echo "目录不存在: $REPO_DIR"; exit 1; }

echo "-----------------------------"
echo "1. 显示当前修改状态"
git status

echo "-----------------------------"
echo "2. 添加所有修改"
git add -A

echo "-----------------------------"
echo "3. 提交修改"
if git diff --cached --quiet; then
    echo "没有需要提交的更改，跳过 commit"
else
    git commit -m "$COMMIT_MSG"
fi

echo "-----------------------------"
echo "4. 拉取远程最新内容 (rebase)"
git pull --rebase origin "$BRANCH" || { echo "拉取失败"; exit 1; }

echo "-----------------------------"
echo "5. 设置 HTTPS 缓存 (可选，仅需第一次运行)"
git config --global credential.helper "cache --timeout=$CACHE_TIMEOUT"

echo "-----------------------------"
echo "6. 推送到远程仓库"
git push origin "$BRANCH" || { echo "推送失败"; exit 1; }

echo "-----------------------------"
echo "完成 ✅"
