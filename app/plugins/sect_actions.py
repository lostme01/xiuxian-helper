# -*- coding: utf-8 -*-
import re
from telethon.errors.rpcerrorlist import MessageEditTimeExpiredError

from app.context import get_application
from app.telegram_client import CommandTimeoutError
from app.utils import create_error_reply
from app.inventory_manager import inventory_manager

HELP_TEXT_EXCHANGE_ITEM = """🔄 **宗门兑换 (带库存同步)**
**说明**: 执行宗门宝库的兑换操作，并在成功后自动将获得的物品添加到内部背包缓存。
**用法**: `,兑换 <物品名称> [数量]`
**示例 1**: `,兑换 凝血草种子`
**示例 2**: `,兑换 凝血草种子 10`
"""

async def _cmd_exchange_item(event, parts):
    app = get_application()
    client = app.client

    if len(parts) < 2:
        usage = app.commands.get('兑换', {}).get('usage')
        error_msg = create_error_reply("兑换", "参数不足", usage_text=usage)
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
            usage = app.commands.get('兑换', {}).get('usage')
            error_msg = create_error_reply("兑换", "数量参数无效", details="数量必须是一个正整数。", usage_text=usage)
            await client.reply_to_admin(event, error_msg)
            return

    command = f".兑换 {item_name}"
    if quantity > 1:
        command += f" {quantity}"
        
    progress_message = await client.reply_to_admin(event, f"⏳ 正在执行兑换指令: `{command}`...")
    if not progress_message: return
    client.pin_message(progress_message)

    final_text = ""
    try:
        _sent, reply = await client.send_game_command_request_response(command)

        if "**兑换成功！**" in reply.text:
            gain_match = re.search(r"获得了【(.+?)】x([\d,]+)", reply.text)
            if gain_match:
                gained_item, gained_quantity_str = gain_match.groups()
                gained_quantity = int(gained_quantity_str.replace(',', ''))
                
                await inventory_manager.add_item(gained_item, gained_quantity)
                
                final_text = f"✅ **兑换成功**!\n\n**获得**: `{gained_item}` x `{gained_quantity}` (已实时入库)"
            else:
                final_text = f"⚠️ **兑换成功但解析失败**\n库存未更新，请使用 `,立即刷新背包` 进行校准。\n\n**游戏返回**:\n`{reply.text}`"
        
        elif "贡献不足" in reply.text:
            final_text = f"ℹ️ **兑换失败**: 宗门贡献不足。\n\n**游戏返回**:\n`{reply.text}`"
        
        else:
            final_text = f"❓ **兑换失败**: 收到未知回复。\n\n**游戏返回**:\n`{reply.text}`"

    except CommandTimeoutError as e:
        final_text = create_error_reply("兑换", "游戏指令超时", details=str(e))
    except Exception as e:
        final_text = create_error_reply("兑换", "任务执行期间发生意外错误", details=str(e))
    finally:
        client.unpin_message(progress_message)
        try:
            await client._cancel_message_deletion(progress_message)
            edited_message = await progress_message.edit(final_text)
            client._schedule_message_deletion(edited_message, 30, "兑换结果")
        except MessageEditTimeExpiredError:
            await client.reply_to_admin(event, final_text)


def initialize(app):
    app.register_command(
        name="兑换",
        handler=_cmd_exchange_item,
        help_text="🔄 从宗门宝库兑换物品并同步库存。",
        category="游戏动作",
        usage=HELP_TEXT_EXCHANGE_ITEM
    )
