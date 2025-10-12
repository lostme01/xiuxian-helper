# -*- coding: utf-8 -*-
import asyncio
import os
import sys
import json

import yaml
from dotenv import load_dotenv
import redis.asyncio as redis

# --- 安全检查：确保在项目根目录运行 ---
if not os.path.isdir('config') or not os.path.isdir('app'):
    print("错误：请在项目根目录 (tg-game-helper/) 中运行此脚本。")
    sys.exit(1)

# --- 模拟加载项目常量 ---
from app.constants import CRAFTING_RECIPES_KEY, BASE_KEY, STATE_KEY_INVENTORY, STATE_KEY_PROFILE

print("--- TG Game Helper 数据检查工具 ---")

def print_section_header(title):
    """打印一个美化的分段标题"""
    print("\n" + "="*60)
    print(f" {title.center(58)} ")
    print("="*60)

async def main():
    # --- 加载配置 ---
    print("\n[步骤 1/3] 正在加载数据库配置...")
    try:
        load_dotenv()
        with open('config/prod.yaml', 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        redis_config = config.get('redis', {})
        redis_config['password'] = os.getenv('REDIS_PASSWORD') or redis_config.get('password')
        redis_config['host'] = '127.0.0.1' # 固定为 localhost
        
        print("  - 配置加载成功。")
    except Exception as e:
        print(f"  - ❌ 错误: 加载配置文件失败: {e}")
        sys.exit(1)

    # --- 连接 Redis ---
    db = None
    try:
        print("[步骤 2/3] 正在连接到 Redis 数据库...")
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

    # --- 读取并显示数据 ---
    print("[步骤 3/3] 正在读取并展示数据...")
    try:
        # 1. 显示配方数据库
        print_section_header("配方数据库 (crafting_recipes)")
        recipes = await db.hgetall(CRAFTING_RECIPES_KEY)
        if not recipes:
            print("  - 数据库中没有找到任何配方。")
        else:
            sorted_recipes = sorted(recipes.items())
            for item_name, materials_json in sorted_recipes:
                print(f"\n- 【{item_name}】需要:")
                try:
                    materials = json.loads(materials_json)
                    for mat, qty in materials.items():
                        # 在材料名称两边加上引号，以便清晰地看到是否有前导/后导空格或符号
                        print(f"    - '{mat}': {qty}")
                except json.JSONDecodeError:
                    print("    - [错误] 解析材料数据失败。")

        # 2. 显示所有助手的背包数据
        print_section_header("各助手背包数据 (inventory)")
        assistant_keys = [key async for key in db.scan_iter(f"{BASE_KEY}:*")]
        if not assistant_keys:
            print("  - 未找到任何助手的缓存数据。")
        else:
            for key in sorted(assistant_keys):
                user_id = key.split(':')[-1]
                profile_json = await db.hget(key, STATE_KEY_PROFILE)
                user_info = f"用户ID: {user_id}"
                if profile_json:
                    try:
                        profile = json.loads(profile_json)
                        user_info = f"{profile.get('道号', '未知道号')} (ID: {user_id})"
                    except json.JSONDecodeError:
                        pass
                
                print(f"\n--- 助手: {user_info} ---")
                
                inventory_json = await db.hget(key, STATE_KEY_INVENTORY)
                if not inventory_json:
                    print("  - 背包数据为空。")
                    continue
                
                try:
                    inventory = json.loads(inventory_json)
                    if not inventory:
                        print("  - 背包为空。")
                        continue

                    sorted_inventory = sorted(inventory.items())
                    for item, count in sorted_inventory:
                        # 同样，在物品名称两边加上引号
                        print(f"  - '{item}': {count}")
                except json.JSONDecodeError:
                    print("  - [错误] 解析背包数据失败。")

    except Exception as e:
        print(f"  - ❌ 错误: 读取数据时发生错误: {e}")
    finally:
        if db:
            await db.aclose()
            print("\n数据库连接已关闭。")

if __name__ == "__main__":
    asyncio.run(main())
