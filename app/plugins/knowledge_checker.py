# -*- coding: utf-8 -*-
from app.context import get_application
from .logic import knowledge_logic
from app.utils import send_paginated_message, progress_manager
from config import settings
# [新增] 导入知识共享的核心逻辑函数
from app.plugins.auto_management import _execute_knowledge_sharing

HELP_TEXT_CHECK_KNOWLEDGE = """✨ **学习盘点**
**说明**: 由管理员账号发起，对比宗门宝库与所有其他助手的学习记录，列出每个助手尚未学习的丹方、图纸和阵法。
**用法**: `,学习盘点`
"""

HELP_TEXT_KNOWLEDGE_SHARING = """🤝 **知识共享 (手动)**
**说明**: [仅限管理员] 手动触发一次“知识共享”扫描。程序会自动寻找拥有多余丹方/图纸的“老师”，并安排“学生”进行学习。
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

    # 确保只有管理员可以执行
    if str(client.me.id) != str(settings.ADMIN_USER_ID):
        return
    
    async with progress_manager(event, "⏳ 正在手动触发“知识共享”扫描...") as progress:
        # 直接调用后台任务的核心逻辑
        await _execute_knowledge_sharing()
        await progress.update("✅ **知识共享扫描已完成。**\n\n如果发现了可共享的配方，相关任务已在后台分派。")


def initialize(app):
    app.register_command(
        name="学习盘点", 
        handler=_cmd_check_knowledge, 
        help_text="✨ 盘点所有助手的学习进度。", 
        category="协同", 
        aliases=["盘点"],
        usage=HELP_TEXT_CHECK_KNOWLEDGE
    )
    
    # [新增] 注册新的手动触发指令
    app.register_command(
        name="知识共享",
        handler=_cmd_trigger_knowledge_sharing,
        help_text="🤝 [管理员] 手动触发一次知识共享扫描。",
        category="协同",
        aliases=["共享知识"],
        usage=HELP_TEXT_KNOWLEDGE_SHARING
    )
