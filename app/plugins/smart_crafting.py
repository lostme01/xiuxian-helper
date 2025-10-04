# -*- coding: utf-8 -*-
import json
import asyncio
import time
import re
from telethon.errors.rpcerrorlist import MessageEditTimeExpiredError
from app.context import get_application
from app.utils import create_error_reply
from app.inventory_manager import inventory_manager
from app.plugins.logic import crafting_logic, trade_logic
from app.plugins.crafting_actions import _cmd_craft_item as execute_craft_item
# [核心修改] 导入新的、不带权限检查的内部函数
from app.plugins.crafting_material_gathering import _internal_gather_materials as execute_gather_materials

HELP_TEXT_SMART_CRAFT = """✨ **智能炼制 (全自动版)**
**说明**: 终极一键指令。自动检查材料，如果不足，则自动向其他助手收集，材料收齐后将自动执行最终的炼制操作。
**用法**: `,智能炼制 <物品名称> [数量]`
**示例**: `,智能炼制 增元丹 2`
"""

async def _cmd_smart_craft(event, parts):
    app = get_application()
    client = app.client
    my_id = str(client.me.id)
    
    if len(parts) < 2:
        await client.reply_to_admin(event, create_error_reply("智能炼制", "参数不足", usage_text=HELP_TEXT_SMART_CRAFT))
        return

    item_to_craft = ""
    quantity = 1
    if len(parts) > 2 and parts[-1].isdigit():
        try:
            quantity = int(parts[-1])
            item_to_craft = " ".join(parts[1:-1])
        except (ValueError, IndexError):
            item_to_craft = " ".join(parts[1:])
    else:
        item_to_craft = " ".join(parts[1:])

    
    progress_message = await client.reply_to_admin(event, f"🧠 **智能炼制任务启动: {item_to_craft} x{quantity}**\n正在检查本地库存...")
    if not progress_message: return
    client.pin_message(progress_message)

    try:
        # 检查本地材料是否足够
        required_materials = await crafting_logic.logic_check_local_materials(item_to_craft, quantity)
        if isinstance(required_materials, str): # 如果返回的是错误字符串
            raise ValueError(required_materials)

        if not required_materials:
            await progress_message.edit(f"✅ **本地材料充足**\n正在为您执行炼制操作...")
            # 因为材料充足，直接调用基础炼制指令
            craft_parts = ["炼制物品", item_to_craft, str(quantity)]
            await execute_craft_item(event, craft_parts)
            # execute_craft_item 会自己处理消息，这里无需再操作
            return 

        # --- 材料不足，启动全自动收集与炼制流程 ---
        await progress_message.edit(f"⚠️ **本地材料不足**\n正在启动P2P协同，向其他助手收集材料...")
        
        # [核心优化] 直接通过函数参数调用，不再拼接parts列表
        await execute_gather_materials(event, item_to_craft, quantity)
        
        # 因为 execute_gather_materials 会处理自己的进度消息，这里在它完成后追加提示
        final_text = (f"✅ **材料收集任务已分派!**\n"
                      f"⏳ 请在材料到账后，手动执行最终的炼制指令:\n"
                      f"`,炼制物品 {item_to_craft} {quantity}`")
        await progress_message.edit(final_text)


    except Exception as e:
        error_text = create_error_reply("智能炼制", "任务失败", details=str(e))
        await progress_message.edit(error_text)
    finally:
        client.unpin_message(progress_message)


def initialize(app):
    app.register_command(
        name="智能炼制", handler=_cmd_smart_craft, help_text="✨ 自动检查、收集并炼制物品。", category="协同", usage=HELP_TEXT_SMART_CRAFT
    )

