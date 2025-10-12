# -*- coding: utf-8 -*-
from telethon.errors.rpcerrorlist import MessageEditTimeExpiredError

from app.context import get_application
from app.plugins.logic import market_logic
# [重构] 导入新的UI流程管理器
from app.utils import create_error_reply, progress_manager

HELP_TEXT_CLEAR_STALL = """🧹 **一键下架**
**说明**: 查询当前账号在万宝楼上架的所有物品，并逐一发送下架指令，用于清理货摊。
**用法**: `,一键下架`
"""

async def _cmd_clear_stall(event, parts):
    """
    [重构]
    处理用户指令，调用核心逻辑并使用 progress_manager 反馈。
    """
    app = get_application()
    client = app.client

    async with progress_manager(event, "⏳ 正在查询您的货摊信息并准备清理...") as progress:
        # 异常会在 progress_manager 中被自动捕获并报告
        final_text = await market_logic.logic_clear_my_stall(client)
        await progress.update(final_text)


def initialize(app):
    app.register_command(
        name="一键下架", 
        handler=_cmd_clear_stall, 
        help_text="🧹 清理万宝楼货摊上所有物品。", 
        category="动作",
        aliases=["清理货摊"],
        usage=HELP_TEXT_CLEAR_STALL
    )
