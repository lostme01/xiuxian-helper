# -*- coding: utf-8 -*-
from app.context import get_application
from .logic import knowledge_logic
from app.utils import send_paginated_message, progress_manager
from config import settings
# [核心修复] 从新的 knowledge_sharing 插件导入正确的函数
from app.plugins.knowledge_sharing import _execute_knowledge_sharing_logic

HELP_TEXT_CHECK_KNOWLEDGE = """✨ **学习盘点**
**说明**: 由管理员账号发起，对比宗门宝库与所有其他助手的学习记录，列出每个助手尚未学习的丹方、图纸和阵法。
**用法**: `,学习盘点`
"""

HELP_TEXT_KNOWLEDGE_SHARING = """🤝 **知识共享 (手动)**
**说明**: [仅限管理员] 手动触发一次“知识共享”扫描。程序会自动寻找需要配方的“学生”，并安排拥有多余配方的“老师”直接将配方交给学生。
**用法**: `,知识共享`
"""

async def _cmd_check_knowledge(event, parts):
    app = get_application()
    client = app.client

    if str(client.me.id) != str(settings.ADMIN_USER_ID):
        return

    async with progress_manager(event, "⏳ 正在盘点所有助手的学习进度，请稍候...") as progress:
        result_text = await knowledge_logic.logic_check_knowledge_all_accounts()
        
        await send_paginated_message(event, result_text, prefix_message=progress.message)
        
        await progress.update("")


async def _cmd_trigger_knowledge_sharing(event, parts):
    """[新增] 手动触发知识共享的指令处理器"""
    app = get_application()
    client = app.client

    if str(client.me.id) != str(settings.ADMIN_USER_ID):
        return
    
    async with progress_manager(event, "⏳ 正在手动触发“知识共享”扫描...") as progress:
        # [核心修复] 调用正确的函数名
        await _execute_knowledge_sharing_logic()
        await progress.update("✅ **知识共享扫描已完成。**\n\n如果发现了可共享的配方，相关教学任务已在后台分派。")


def initialize(app):
    app.register_command(
        name="学习盘点", 
        handler=_cmd_check_knowledge, 
        help_text="✨ 盘点所有助手的学习进度。", 
        category="协同", 
        aliases=["盘点"],
        usage=HELP_TEXT_CHECK_KNOWLEDGE
    )
    
    app.register_command(
        name="知识共享",
        handler=_cmd_trigger_knowledge_sharing,
        help_text="🤝 [管理员] 手动触发一次知识共享。",
        category="协同",
        aliases=["共享知识"],
        usage=HELP_TEXT_KNOWLEDGE_SHARING
    )
