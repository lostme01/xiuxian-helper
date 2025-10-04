# -*- coding: utf-8 -*-
import re
import json
import asyncio
from telethon.errors.rpcerrorlist import MessageEditTimeExpiredError

from app.context import get_application
from app.telegram_client import CommandTimeoutError
from app.utils import create_error_reply
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

    item_name = parts[1]
    quantity = 1
    if len(parts) > 2:
        try:
            quantity = int(parts[2])
            if quantity <= 0:
                raise ValueError("数量必须为正整数")
        except ValueError:
            usage = app.commands.get('炼制物品', {}).get('usage')
            error_msg = create_error_reply("炼制物品", "数量参数无效", details="数量必须是一个正整数。", usage_text=usage)
            await client.reply_to_admin(event, error_msg)
            return
    
    command = f".炼制 {item_name}"
    if quantity > 1:
        command += f" {quantity}"

    progress_message = await client.reply_to_admin(event, f"⏳ 正在执行炼制指令: `{command}`...")
    if not progress_message: return
    client.pin_message(progress_message)

    final_text = ""
    try:
        _sent_msg, final_reply = await client.send_and_wait_for_edit(
            command, 
            initial_reply_pattern=r"你凝神静气"
        )

        if "炼制结束！" in final_reply.text and "最终获得" in final_reply.text:
            gain_match = re.search(r"最终获得【(.+?)】x\*\*(\d+)\*\*", final_reply.text)
            if not gain_match:
                raise ValueError("无法从成功回复中解析出获得的物品和数量。")
            
            gained_item, gained_quantity = gain_match.group(1), int(gain_match.group(2))

            if not app.redis_db:
                raise ConnectionError("Redis未连接，无法获取配方以计算材料消耗。")

            recipe_json = await app.redis_db.hget(CRAFTING_RECIPES_KEY, item_name)
            if not recipe_json:
                raise ValueError(f"在配方数据库中未找到“{item_name}”的配方，无法扣除材料。")
            
            recipe = json.loads(recipe_json)
            
            final_text = f"✅ **炼制成功**!\n\n**产出**:\n- `{gained_item}` x `{gained_quantity}` (已入库)\n\n"
            await inventory_manager.add_item(gained_item, gained_quantity)

            if "error" not in recipe:
                consumed_text = ["**消耗**:\n"]
                for material, count_per_unit in recipe.items():
                    if material == "修为": continue
                    total_consumed = count_per_unit * quantity
                    await inventory_manager.remove_item(material, total_consumed)
                    consumed_text.append(f"- `{material}` x `{total_consumed}` (已出库)")
                final_text += "\n".join(consumed_text)

        else:
            final_text = f"ℹ️ **炼制未成功** (库存未变动)\n\n**游戏返回**:\n`{final_reply.text}`"

    except CommandTimeoutError as e:
        final_text = create_error_reply("炼制物品", "游戏指令超时", details=str(e))
    except Exception as e:
        final_text = create_error_reply("炼制物品", "任务执行期间发生意外错误", details=str(e))
    finally:
        client.unpin_message(progress_message)
        try:
            await client._cancel_message_deletion(progress_message)
            edited_message = await progress_message.edit(final_text)
            client._schedule_message_deletion(edited_message, settings.AUTO_DELETE.get('delay_admin_command'), "炼制结果")
        except MessageEditTimeExpiredError:
            await client.reply_to_admin(event, final_text)

def initialize(app):
    app.register_command(
        name="炼制物品", handler=_cmd_craft_item, help_text="🛠️ 炼制物品并自动同步库存。", category="动作", usage=HELP_TEXT_CRAFT_ITEM
    )
