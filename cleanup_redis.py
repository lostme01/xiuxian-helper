# -*- coding: utf-8 -*-
import asyncio
import os
import sys
import argparse

import yaml
from dotenv import load_dotenv
import redis.asyncio as redis

# --- 安全检查：确保在项目根目录运行 ---
if not os.path.isdir('config') or not os.path.isdir('app'):
    print("错误：请在项目根目录 (tg-game-helper/) 中运行此脚本。")
    sys.exit(1)

# --- 模拟加载项目配置 ---
from app.constants import (
    BASE_KEY, CRAFTING_RECIPES_KEY, CRAFTING_SESSIONS_KEY, 
    KNOWLEDGE_SESSIONS_KEY
)

print("--- TG Game Helper Redis 清理工具 ---")

# --- 定义当前版本项目使用的“合法”Redis键 ---
VALID_KEY_PREFIXES = [
    BASE_KEY,
]
VALID_EXACT_KEYS = [
    CRAFTING_RECIPES_KEY,
    CRAFTING_SESSIONS_KEY,
    KNOWLEDGE_SESSIONS_KEY,
]

async def main():
    # --- 参数解析 ---
    parser = argparse.ArgumentParser(description="清理 TG Game Helper 项目的 Redis 孤儿数据。")
    parser.add_argument(
        '--execute',
        action='store_true',
        help='执行删除操作。如果未提供此参数，将只进行“预演”（Dry Run），列出将要删除的键。'
    )
    args = parser.parse_args()

    # --- 加载配置 ---
    print("\n[步骤 1/4] 正在加载数据库配置...")
    try:
        load_dotenv()
        with open('config/prod.yaml', 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)

        redis_config = config.get('redis', {})
        redis_config['password'] = os.getenv('REDIS_PASSWORD') or redis_config.get('password')

        redis_config['host'] = '127.0.0.1'

        VALID_EXACT_KEYS.append(redis_config.get('xuangu_db_name', 'xuangu_qa'))
        VALID_EXACT_KEYS.append(redis_config.get('tianji_db_name', 'tianji_qa'))

        print("  - 配置加载成功。")
    except Exception as e:
        print(f"  - ❌ 错误: 加载配置文件失败: {e}")
        sys.exit(1)

    # --- 连接 Redis ---
    db = None
    try:
        print("[步骤 2/4] 正在连接到 Redis 数据库...")
        pool = redis.ConnectionPool.from_url(
            f"redis://{redis_config.get('host')}",
            port=redis_config.get('port'),
            password=redis_config.get('password'),
            db=redis_config.get('db'),
            decode_responses=True,
            socket_connect_timeout=5
        )
        db = redis.Redis(connection_pool=pool)
        await db.ping()
        print(f"  - 连接成功: {redis_config.get('host')}:{redis_config.get('port')}")
    except Exception as e:
        print(f"  - ❌ 错误: 连接 Redis 失败: {e}")
        if db:
            await db.aclose()
        sys.exit(1)

    # --- 扫描和分析 ---
    orphaned_keys = []
    try:
        print("[步骤 3/4] 正在扫描并分析所有键...")
        total_keys = 0
        async for key in db.scan_iter("*"):
            total_keys += 1
            is_valid = False
            if key in VALID_EXACT_KEYS:
                is_valid = True

            if not is_valid:
                for prefix in VALID_KEY_PREFIXES:
                    if key.startswith(prefix):
                        is_valid = True
                        break

            if not is_valid:
                orphaned_keys.append(key)

        print(f"  - 分析完成。共扫描 {total_keys} 个键，发现 {len(orphaned_keys)} 个可能无用的键。")

    except Exception as e:
        print(f"  - ❌ 错误: 扫描 Redis 时发生错误: {e}")

    # --- 执行或预演 ---
    print("[步骤 4/4] 准备执行操作...")
    if not orphaned_keys:
        print("  - ✅ 数据库非常干净，未发现任何无用的键。无需清理。")
    elif not args.execute:
        print("\n  - 🟡 **预演模式 (Dry Run)** -")
        print("  - 以下键被识别为无用数据，但 **不会** 被删除：")
        for key in orphaned_keys:
            print(f"    - `{key}`")
        print("\n  - 要真正删除这些键，请使用 `--execute` 参数重新运行此脚本。")
        print("  - 命令示例: python3 cleanup_redis.py --execute")
    else:
        print("\n  - 🟢 **执行模式 (Execute)** -")
        try:
            print(f"  - 正在删除 {len(orphaned_keys)} 个无用的键...")
            deleted_count = await db.delete(*orphaned_keys)
            print(f"  - ✅ 操作完成！成功删除了 {deleted_count} 个键。")
        except Exception as e:
            print(f"  - ❌ 错误: 删除键时发生错误: {e}")

    # --- 关闭连接 ---
    if db:
        # [修复] 使用新的 aclose() 方法
        await db.aclose()
        print("\n数据库连接已关闭。")

if __name__ == "__main__":
    asyncio.run(main())
