# -*- coding: utf-8 -*-
import json
import re

from telethon.errors.rpcerrorlist import MessageEditTimeExpiredError

from app.context import get_application
from app.plugins.logic.crafting_logic import logic_execute_crafting
from app.telegram_client import CommandTimeoutError
from app.utils import create_error_reply, progress_manager, send_paginated_message

HELP_TEXT_CRAFT_ITEM = """🛠️ **炼制物品 (带库存同步)**
**说明**: 执行炼制操作，并在成功后自动更新内部的背包缓存，实现材料的减少和成品的增加。
**用法**: `,炼制物品 <物品名称> [数量]`
**示例 1**: `,炼制物品 增元丹`
**示例 2**: `,炼制物品 增元丹 2`
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


async def _cmd_list_craftable_items(event, parts):
    """列出所有已知的可炼制物品"""
    app = get_application()
    client = app.client

    if not app.redis_db:
        await client.reply_to_admin(event, "❌ 错误: Redis 未连接。")
        return
        
    all_recipes = await app.redis_db.hgetall("crafting_recipes")
    if not all_recipes:
        await client.reply_to_admin(event, "ℹ️ 知识库中尚无任何配方。")
        return
        
    craftable_items = []
    for name, recipe_json in all_recipes.items():
        try:
            recipe = json.loads(recipe_json)
            if "error" not in recipe:
                craftable_items.append(f"- `{name}`")
        except json.JSONDecodeError:
            continue
            
    if not craftable_items:
        await client.reply_to_admin(event, "ℹ️ 知识库中尚无可炼制的物品配方。")
        return

    header = "✅ **当前知识库中所有可炼制的物品如下:**\n"
    await send_paginated_message(event, header + "\n".join(sorted(craftable_items)))


def initialize(app):
    app.register_command(
        name="炼制物品",
        handler=_cmd_craft_item,
        help_text="基础炼制指令",
        category="动作",
        aliases=["炼制"],
        usage=HELP_TEXT_CRAFT_ITEM
    )
    app.register_command(
        # [修改] 指令名改为4个字
        name="可炼列表",
        handler=_cmd_list_craftable_items,
        help_text="查看所有已知的可炼制物品",
        # [修改] 将旧名称加入别名
        aliases=["可炼制列表"],
        category="查询"
    )
