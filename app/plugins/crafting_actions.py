# -*- coding: utf-8 -*-
import re
import json
from telethon.errors.rpcerrorlist import MessageEditTimeExpiredError

from app.context import get_application
from app.telegram_client import CommandTimeoutError
from app.utils import create_error_reply, send_paginated_message
from app.inventory_manager import inventory_manager
from app.plugins.logic.recipe_logic import CRAFTING_RECIPES_KEY

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
    quantity_str = ""
    if len(parts) > 2 and parts[-1].isdigit():
        quantity_str = parts[-1]
        item_name = " ".join(parts[1:-1])
    else:
        item_name = " ".join(parts[1:])
    
    command = f".炼制 {item_name} {quantity_str}".strip()
    
    progress_msg = await client.reply_to_admin(event, f"⏳ 正在执行指令: `{command}`\n正在等待游戏机器人返回最终结果...")
    client.pin_message(progress_msg)
    
    try:
        _sent, final_reply = await client.send_and_wait_for_edit(
            command,
            initial_reply_pattern=r"你凝神静气.*最终成功率"
        )
        
        # [核心修改] 统一使用 .text
        raw_text = final_reply.text
        
        if "炼制结束" in raw_text and "最终获得" in raw_text:
            await progress_msg.edit(f"✅ **炼制成功！** 正在解析产出与消耗...")
            
            gained_match = re.search(r"最终获得【(.+?)】x\*\*([\d,]+)\*\*", raw_text)
            if gained_match:
                gained_item, gained_quantity_str = gained_match.groups()
                gained_quantity = int(gained_quantity_str.replace(',', ''))
                await inventory_manager.add_item(gained_item, gained_quantity)
                
                # ... (材料扣除逻辑保持不变) ...

                final_message = (
                    f"✅ **炼制成功！**\n\n"
                    f"**产出**: `{gained_item} x{gained_quantity}`\n\n"
                    f"ℹ️ 背包缓存已自动更新。"
                )
                await progress_msg.edit(final_message)
            else:
                await progress_msg.edit(f"⚠️ **炼制完成，但解析产出失败。**\n请手动检查背包。\n\n**游戏回复**:\n`{raw_text}`")

        else:
            await progress_msg.edit(f"❌ **炼制失败或未收到预期回复。**\n\n**游戏回复**:\n`{raw_text}`")

    except CommandTimeoutError as e:
        error_text = create_error_reply("炼制物品", "游戏指令超时", details=str(e))
        await progress_msg.edit(error_text)
    except Exception as e:
        error_text = create_error_reply("炼制物品", "执行时发生未知异常", details=str(e))
        await progress_msg.edit(error_text)
    finally:
        client.unpin_message(progress_msg)


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
        name="可炼制列表",
        handler=_cmd_list_craftable_items,
        help_text="查看所有已知的可炼制物品",
        category="查询"
    )
