# -*- coding: utf-8 -*-
import asyncio
import re
from telethon import events

from config import settings
from app.context import get_application
from app.logger import format_and_log
from app.plugins.logic.trade_logic import publish_task

async def _handle_broadcast_command(event):
    """
    [修改版] 处理全局广播和宗门广播指令。
    """
    app = get_application()
    client = app.client
    
    if event.sender_id != settings.ADMIN_USER_ID:
        return

    command_text = event.text.strip()
    
    # 使用正则表达式匹配指令格式
    match = re.match(r"\*(all|[\u4e00-\u9fa5]+)\s+(.+)", command_text)
    if not match:
        return

    target_group, command_to_run = match.groups()
    
    if not command_to_run:
        await client.reply_to_admin(event, "❌ **广播指令错误**: 未指定要执行的命令。")
        return

    for prefix in settings.COMMAND_PREFIXES:
        if command_to_run.startswith(prefix):
            await client.reply_to_admin(event, f"❌ **广播安全中止**\n检测到您试图广播一个脚本指令 (`{command_to_run}`)，该操作已被禁止。")
            format_and_log("WARNING", "广播安全中止", {'指令': command_to_run, '原因': '尝试广播脚本指令'})
            return

    task = {
        "task_type": "broadcast_command",
        "command_to_run": command_to_run
    }
    
    # 如果不是 *all，则为宗门广播
    if target_group != "all":
        task["target_sect"] = target_group

    log_context = {'指令': command_to_run, '目标': target_group}
    format_and_log("TASK", "广播指令-发布", log_context)
    
    if await publish_task(task):
        await client.reply_to_admin(event, f"✅ **广播指令已发布** (目标: `{target_group}`): 所有匹配的助手将执行 `{command_to_run}`。")
    else:
        await client.reply_to_admin(event, f"❌ **广播指令发布失败**: 无法连接到 Redis，请检查服务状态。")


def initialize(app):
    """
    初始化广播指令监听器。
    """
    client = app.client
    
    if not settings.CONTROL_GROUP_ID:
        return

    @client.client.on(events.NewMessage(chats=[settings.CONTROL_GROUP_ID]))
    async def broadcast_handler(event):
        if event.sender_id == settings.ADMIN_USER_ID:
            await _handle_broadcast_command(event)

