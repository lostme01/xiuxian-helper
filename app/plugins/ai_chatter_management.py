# -*- coding: utf-8 -*-
from app.context import get_application
from app.utils import send_paginated_message
# 从AI聊天插件中，直接导入内存中的聊天记录变量
from app.plugins.ai_chatter import human_chat_history

HELP_TEXT_VIEW_HISTORY = """🧠 **查看AI聊天记录**
**说明**: 查看AI当前缓存在内存中的、用于学习和生成对话的最近聊天记录。
**用法**: `,查看AI聊天记录`
"""

HELP_TEXT_CLEAR_HISTORY = """🗑️ **清空AI聊天记录**
**说明**: 立即清空AI当前的所有聊天记忆。
**用法**: `,清空AI聊天记录`
"""

async def _cmd_view_chat_history(event, parts):
    """处理查看聊天记录的指令"""
    client = get_application().client
    
    if not human_chat_history:
        await client.reply_to_admin(event, "ℹ️ AI当前的聊天记录为空。")
        return

    report_lines = ["🧠 **AI 当前学习的聊天记录如下 (从旧到新):**\n"]
    for i, entry in enumerate(human_chat_history, 1):
        report_lines.append(f"`{i}. {entry}`")
    
    await send_paginated_message(event, "\n".join(report_lines))


async def _cmd_clear_chat_history(event, parts):
    """处理清空聊天记录的指令"""
    client = get_application().client
    
    human_chat_history.clear()
    
    await client.reply_to_admin(event, "✅ 已成功清空AI的所有聊天记录。")


def initialize(app):
    """初始化指令"""
    app.register_command(
        name="查看AI聊天记录",
        handler=_cmd_view_chat_history,
        help_text="🧠 查看AI当前学习的聊天记录。",
        category="系统",
        usage=HELP_TEXT_VIEW_HISTORY
    )
    app.register_command(
        name="清空AI聊天记录",
        handler=_cmd_clear_chat_history,
        help_text="🗑️ 清空AI的聊天记忆。",
        category="系统",
        usage=HELP_TEXT_CLEAR_HISTORY
    )
