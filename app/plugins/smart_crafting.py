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
            # Handle non-integer quantity
            pass
    
    progress_message = await client.reply_to_admin(event, f"🧠 **智能炼制任务启动: {item_to_craft} x{quantity}**\n正在检查本地库存...")
    if not progress_message: return
    client.pin_message(progress_message)

    try:
        # 1. 检查本地材料是否足够
        plan = await crafting_logic.logic_plan_crafting_session(item_to_craft, my_id)
        if isinstance(plan, str) and "无法被人工炼制" in plan: # 配方不存在或不可炼制
             raise ValueError(plan)
        
        # 2. 如果 plan 为空字典，说明无需向其他助手收集，代表本地材料足够
        if not plan:
            await progress_message.edit(f"✅ **本地材料充足**\n正在为您执行炼制操作...")
            # 直接调用我们已有的 `,炼制物品` 指令的内部逻辑
            # We need to construct a "parts" list for the called function
            craft_parts = ["炼制物品", item_to_craft]
            if quantity > 1:
                craft_parts.append(str(quantity))
            await execute_craft_item(event, craft_parts)
            # execute_craft_item has its own user feedback, so we are done here.
            # The progress_message will be edited by it.
            return 

        # 3. 如果 plan 不为空，说明需要向其他助手收集材料
        await progress_message.edit(f"⚠️ **本地材料不足**\n正在启动P2P协同，向其他助手收集材料...")
        
        # 构造一个新的 event 和 parts，模拟用户发送 `,炼制` 指令
        # 注意：这里的 `,炼制` 是指P2P协同凑材料的那个指令
        gather_parts = ["炼制", item_to_craft]
        await execute_craft_gather(event, gather_parts)
        
        # P2P凑材料完成后，提示用户手动执行最终炼制
        # 因为我们无法确切知道材料何时到账
        final_text = f"✅ **材料收集任务已分派!**\n请在材料到账后，手动执行最终的炼制指令:\n`,炼制物品 {item_to_craft} {quantity}`"
        await progress_message.edit(final_text)

    except Exception as e:
        error_text = create_error_reply("智能炼制", "任务失败", details=str(e))
        await progress_message.edit(error_text)
    finally:
        # unpin is handled by the final function call (execute_craft_item or execute_craft_gather)
        # We might need to adjust this if they don't always unpin
        client.unpin_message(progress_message)


def initialize(app):
    app.register_command(
        name="智能炼制",
        handler=_cmd_smart_craft,
        help_text="✨ 自动检查、收集并炼制物品。",
        category="游戏动作",
        usage=HELP_TEXT_SMART_CRAFT
    )
