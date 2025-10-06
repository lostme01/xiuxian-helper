# -*- coding: utf-8 -*-
from app.context import get_application
from app.plugins.logic.trade_logic import publish_task
from config import settings

async def _cmd_broadcast(event, parts):
    """
    ,b <指令> - 向所有助手广播游戏指令 (. 开头)
    ,b <宗门> <指令> - 向指定宗门广播
    """
    app = get_application()
    
    if len(parts) < 2:
        await app.client.reply_to_admin(event, "❌ **广播指令格式错误**\n请提供要执行的指令。")
        return
    
    target_sect = None
    command_to_run = ""
    
    if len(parts) > 2 and not parts[1].startswith('.'):
        target_sect = parts[1]
        command_to_run = " ".join(parts[2:])
    else:
        command_to_run = " ".join(parts[1:])
        
    if not command_to_run.startswith('.'):
        await app.client.reply_to_admin(event, "❌ **广播失败**\n出于安全考虑，只能广播以 `.` 开头的游戏指令。")
        return

    task = {
        "task_type": "broadcast_command",
        "command_to_run": command_to_run
    }
    if target_sect:
        task["target_sect"] = target_sect

    if await publish_task(task):
        target_str = f"宗门 **[{target_sect}]**" if target_sect else "**所有**"
        await app.client.reply_to_admin(event, f"✅ 已向 {target_str} 助手广播指令:\n`{command_to_run}`")
    else:
        await app.client.reply_to_admin(event, "❌ **广播失败**\n无法将任务发布到 Redis。")

def initialize(app):
    app.register_command("b", _cmd_broadcast, help_text="📢 向所有 (或指定宗门) 的助手广播游戏指令。", category="协同")
