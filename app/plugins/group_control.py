# -*- coding: utf-8 -*-
import shlex
import logging
from telethon import events

from config import settings
from app.context import get_application
from app.logger import format_and_log

async def _handle_help_command(event, parts):
    app = get_application()
    client = app.client
    prefix = settings.COMMAND_PREFIXES[0]
    
    if len(parts) > 1:
        cmd_name_to_find = parts[1]
        command_info = app.commands.get(cmd_name_to_find.lower())
        if command_info:
            usage_text = command_info.get('usage', '该指令没有提供详细的帮助信息。')
            await client.reply_to_admin(event, f"📄 **指令帮助: {prefix}{cmd_name_to_find}**\n\n{usage_text}")
        else:
            await client.reply_to_admin(event, f"❓ 未找到指令: `{cmd_name_to_find}`")
        return

    categorized_cmds = {}
    unique_cmds = {}
    for name, data in app.commands.items():
        if data.get('handler') is None:
            continue
        handler = data['handler']
        if handler not in unique_cmds:
            unique_cmds[handler] = {"name": name, "category": data.get("category", "默认")}
    
    for cmd_info in unique_cmds.values():
        category = cmd_info["category"]
        if category not in categorized_cmds:
            categorized_cmds[category] = []
        categorized_cmds[category].append(f"`{prefix}{cmd_info['name']}`")

    sorted_categories = sorted(categorized_cmds.keys())
    help_text = f"🤖 **TG 游戏助手指令菜单**\n\n_使用 `{prefix}帮助 <指令名>` 查看具体用法。_\n"
    for category in sorted_categories:
        sorted_cmds = sorted(categorized_cmds[category])
        help_text += f"\n**{category}**\n{' '.join(sorted_cmds)}"
        
    await client.reply_to_admin(event, help_text)


async def execute_command(event):
    """
    [统一分发版] 指令执行的核心入口。
    """
    app = get_application()
    client = app.client
    text = event.text.strip()
    
    used_prefix = next((p for p in settings.COMMAND_PREFIXES if text.startswith(p)), None)
    if not used_prefix: return

    command_body = text[len(used_prefix):].strip()
    try:
        parts = shlex.split(command_body)
    except ValueError:
        await client.reply_to_admin(event, "❌ 参数解析错误，请检查您的引号是否匹配。")
        return

    if not parts: return

    cmd_name = parts[0]
    command_info = app.commands.get(cmd_name.lower())
    
    if not command_info or not command_info.get("handler"):
        if str(event.sender_id) == str(settings.ADMIN_USER_ID):
            await client.reply_to_admin(event, f"❓ 未知指令: `{cmd_name}`")
        return

    handler = command_info.get("handler")
    category = command_info.get("category")
    my_id = str(client.me.id)

    # --- 核心分发逻辑 ---
    # 1. 如果是高级协同指令 (P2P模式)
    if category == "高级协同":
        # 只有消息发送者自己才能执行
        if str(event.sender_id) == my_id:
            format_and_log("INFO", "指令分发-P2P模式", {'指令': cmd_name, '发起者': my_id})
            await handler(event, parts)
        # 其他号直接忽略，不再报“未知指令”
        return

    # 2. 如果是其他管理指令 (Admin模式)
    else:
        # 只有管理员才能执行
        if str(event.sender_id) == str(settings.ADMIN_USER_ID):
            # 管理员号自己不回复自己在群里发的管理指令
            if event.is_group and str(client.me.id) == str(settings.ADMIN_USER_ID):
                return
            format_and_log("INFO", "指令分发-Admin模式", {'指令': cmd_name, '执行者': my_id})
            await handler(event, parts)
        # 其他号直接忽略
        return


def initialize(app):
    client = app.client
    
    listen_chats = [settings.ADMIN_USER_ID]
    if settings.CONTROL_GROUP_ID:
        listen_chats.append(settings.CONTROL_GROUP_ID)

    app.register_command("帮助", _handle_help_command, help_text="ℹ️ 显示此帮助菜单。", category="系统管理", aliases=["help"])

    # 唯一的指令监听器
    @client.client.on(events.NewMessage(chats=listen_chats))
    async def unified_command_handler(event):
        await execute_command(event)
