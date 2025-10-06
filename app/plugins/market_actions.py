# -*- coding: utf-8 -*-
from telethon.errors.rpcerrorlist import MessageEditTimeExpiredError
from app.context import get_application
from app.plugins.logic import market_logic
from app.utils import create_error_reply

HELP_TEXT_CLEAR_STALL = """🧹 **一键下架**
**说明**: 查询当前账号在万宝楼上架的所有物品，并逐一发送下架指令，用于清理货摊。
**用法**: `,一键下架`
"""

async def _cmd_clear_stall(event, parts):
    """处理用户指令，调用核心逻辑并向用户反馈。"""
    app = get_application()
    client = app.client

    progress_message = await client.reply_to_admin(event, "⏳ 正在查询您的货摊信息并准备清理...")
    if not progress_message: return
    client.pin_message(progress_message)

    final_text = ""
    try:
        final_text = await market_logic.logic_clear_my_stall(client)
    except Exception as e:
        final_text = create_error_reply("一键下架", "执行时发生未知异常", details=str(e))
    finally:
        client.unpin_message(progress_message)
        try:
            await client._cancel_message_deletion(progress_message)
            await progress_message.edit(final_text)
        except MessageEditTimeExpiredError:
            await client.reply_to_admin(event, final_text)

def initialize(app):
    app.register_command(
        name="一键下架", 
        handler=_cmd_clear_stall, 
        help_text="🧹 清理万宝楼货摊上所有物品。", 
        category="动作",
        aliases=["清理货摊"],
        usage=HELP_TEXT_CLEAR_STALL
    )
