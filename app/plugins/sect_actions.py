# -*- coding: utf-8 -*-
import re

from telethon.errors.rpcerrorlist import MessageEditTimeExpiredError

from app import game_adaptor
from app.context import get_application
from app.telegram_client import CommandTimeoutError
# [重构] 导入新的UI流程管理器
from app.utils import create_error_reply, parse_item_and_quantity, progress_manager

HELP_TEXT_EXCHANGE_ITEM = """🔄 **宗门兑换 (事件驱动)**
**说明**: 执行宗门宝库的兑换操作。成功后，系统将通过监听游戏事件自动更新库存和贡献。
**用法**: `,兑换 <物品名称> [数量]`
**示例**: `,兑换 凝血草种子 10`
"""

HELP_TEXT_DONATE_ITEM = """💸 **宗门捐献 (事件驱动)**
**说明**: 执行宗门捐献操作。成功后，系统将通过监听游戏事件自动更新库存和贡献。
**用法**: `,捐献 <物品名称> <数量>`
**示例**: `,捐献 凝血草 10`
"""

async def _cmd_exchange_item(event, parts):
    app = get_application()
    client = app.client
    usage = app.commands.get('兑换', {}).get('usage')

    item_name, quantity, error = parse_item_and_quantity(parts)
    if error:
        error_msg = create_error_reply("兑换", error, usage_text=usage)
        await client.reply_to_admin(event, error_msg)
        return

    command = game_adaptor.sect_exchange(item_name, quantity)
    
    # [重构] 使用 progress_manager
    async with progress_manager(event, f"⏳ 正在执行兑换指令: `{command}`...") as progress:
        final_text = ""
        try:
            _sent, reply = await client.send_game_command_request_response(command)

            if "**兑换成功！**" in reply.text:
                final_text = f"✅ **兑换指令已发送**!\n系统将通过事件监听器自动更新状态。"
            elif "贡献不足" in reply.text:
                final_text = f"ℹ️ **兑换失败**: 宗门贡献不足。"
            else:
                final_text = f"❓ **兑换失败**: 收到未知回复。\n\n**游戏返回**:\n`{reply.text}`"
        except CommandTimeoutError as e:
            final_text = create_error_reply("兑换", "游戏指令超时", details=str(e))
        
        await progress.update(final_text)


async def _cmd_donate_item(event, parts):
    app = get_application()
    client = app.client
    usage = app.commands.get('捐献', {}).get('usage')

    if len(parts) < 3:
        error_msg = create_error_reply("捐献", "参数不足", usage_text=usage)
        await client.reply_to_admin(event, error_msg)
        return

    item_name = " ".join(parts[1:-1])
    try:
        quantity = int(parts[-1])
        if quantity <= 0:
            raise ValueError("数量必须为正整数")
    except (ValueError, IndexError):
        error_msg = create_error_reply("捐献", "数量参数无效", details="数量必须是一个正整数。", usage_text=usage)
        await client.reply_to_admin(event, error_msg)
        return
        
    if not item_name:
        error_msg = create_error_reply("捐献", "物品名称不能为空", usage_text=usage)
        await client.reply_to_admin(event, error_msg)
        return

    command = game_adaptor.sect_donate(item_name, quantity)
        
    # [重构] 使用 progress_manager
    async with progress_manager(event, f"⏳ 正在执行捐献指令: `{command}`...") as progress:
        final_text = ""
        try:
            _sent, reply = await client.send_game_command_request_response(command)

            if "你向宗门捐献了" in reply.text:
                final_text = f"✅ **捐献指令已发送**!\n系统将通过事件监听器自动更新状态。"
            elif "数量不足" in reply.text or "并无价值" in reply.text:
                final_text = f"ℹ️ **捐献失败** (状态未变动)\n\n**游戏返回**:\n`{reply.text}`"
            else:
                final_text = f"❓ **捐献失败**: 收到未知回复。\n\n**游戏返回**:\n`{reply.text}`"

        except CommandTimeoutError as e:
            final_text = create_error_reply("捐献", "游戏指令超时", details=str(e))
        
        await progress.update(final_text)

def initialize(app):
    app.register_command(
        name="兑换", handler=_cmd_exchange_item, help_text="🔄 从宗门宝库兑换物品并同步库存。", category="动作", usage=HELP_TEXT_EXCHANGE_ITEM
    )
    app.register_command(
        name="捐献", handler=_cmd_donate_item, help_text="💸 向宗门捐献物品并同步库存与贡献。", category="动作", usage=HELP_TEXT_DONATE_ITEM
    )
