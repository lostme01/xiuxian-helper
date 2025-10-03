# -*- coding: utf-8 -*-
from app.context import get_application
from .logic import gamestate_logic
from app.utils import require_args

# --- 核心修改：更新帮助文本 ---
HELP_TEXT_RESET_TASK = """⏳ **重置任务冷却状态**
**说明**: 清除指定任务的冷却时间记录或状态，使其可以立即（通过手动指令）或在下次调度周期中重新执行。
**用法**: `,重置任务 <任务名>`
**可用任务名**:
  `biguan` (闭关), `dianmao` (点卯), `chuangta` (闯塔), `yindao` (引道)"""

@require_args(count=2, usage=HELP_TEXT_RESET_TASK)
async def _cmd_reset_task(event, parts):
    await get_application().client.reply_to_admin(event, await gamestate_logic.logic_reset_task_state(parts[1]))

def initialize(app):
    app.register_command(
        name="重置任务",
        handler=_cmd_reset_task,
        help_text="⏳ 重置任务冷却状态。",
        category="游戏管理",
        usage=HELP_TEXT_RESET_TASK
    )
