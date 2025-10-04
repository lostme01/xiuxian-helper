# -*- coding: utf-8 -*-
import json
from collections import defaultdict
from app.context import get_application
from app.logger import format_and_log
from app.inventory_manager import inventory_manager

CRAFTING_RECIPES_KEY = "crafting_recipes"
STATES_KEY_PATTERN = "tg_helper:task_states:*"

async def logic_check_local_materials(item_name: str, quantity: int = 1) -> dict | str:
    """
    仅检查本地库存是否足够炼制指定物品。
    如果足够，返回空字典。
    如果不足，返回缺失的材料字典。
    如果配方不存在或无法炼制，返回错误字符串。
    """
    app = get_application()
    if not app.redis_db:
        return "❌ 错误: Redis 未连接。"
    
    recipe_json = await app.redis_db.hget(CRAFTING_RECIPES_KEY, item_name)
    if not recipe_json:
        return f"❌ **规划失败**: 在配方数据库中未找到“{item_name}”的配方。"
    
    try:
        unit_materials = json.loads(recipe_json)
        if "error" in unit_materials:
            return f"❌ **规划失败**: “{item_name}”无法被人工炼制。"
        if "修为" in unit_materials:
            del unit_materials["修为"]
        
        required_materials = {k: v * quantity for k, v in unit_materials.items()}
        
        local_inventory = await inventory_manager.get_inventory()
        
        missing = {}
        for material, required in required_materials.items():
            if local_inventory.get(material, 0) < required:
                missing[material] = required - local_inventory.get(material, 0)
        
        return missing

    except json.JSONDecodeError:
        return "❌ **规划失败**: 解析配方数据时出错。"


async def logic_plan_crafting_session(item_name: str, initiator_id: str, quantity: int = 1) -> dict | str:
    """
    规划一次多账号协同炼制任务，寻找材料供应方。
    """
    app = get_application()
    if not app.redis_db:
        return "❌ 错误: Redis 未连接。"

    # 1. 获取配方并计算总需求
    recipe_json = await app.redis_db.hget(CRAFTING_RECIPES_KEY, item_name)
    if not recipe_json:
        return f"❌ **规划失败**: 在配方数据库中未找到“{item_name}”的配方。"
    
    try:
        unit_materials = json.loads(recipe_json)
        if "error" in unit_materials:
            return f"❌ **规划失败**: “{item_name}”无法被人工炼制。"
        if "修为" in unit_materials:
            del unit_materials["修为"]
            
        required_materials = {k: v * quantity for k, v in unit_materials.items()}
        
    except json.JSONDecodeError:
        return "❌ **规划失败**: 解析配方数据时出错。"

    # 2. 聚合所有其他助手的库存
    accounts_inventories = {}
    total_network_inventory = defaultdict(int)
    
    keys_found = [key async for key in app.redis_db.scan_iter(STATES_KEY_PATTERN)]
    for key in keys_found:
        account_id = key.split(':')[-1]
        if account_id == initiator_id:
            continue
            
        inventory_json = await app.redis_db.hget(key, "inventory")
        if inventory_json:
            try:
                inventory = json.loads(inventory_json)
                accounts_inventories[account_id] = inventory
                for material, count in inventory.items():
                    total_network_inventory[material] += count
            except json.JSONDecodeError:
                continue

    # 3. 全局可行性分析 (只考虑网络库存)
    missing_materials = {mat: req_count - total_network_inventory[mat] for mat, req_count in required_materials.items() if total_network_inventory[mat] < req_count}
    if missing_materials:
        errors = [f"- `{name}`: 缺少 {count}" for name, count in missing_materials.items()]
        return f"❌ **材料不足，无法炼制**:\n" + "\n".join(errors)

    # 4. 分配策略
    contribution_plan = defaultdict(lambda: defaultdict(int))
    
    # 优先从单个助手中凑齐
    for acc_id, inventory in accounts_inventories.items():
        if all(inventory.get(mat, 0) >= req_count for mat, req_count in required_materials.items()):
            for mat, req_count in required_materials.items():
                contribution_plan[acc_id][mat] = req_count
            return dict(contribution_plan)

    # 凑不齐时，启动贪心算法
    temp_inventories = {acc_id: inv.copy() for acc_id, inv in accounts_inventories.items()}
    
    for material, required_count in required_materials.items():
        needed = required_count
        
        sorted_accounts = sorted(
            temp_inventories.keys(),
            key=lambda acc_id: temp_inventories[acc_id].get(material, 0),
            reverse=True
        )
        
        for acc_id in sorted_accounts:
            if needed <= 0: break
            
            available = temp_inventories[acc_id].get(material, 0)
            if available > 0:
                contribution = min(needed, available)
                contribution_plan[acc_id][material] += contribution
                temp_inventories[acc_id][material] -= contribution
                needed -= contribution

    format_and_log("TASK", "炼制规划", {'物品': item_name, '数量': quantity, '总需求': required_materials, '最终分配方案': json.dumps(contribution_plan, indent=2)})
    return dict(contribution_plan)
