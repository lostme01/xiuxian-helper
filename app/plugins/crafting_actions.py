# -*- coding: utf-8 -*-
import json
import re

from telethon.errors.rpcerrorlist import MessageEditTimeExpiredError

from app.context import get_application
from app.plugins.logic.crafting_logic import logic_execute_crafting
from app.telegram_client import CommandTimeoutError
from app.utils import create_error_reply, progress_manager, send_paginated_message

HELP_TEXT_CRAFT_ITEM = """🛠️ **炼制物品 (带库存同步)**
**说明**: 执行炼制操作。如果配方未学习，会自动尝试学习。
**用法**: `,炼制物品 <物品名称> [数量]`
**示例**: 
  `,炼制物品 增元丹`
  `,炼制物品 增元丹 2`
"""

async def _cmd_craft_item(event, parts):
    app = get_application()
    client = app.client
    
    if len(parts) < 2:
        usage = app.commands.get('炼制物品', {}).get('usage')
        error_msg = create_error_reply("炼制物品", "参数不足", usage_text=usage)
        await client.reply_to_admin(event, error_msg)
        return

    item_name = ""
    quantity = 1
    if len(parts) > 2 and parts[-1].isdigit():
        quantity = int(parts[-1])
        item_name = " ".join(parts[1:-1])
    else:
        item_name = " ".join(parts[1:])
    
    async with progress_manager(event, f"⏳ 正在准备炼制任务: `{item_name} x{quantity}`...") as progress:
        async def feedback_handler(text):
            await progress.update(text)
        
        await logic_execute_crafting(item_name, quantity, feedback_handler)

def initialize(app):
    app.register_command(
        name="炼制物品",
        handler=_cmd_craft_item,
        help_text="🛠️ 自动学习并炼制物品。",
        category="动作",
        aliases=["炼制"],
        usage=HELP_TEXT_CRAFT_ITEM
    )
