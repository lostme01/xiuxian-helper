# -*- coding: utf-8 -*-
from app.context import get_application
from .logic import knowledge_logic
from app.utils import send_paginated_message
from config import settings

HELP_TEXT_CHECK_KNOWLEDGE = """✨ **盘点学习进度**
**说明**: 由管理员账号发起，对比宗门宝库与所有其他助手的学习记录，列出每个助手尚未学习的丹方、图纸和阵法。
**用法**: `,盘点`
"""

async def _cmd_check_knowledge(event, parts):
    app = get_application()
    client = app.client

    if str(client.me.id) != str(settings.ADMIN_USER_ID):
        return

    progress_msg = await client.reply_to_admin(event, "⏳ 正在盘点所有助手的学习进度，请稍候...")
    
    result_text = await knowledge_logic.logic_check_knowledge_all_accounts()
    
    await send_paginated_message(event, result_text, prefix_message=progress_msg)


def initialize(app):
    app.register_command(
        name="盘点", handler=_cmd_check_knowledge, help_text="✨ 盘点所有助手的学习进度。", category="协同", usage=HELP_TEXT_CHECK_KNOWLEDGE
    )
