# -*- coding: utf-8 -*-
import asyncio
import os
import sys
import re
import json

import yaml
from dotenv import load_dotenv
import redis.asyncio as redis

# --- 安全检查：确保在项目根目录运行 ---
if not os.path.isdir('config') or not os.path.isdir('app'):
    print("错误：请在项目根目录 (tg-game-helper/) 中运行此脚本。")
    sys.exit(1)

# --- 模拟加载项目常量 ---
from app.constants import CRAFTING_RECIPES_KEY

print("--- TG Game Helper 配方更新工具 ---")

# ==============================================================================
# 将您提供的配方文本粘贴到这里
# ==============================================================================
RECIPE_TEXT = """
【增元丹】：凝血草x4, 灵石x10。需炼气五层。
【凝气散】：一阶妖丹x1, 凝血草x4, 灵石x10。需炼气八层。
【清灵丹】：清灵草x3, 凝血草x5。
【合气丹】：一阶妖丹x5, 凝血草x10, 三级妖丹x5。
【黄芽丹】：百年铁木x3, 一阶妖丹x30。需筑基初期。
【天火液】：养魂木x2, 二级妖丹x5, 金精矿x10, 三级妖丹x1。
【凝魂丹】：养魂木x1, 阴魂丝x10, 清灵草x20, 三级妖丹x1。
【三转重元丹】：天雷竹x4, 百年铁木x10, 一阶妖丹x30, 三级妖丹x1。
【九曲灵参丹】：养魂木x15, 二级妖丹x30, 三级妖丹x5。
【风行丹】：一截灵眼之树x1, 养魂木x3, 天雷竹x5。
【玄铁剑】：灵石x10。
【金蚨子母刃】：金精矿x2, 一阶妖丹x3, 灵石x50。
【乌龙幡】：阴魂丝x5, 一阶妖丹x2, 灵石x40。
【青竹蜂云剑】：天雷竹x12, 金精矿x10, 二级妖丹x5, 灵石x80。
【金光砖】：金精矿x12, 二级妖丹x3, 灵石x60。
【风雷翅】：天雷竹x10, 三级妖丹x50, 二级妖丹x10, 金精矿x8, 灵石x100。需结丹中期。
【皇鳞甲】：一截灵眼之树x5, 二级妖丹x10, 金精矿x8, 灵石x100, 三级妖丹x40。需结丹中期。
【青鸾天盾】：养魂木x20, 三级妖丹x20, 元磁山核·甲x1, 元磁山核·乙x1, 元磁山核·丙x1, 元磁山核·丁x1。
【神行符】：凝血草x5, 灵石x20。
【金刚符】：一阶妖丹x1, 灵石x20。
【九转凝魂丹】：【空间之核】x1, 【法则碎片·木】x5, 【法则碎片·水】x5, 【养魂木】x20。
【太虚丹】：【太虚仙露】x1, 【法则碎片·火】x5, 【法则碎片·土】x5, 【九曲灵参丹】x5。
【佑天神盾】：【九天神雷木】x1, 【法则碎片·风】x3, 【法则碎片·雷】x3, 【天雷竹】x50。
"""
# ==============================================================================

def parse_recipes(text: str) -> dict:
    """
    智能解析配方文本，返回一个字典。
    """
    parsed_data = {}
    lines = text.strip().split('\n')
    
    # 正则表达式，用于匹配 "材料名x数量"
    material_pattern = re.compile(r"【?([^】x]+?)】?x(\d+)")

    for line in lines:
        if '：' not in line:
            continue
            
        parts = line.split('：', 1)
        item_name = parts[0].replace('【', '').replace('】', '').strip()
        materials_text = parts[1]
        
        materials = {}
        matches = material_pattern.findall(materials_text)
        
        for name, quantity in matches:
            materials[name.strip()] = int(quantity)
            
        if materials:
            parsed_data[item_name] = materials
            
    return parsed_data

async def main():
    # --- 加载配置 ---
    print("\n[步骤 1/4] 正在加载数据库配置...")
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

    # --- 解析配方 ---
    print("[步骤 3/4] 正在解析配方文本...")
    recipes_to_update = parse_recipes(RECIPE_TEXT)
    if not recipes_to_update:
        print("  - ❌ 错误: 未能从提供的文本中解析出任何配方。")
        await db.aclose()
        sys.exit(1)
    
    print(f"  - 解析完成，共发现 {len(recipes_to_update)} 条配方需要更新。")

    # --- 更新 Redis ---
    print("[步骤 4/4] 正在将配方写入数据库...")
    updated_count = 0
    try:
        # 使用 pipeline 提高写入效率
        async with db.pipeline(transaction=False) as pipe:
            for item_name, materials in recipes_to_update.items():
                await pipe.hset(CRAFTING_RECIPES_KEY, item_name, json.dumps(materials, ensure_ascii=False))
                print(f"  - 准备更新: {item_name}")
                updated_count += 1
            await pipe.execute()
        
        print(f"\n  - ✅ 操作完成！成功更新或覆盖了 {updated_count} 条配方到数据库。")
    except Exception as e:
        print(f"  - ❌ 错误: 写入 Redis 时发生错误: {e}")
    finally:
        if db:
            await db.aclose()
            print("\n数据库连接已关闭。")

if __name__ == "__main__":
    asyncio.run(main())
