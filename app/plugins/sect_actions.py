# -*- coding: utf-8 -*-
import re
from telethon.errors.rpcerrorlist import MessageEditTimeExpiredError

from app.context import get_application
from app.telegram_client import CommandTimeoutError
from app.utils import create_error_reply
from app.inventory_manager import inventory_manager
from app.character_stats_manager import stats_manager

HELP_TEXT_EXCHANGE_ITEM = """🔄 **宗门兑换 (带库存同步)**
**说明**: 执行宗门宝库的兑换操作，并在成功后自动将获得的物品添加到内部背包缓存。
**用法**: `,兑换 <物品名称> [数量]`
**示例 1**: `,兑换 凝血草种子`
**示例 2**: `,兑换 凝血草种子 10`
"""

HELP_TEXT_DONATE_ITEM = """💸 **宗门捐献 (带库存同步)**
**说明**: 执行宗门捐献操作，并在成功后自动扣减背包物品、增加宗门贡献。
**用法**: `,捐献 <物品名称> <数量>`
**示例**: `,捐献 凝血草 10`
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
            cost_match = re.search(r"消耗了 \*\*([\d,]+)\*\* 点贡献", reply.text) # [逻辑修复] 匹配消耗的贡献

            if gain_match and cost_match:
                gained_item, gained_quantity_str = gain_match.groups()
                gained_quantity = int(gained_quantity_str.replace(',', ''))
                cost = int(cost_match.group(1).replace(',', ''))
                
                # [逻辑修复] 同时更新物品和贡献
                await inventory_manager.add_item(gained_item, gained_quantity)
                await stats_manager.remove_contribution(cost)
                
                final_text = f"✅ **兑换成功**!\n\n- **获得**: `{gained_item}` x `{gained_quantity}` (已入库)\n- **消耗**: `{cost}` 点宗门贡献 (已扣除)"
            else:
                final_text = f"⚠️ **兑换成功但解析失败**\n状态未更新，请使用 `,宗门宝库` 进行校准。\n\n**游戏返回**:\n`{reply.text}`"
        
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
            await progress_message.edit(final_text)
        except MessageEditTimeExpiredError:
            await client.reply_to_admin(event, final_text)

async def _cmd_donate_item(event, parts):
    app = get_application()
    client = app.client

    if len(parts) < 3:
        usage = app.commands.get('捐献', {}).get('usage')
        error_msg = create_error_reply("捐献", "参数不足", usage_text=usage)
        await client.reply_to_admin(event, error_msg)
        return

    item_name = parts[1]
    try:
        quantity = int(parts[2])
        if quantity <= 0:
            raise ValueError("数量必须为正整数")
    except ValueError:
        usage = app.commands.get('捐献', {}).get('usage')
        error_msg = create_error_reply("捐献", "数量参数无效", details="数量必须是一个正整数。", usage_text=usage)
        await client.reply_to_admin(event, error_msg)
        return

    command = f".宗门捐献 {item_name} {quantity}"
        
    progress_message = await client.reply_to_admin(event, f"⏳ 正在执行捐献指令: `{command}`...")
    if not progress_message: return
    client.pin_message(progress_message)

    final_text = ""
    try:
        _sent, reply = await client.send_game_command_request_response(command)

        if "你向宗门捐献了" in reply.text:
            consumed_match = re.search(r"捐献了 \*\*【(.+?)】\*\*x([\d,]+)", reply.text)
            contrib_match = re.search(r"获得了 \*\*([\d,]+)\*\* 点宗门贡献", reply.text)

            if consumed_match and contrib_match:
                consumed_item, consumed_quantity_str = consumed_match.groups()
                consumed_quantity = int(consumed_quantity_str.replace(',', ''))
                gained_contrib = int(contrib_match.group(1).replace(',', ''))
                
                await inventory_manager.remove_item(consumed_item, consumed_quantity)
                await stats_manager.add_contribution(gained_contrib)
                
                final_text = f"✅ **捐献成功**!\n\n- **消耗**: `{consumed_item}` x `{consumed_quantity}` (已出库)\n- **获得**: `{gained_contrib}` 点宗门贡献"
            else:
                final_text = f"⚠️ **捐献成功但解析失败**\n状态未更新，请使用 `,立即刷新背包` 校准。\n\n**游戏返回**:\n`{reply.text}`"
        
        elif "数量不足" in reply.text or "并无价值" in reply.text:
            final_text = f"ℹ️ **捐献失败** (状态未变动)\n\n**游戏返回**:\n`{reply.text}`"
        
        else:
            final_text = f"❓ **捐献失败**: 收到未知回复。\n\n**游戏返回**:\n`{reply.text}`"

    except CommandTimeoutError as e:
        final_text = create_error_reply("捐献", "游戏指令超时", details=str(e))
    except Exception as e:
        final_text = create_error_reply("捐献", "任务执行期间发生意外错误", details=str(e))
    finally:
        client.unpin_message(progress_message)
        try:
            await client._cancel_message_deletion(progress_message)
            await progress_message.edit(final_text)
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
    app.register_command(
        name="捐献",
        handler=_cmd_donate_item,
        help_text="💸 向宗门捐献物品并同步库存与贡献。",
        category="游戏动作",
        usage=HELP_TEXT_DONATE_ITEM
    )
