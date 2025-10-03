# -*- coding: utf-8 -*-
import json
from collections import defaultdict
from app.context import get_application
from app.logger import format_and_log

CRAFTING_RECIPES_KEY = "crafting_recipes"
STATES_KEY_PATTERN = "tg_helper:task_states:*"

async def logic_plan_crafting_session(item_name: str, initiator_id: str) -> dict | str:
    """
    规划一次多账号协同炼制任务。
    返回一个“贡献清单”或错误信息。
    """
    app = get_application()
    if not app.redis_db:
        return "❌ 错误: Redis 未连接。"

    # 1. 获取配方
    recipe_json = await app.redis_db.hget(CRAFTING_RECIPES_KEY, item_name)
    if not recipe_json:
        return f"❌ **规划失败**: 在配方数据库中未找到“{item_name}”的配方。"
    
    try:
        required_materials = json.loads(recipe_json)
        if "error" in required_materials:
            return f"❌ **规划失败**: “{item_name}”无法被人工炼制。"
        if "修为" in required_materials:
            del required_materials["修为"] # 忽略对修为的需求
    except json.JSONDecodeError:
        return "❌ **规划失败**: 解析配方数据时出错。"

    # 2. 聚合所有助手的库存
    total_inventory = defaultdict(int)
    accounts_inventories = {}
    
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
                    total_inventory[material] += count
            except json.JSONDecodeError:
                continue

    # 3. 可行性分析
    missing_materials = {}
    for material, required_count in required_materials.items():
        if total_inventory[material] < required_count:
            missing_materials[material] = required_count - total_inventory[material]
            
    if missing_materials:
        errors = [f"- `{name}`: 缺少 {count}" for name, count in missing_materials.items()]
        return f"❌ **材料不足，无法炼制**:\n" + "\n".join(errors)

    # 4. 智能分配
    contribution_plan = defaultdict(lambda: defaultdict(int))
    
    for material, required_count in required_materials.items():
        needed = required_count
        # 按库存从多到少排序，优先让存货多的号出材料
        sorted_accounts = sorted(
            accounts_inventories.keys(),
            key=lambda acc_id: accounts_inventories[acc_id].get(material, 0),
            reverse=True
        )
        
        for acc_id in sorted_accounts:
            if needed == 0: break
            
            available = accounts_inventories[acc_id].get(material, 0)
            if available > 0:
                contribution = min(needed, available)
                contribution_plan[acc_id][material] += contribution
                needed -= contribution

    format_and_log("TASK", "炼制规划", {'物品': item_name, '需求': required_materials, '分配方案': json.dumps(contribution_plan, indent=2)})
    return dict(contribution_plan)
