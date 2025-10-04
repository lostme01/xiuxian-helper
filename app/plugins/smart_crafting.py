# -*- coding: utf-8 -*-
import json
from telethon.errors.rpcerrorlist import MessageEditTimeExpiredError
from app.context import get_application
from app.utils import create_error_reply
from app.inventory_manager import inventory_manager
from app.plugins.logic import crafting_logic, trade_logic
from app.plugins.crafting_actions import _cmd_craft_item as execute_craft_item
from app.plugins.crafting_coordinator import _cmd_craft_gather as execute_craft_gather

HELP_TEXT_SMART_CRAFT = """✨ **智能炼制 (最终版)**
**说明**: 终极一键指令。自动检查材料，如果足够则直接炼制；如果不足，则自动向其他助手收集材料，并在收集完成后再进行炼制。
**用法**: `,智能炼制 <物品名称> [数量]`
**示例**: `,智能炼制 增元丹 2`
"""

async def _cmd_smart_craft(event, parts):
    app = get_application()
    client = app.client
    my_id = str(client.me.id)
    
    if len(parts) < 2:
        usage = app.commands.get('智能炼制', {}).get('usage')
        error_msg = create_error_reply("智能炼制", "参数不足", usage_text=usage)
        await client.reply_to_admin(event, error_msg)
        return

    item_to_craft = parts[1]
    quantity = 1
    if len(parts) > 2:
        try:
            quantity = int(parts[2])
        except ValueError:
            pass
    
    progress_message = await client.reply_to_admin(event, f"🧠 **智能炼制任务启动: {item_to_craft} x{quantity}**\n正在检查本地库存...")
    if not progress_message: return
    client.pin_message(progress_message)

    try:
        plan = await crafting_logic.logic_plan_crafting_session(item_to_craft, my_id)
        if isinstance(plan, str) and "无法被人工炼制" in plan:
             raise ValueError(plan)
        
        if not plan:
            await progress_message.edit(f"✅ **本地材料充足**\n正在为您执行炼制操作...")
            craft_parts = ["炼制物品", item_to_craft]
            if quantity > 1:
                craft_parts.append(str(quantity))
            await execute_craft_item(event, craft_parts)
            return 

        await progress_message.edit(f"⚠️ **本地材料不足**\n正在启动P2P协同，向其他助手收集材料...")
        
        gather_parts = ["炼制", item_to_craft]
        await execute_craft_gather(event, gather_parts)
        
        final_text = f"✅ **材料收集任务已分派!**\n请在材料到账后，手动执行最终的炼制指令:\n`,炼制物品 {item_to_craft} {quantity}`"
        await progress_message.edit(final_text)

    except Exception as e:
        error_text = create_error_reply("智能炼制", "任务失败", details=str(e))
        await progress_message.edit(error_text)
    finally:
        client.unpin_message(progress_message)


def initialize(app):
    app.register_command(
        name="智能炼制", handler=_cmd_smart_craft, help_text="✨ 自动检查、收集并炼制物品。", category="动作", usage=HELP_TEXT_SMART_CRAFT
    )
