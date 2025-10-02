# -*- coding: utf-8 -*-
from app.context import get_application
from .logic import gamestate_logic
from app.utils import require_args

HELP_TEXT_RESET_TASK = """⏳ **重置任务状态**
**说明**: 清除任务的冷却记录，使其可重新执行。
**用法**: `,重置任务 <任务名>`
**可用**: `biguan`, `dianmao`, `chuangta`, `yindao`"""

@require_args(count=2, usage=HELP_TEXT_RESET_TASK)
async def _cmd_reset_task(event, parts):
    await get_application().client.reply_to_admin(event, await gamestate_logic.logic_reset_task_state(parts[1]))

def initialize(app):
    app.register_command(
        name="重置任务",
        handler=_cmd_reset_task,
        help_text="⏳ 重置任务冷却",
        category="游戏管理",
        usage=HELP_TEXT_RESET_TASK
    )
