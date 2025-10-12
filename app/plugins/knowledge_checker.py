# -*- coding: utf-8 -*-
from app.context import get_application
from .logic import knowledge_logic
from app.utils import send_paginated_message, progress_manager
from config import settings

HELP_TEXT_CHECK_KNOWLEDGE = """✨ **学习盘点**
**说明**: 由管理员账号发起，对比宗门宝库与所有其他助手的学习记录，列出每个助手尚未学习的丹方、图纸和阵法。
**用法**: `,学习盘点`
"""

async def _cmd_check_knowledge(event, parts):
    app = get_application()
    client = app.client

    if str(client.me.id) != str(settings.ADMIN_USER_ID):
        return

    async with progress_manager(event, "⏳ 正在盘点所有助手的学习进度，请稍候...") as progress:
        result_text = await knowledge_logic.logic_check_knowledge_all_accounts()
        
        # 将 progress message 作为 "prefix_message" 传给分页函数
        # send_paginated_message 会首先尝试编辑这个消息为第一页内容
        await send_paginated_message(event, result_text, prefix_message=progress.message)
        
        # 清空 final_text，防止 progress_manager 在退出时再次编辑
        await progress.update("")


def initialize(app):
    app.register_command(
        # [修改] 指令名改为4个字
        name="学习盘点", 
        handler=_cmd_check_knowledge, 
        help_text="✨ 盘点所有助手的学习进度。", 
        category="协同", 
        # [修改] 将旧名称加入别名
        aliases=["盘点"],
        usage=HELP_TEXT_CHECK_KNOWLEDGE
    )
