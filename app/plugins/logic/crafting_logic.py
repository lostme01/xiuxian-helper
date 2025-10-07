# -*- coding: utf-8 -*-
import json
import re
from collections import defaultdict
from app.context import get_application
from app.logger import format_and_log
from app.inventory_manager import inventory_manager
from app.telegram_client import CommandTimeoutError
from app.utils import create_error_reply
from app import game_adaptor
from app.data_manager import data_manager

CRAFTING_RECIPES_KEY = "crafting_recipes"

async def logic_execute_crafting(item_name: str, quantity: int, feedback_handler):
    """
    核心炼制逻辑，使用混合模式等待最终结果。
    """
    app = get_application()
    client = app.client
    
    command = game_adaptor.craft_item(item_name, quantity)
    
    await feedback_handler(f"⏳ 正在执行指令: `{command}`\n正在等待游戏机器人返回最终结果...")
    
    try:
        # [FIX] 修正错误的函数调用，应使用公开的 send_and_wait_for_edit 方法
        _sent, final_reply = await client.send_and_wait_for_edit(
            command=command,
            final_pattern=r"炼制结束",
            initial_pattern=r"你凝神静气"
        )
        
        raw_text = final_reply.text
        
        if "炼制结束" in raw_text and "最终获得" in raw_text:
            await feedback_handler(f"✅ **炼制指令已成功**!\n系统将通过事件监听器自动更新库存。")
        else:
            await feedback_handler(f"❌ **炼制失败或未收到预期回复。**\n\n**游戏回复**:\n`{raw_text}`")

    except CommandTimeoutError as e:
        error_text = create_error_reply("炼制物品", "游戏指令超时", details=str(e))
        await feedback_handler(error_text)
    except Exception as e:
        error_text = create_error_reply("炼制物品", "执行时发生未知异常", details=str(e))
        await feedback_handler(error_text)

async def logic_check_local_materials(item_name: str, quantity: int = 1) -> dict | str:
    if not data_manager.db:
        return "❌ 错误: Redis 未连接。"
    
    recipe_json = await data_manager.db.hget(CRAFTING_RECIPES_KEY, item_name)
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
    if not data_manager.db:
        return "❌ 错误: Redis 未连接。"

    recipe_json = await data_manager.db.hget(CRAFTING_RECIPES_KEY, item_name)
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

    accounts_inventories = {}
    total_network_inventory = defaultdict(int)
    
    keys_found = await data_manager.get_all_assistant_keys()
    for key in keys_found:
        account_id = key.split(':')[-1]
        if account_id == initiator_id:
            continue
            
        inventory_json = await data_manager.db.hget(key, "inventory")
        if inventory_json:
            try:
                inventory = json.loads(inventory_json)
                accounts_inventories[account_id] = inventory
                for material, count in inventory.items():
                    total_network_inventory[material] += count
            except json.JSONDecodeError:
                continue

    missing_materials = {mat: req_count - total_network_inventory[mat] for mat, req_count in required_materials.items() if total_network_inventory[mat] < req_count}
    if missing_materials:
        errors = [f"- `{name}`: 缺少 {count}" for name, count in missing_materials.items()]
        return f"❌ **材料不足，无法炼制**:\n" + "\n".join(errors)

    contribution_plan = defaultdict(lambda: defaultdict(int))
    
    for acc_id, inventory in accounts_inventories.items():
        if all(inventory.get(mat, 0) >= req_count for mat, req_count in required_materials.items()):
            for mat, req_count in required_materials.items():
                contribution_plan[acc_id][mat] = req_count
            return dict(contribution_plan)

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
