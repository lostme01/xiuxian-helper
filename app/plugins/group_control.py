# -*- coding: utf-8 -*-
import shlex
import logging
from telethon import events

from config import settings
from app.context import get_application
from app.logger import format_and_log
from app.utils import get_display_width

async def _handle_help_command(event, parts):
    """
    生成帮助菜单。
    """
    app = get_application()
    client = app.client
    prefix = settings.COMMAND_PREFIXES[0]
    
    if len(parts) > 1:
        cmd_name_to_find = parts[1]
        # [核心修改] 别名查找也在这里处理
        command_info = app.commands.get(cmd_name_to_find.lower())
        if command_info:
            usage_text = command_info.get('usage', '该指令没有提供详细的帮助信息。')
            await client.reply_to_admin(event, f"📄 **指令帮助: {prefix}{command_info['name']}**\n\n{usage_text}")
        else:
            await client.reply_to_admin(event, f"❓ 未找到指令: `{cmd_name_to_find}`")
        return

    categorized_cmds = {}
    unique_cmds = {}
    for name, data in app.commands.items():
        handler = data.get('handler')
        if handler and handler not in unique_cmds:
            unique_cmds[handler] = {
                "name": name, 
                "category": data.get("category", "默认")
            }
    
    for cmd_info in unique_cmds.values():
        category = cmd_info["category"]
        if category not in categorized_cmds:
            categorized_cmds[category] = []
        categorized_cmds[category].append(f"`{prefix}{cmd_info['name']}`")

    COLUMN_COUNT = 3
    help_lines = [f"🤖 **TG 游戏助手指令菜单**\n\n_使用 `{prefix}帮助 <指令名>` 查看具体用法。_\n"]
    
    category_order = ["系统", "查询", "动作", "协同", "知识"]
    
    for category in category_order:
        if category in categorized_cmds:
            help_lines.append(f"**{category}**")
            sorted_cmds = sorted(categorized_cmds[category])
            for i in range(0, len(sorted_cmds), COLUMN_COUNT):
                row_items = sorted_cmds[i:i + COLUMN_COUNT]
                line = '  '.join(row_items)
                help_lines.append(line)
            help_lines.append("")

    await client.reply_to_admin(event, "\n".join(help_lines))


async def execute_command(event):
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

    cmd_name = parts[0].lower()
    command_info = app.commands.get(cmd_name)
    
    if not command_info or not command_info.get("handler"):
        return

    is_admin = str(event.sender_id) == str(settings.ADMIN_USER_ID)
    my_id = str(client.me.id)

    # [核心修改] 更新受限指令列表
    restricted_commands = ["炼制物品", "炼制集材", "智能炼制"]
    is_restricted = command_info['name'] in restricted_commands

    can_execute = False
    if is_admin:
        can_execute = True
    elif is_restricted:
        if event.is_private and str(event.chat_id) == my_id:
            can_execute = True
    else:
        if (event.is_private and str(event.chat_id) == my_id) or (event.is_group and str(event.sender_id) == my_id):
             can_execute = True

    if can_execute:
        format_and_log("INFO", "指令执行", {'指令': cmd_name, '执行者': my_id, '来源': 'Admin' if is_admin else 'Self'})
        handler = command_info.get("handler")
        await handler(event, parts)


def initialize(app):
    client = app.client
    
    listen_chats = [settings.ADMIN_USER_ID]
    if settings.CONTROL_GROUP_ID:
        listen_chats.append(settings.CONTROL_GROUP_ID)
    
    # [新增] 助手号也需要监听自己的收藏夹
    listen_chats.append('me')

    app.register_command(
        "帮助", 
        _handle_help_command, 
        help_text="ℹ️ 显示此帮助菜单。", 
        category="系统", 
        aliases=["help", "菜单", "menu"]
    )

    @client.client.on(events.NewMessage(chats=listen_chats))
    async def unified_command_handler(event):
        await execute_command(event)
