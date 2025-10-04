# -*- coding: utf-8 -*-
import json
from collections import defaultdict
from app.context import get_application
from app.logger import format_and_log

CRAFTING_RECIPES_KEY = "crafting_recipes"
STATES_KEY_PATTERN = "tg_helper:task_states:*"

async def logic_plan_crafting_session(item_name: str, initiator_id: str, quantity: int = 1) -> dict | str:
    """
    [v2.0 智能分配版]
    规划一次多账号协同炼制任务。
    1. 优先尝试从单个助手中凑齐所有材料。
    2. 如果无法单人完成，则启动贪心算法，从最富有的助手中依次获取，以最小化交易次数。
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

    # 2. 聚合所有助手的库存
    accounts_inventories = {}
    total_inventory = defaultdict(int)
    
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

    # 3. 全局可行性分析
    missing_materials = {mat: req_count - total_inventory[mat] for mat, req_count in required_materials.items() if total_inventory[mat] < req_count}
    if missing_materials:
        errors = [f"- `{name}`: 缺少 {count}" for name, count in missing_materials.items()]
        return f"❌ **材料不足，无法炼制**:\n" + "\n".join(errors)

    # 4. [智能分配策略 v2.0]
    contribution_plan = defaultdict(lambda: defaultdict(int))
    
    # --- 策略一: 寻找能独立完成任务的 "最优解" ---
    for acc_id, inventory in accounts_inventories.items():
        if all(inventory.get(mat, 0) >= req_count for mat, req_count in required_materials.items()):
            format_and_log("TASK", "炼制规划", {'策略': '最优解', '详情': f"助手 {acc_id[-4:]} 可独立完成所有材料供应。"})
            for mat, req_count in required_materials.items():
                contribution_plan[acc_id][mat] = req_count
            return dict(contribution_plan)

    # --- 策略二: "贪心算法"，凑不齐时再进行多点协作 ---
    format_and_log("TASK", "炼制规划", {'策略': '贪心算法', '详情': "未找到可独立完成的助手，启动多点协作规划。"})
    
    # 创建一个可修改的库存副本用于规划
    temp_inventories = {acc_id: inv.copy() for acc_id, inv in accounts_inventories.items()}
    
    for material, required_count in required_materials.items():
        needed = required_count
        
        # 按当前材料的库存从多到少排序
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
                temp_inventories[acc_id][material] -= contribution # 更新临时库存
                needed -= contribution

    format_and_log("TASK", "炼制规划", {'物品': item_name, '数量': quantity, '总需求': required_materials, '最终分配方案': json.dumps(contribution_plan, indent=2)})
    return dict(contribution_plan)
