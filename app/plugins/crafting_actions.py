# -*- coding: utf-8 -*-
import re
from app.context import get_application
from .logic import crafting_logic
from app.telegram_client import CommandTimeoutError
from app.utils import create_error_reply, send_paginated_message
from app.inventory_manager import inventory_manager

HELP_TEXT_CRAFT_ITEM = """🛠️ **炼制物品**
**说明**: 这是最基础的炼制指令，它会等待游戏机器人返回最终的炼制结果，并自动更新内部的背包缓存。
**用法**: `,炼制物品 <物品名称> [数量]`
**别名**: `,炼制`
**示例**: `,炼制物品 增元丹 10`
"""

async def _cmd_craft_item(event, parts):
    """
    [最终修复版]
    使用 send_and_wait_for_edit 函数，精确处理游戏机器人“先回复再编辑”的行为。
    """
    app = get_application()
    client = app.client
    
    if len(parts) < 2:
        await client.reply_to_admin(event, create_error_reply("炼制物品", "参数不足", usage=HELP_TEXT_CRAFT_ITEM))
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
        # [核心修复] 使用等待编辑的函数，并提供精确的初始回复模板
        _sent, final_reply = await client.send_and_wait_for_edit(
            command,
            initial_reply_pattern=r"你凝神静气.*最终成功率"
        )
        
        raw_text = final_reply.raw_text
        
        if "炼制结束" in raw_text and "最终获得" in raw_text:
            await progress_msg.edit(f"✅ **炼制成功！** 正在解析产出与消耗...")
            
            # 解析产出
            gained_match = re.search(r"最终获得【(.+?)】x\*\*([\d,]+)\*\*", raw_text)
            if gained_match:
                gained_item, gained_quantity_str = gained_match.groups()
                gained_quantity = int(gained_quantity_str.replace(',', ''))
                await inventory_manager.add_item(gained_item, gained_quantity)
                
                # 解析消耗
                # 注意：游戏机器人的回复中没有消耗信息，我们需要从配方反推
                # 这是一个简化的逻辑，假设使用的是第一个配方
                recipe_json = await app.redis_db.hget("crafting_recipes", gained_item)
                if recipe_json:
                    try:
                        recipe = json.loads(recipe_json)
                        # 假设我们总是按最终产出/配方产出的比例来扣除材料
                        # 例如配方是10个草 -> 10个丹，最终产出13个丹，则消耗13个草
                        # 这是一个复杂的逻辑，我们先做一个简化版：按指令数量扣除
                        required = await crafting_logic.logic_check_local_materials(item_name, int(quantity_str) if quantity_str else 1)
                        if isinstance(required, dict) and required:
                             for mat, count in required.items():
                                 await inventory_manager.remove_item(mat, count)

                    except Exception as e:
                        await client.send_admin_notification(f"⚠️ **自动扣除材料失败**: 解析配方时出错: {e}")

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

