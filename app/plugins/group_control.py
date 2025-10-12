# -*- coding: utf-8 -*-
import logging
import shlex

from telethon import events

from app.context import get_application
from app.logging_service import LogType, format_and_log
from app.utils import get_display_width
from config import settings


async def _handle_help_command(event, parts):
    app = get_application()
    client = app.client
    prefix = settings.COMMAND_PREFIXES[0]
    
    if len(parts) > 1:
        cmd_name_to_find = parts[1]
        command_info = app.commands.get(cmd_name_to_find.lower())
        if command_info:
            usage_text = command_info.get('usage', '该指令没有提供详细的帮助信息。')
            await client.reply_to_admin(event, f"📄 **指令帮助: {prefix}{command_info['name']}**\n\n{usage_text}")
        else:
            await client.reply_to_admin(event, f"❓ 未找到指令: `{cmd_name_to_find}`")
        return

    hidden_commands = {
        "查看背包", "查看宝库", "查看角色", "查看阵法"
    }

    categorized_cmds = {}
    unique_cmds = {}
    for name, data in app.commands.items():
        canonical_name = data.get("name")
        if canonical_name in hidden_commands:
            continue
        handler = data.get('handler')
        if handler and handler not in unique_cmds:
            unique_cmds[handler] = {
                "name": canonical_name, 
                "category": data.get("category", "默认")
            }
    
    for cmd_info in unique_cmds.values():
        category = cmd_info["category"]
        if category not in categorized_cmds:
            categorized_cmds[category] = []
        categorized_cmds[category].append(f"`{prefix}{cmd_info['name']}`")

    help_lines = [f"🤖 **TG 游戏助手指令菜单**\n"]
    category_order = ["系统", "查询", "动作", "协同", "知识", "数据查询"]
    category_icons = {
        "系统": "⚙️", "查询": "🔍", "动作": "⚡️",
        "协同": "🤝", "知识": "📚", "数据查询": "📊", "默认": "🔸"
    }

    # [修改] 简化布局逻辑，统一为一行三个
    def format_commands_to_three_per_line(commands):
        lines = []
        # 首先对指令进行排序，保证每次生成的菜单顺序一致
        sorted_commands = sorted(commands)
        
        # 将排序后的指令列表，每3个一组进行切分
        for i in range(0, len(sorted_commands), 3):
            # 将每组的3个指令用空格连接成一行
            lines.append("  ".join(sorted_commands[i:i+3]))
            
        return lines

    all_categories = category_order + [cat for cat in sorted(categorized_cmds.keys()) if cat not in category_order]
    for category in all_categories:
        if category in categorized_cmds:
            icon = category_icons.get(category, "🔸")
            help_lines.append(f"**{icon} {category}**")
            # 使用新的、统一的布局函数
            formatted_lines = format_commands_to_three_per_line(categorized_cmds[category])
            help_lines.extend(formatted_lines)
            help_lines.append("")
    
    help_lines.append(f"**使用 `{prefix}获取帮助 <指令名>` 查看具体用法。**")
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
        if str(client.me.id) == str(settings.ADMIN_USER_ID):
            await client.reply_to_admin(event, "❌ 参数解析错误，请检查您的引号是否匹配。")
        return

    if not parts: return

    cmd_name = parts[0].lower()
    command_info = app.commands.get(cmd_name)
    
    if not command_info or not command_info.get("handler"):
        return

    is_admin_sender = str(event.sender_id) == str(settings.ADMIN_USER_ID)
    my_id = str(client.me.id)

    can_execute = False
    
    if is_admin_sender:
        if event.is_private:
            can_execute = True
        elif event.is_group:
            if event.is_reply:
                reply_to_msg = await event.get_reply_message()
                if reply_to_msg and str(reply_to_msg.sender_id) == my_id:
                    can_execute = True
            else:
                can_execute = True
    elif str(event.sender_id) == my_id and event.is_private and str(event.chat_id) == my_id:
         can_execute = True


    if can_execute:
        is_self_command = str(event.sender_id) == my_id
        if is_admin_sender or is_self_command:
            client._schedule_message_deletion(event.message, settings.AUTO_DELETE.get('delay_admin_command'), "管理员或自身指令原文")

        noisy_commands = settings.BROADCAST_CONFIG.get('noisy_commands', [])
        is_main_bot = my_id == str(settings.ADMIN_USER_ID)
        is_broadcast_in_group = is_admin_sender and event.is_group and not event.is_reply
        if is_broadcast_in_group and cmd_name in noisy_commands and not is_main_bot:
            format_and_log(LogType.TASK, "指令忽略", {'指令': cmd_name, '执行者': my_id, '原因': '非主控号，避免群内刷屏'})
            return

        format_and_log(LogType.TASK, "指令执行", {'指令': cmd_name, '执行者': my_id, '来源': 'Admin' if is_admin_sender else 'Self'})
        handler = command_info.get("handler")
        await handler(event, parts)

def initialize(app):
    client = app.client
    
    # 确保ID是整数类型
    listen_chats = [int(settings.ADMIN_USER_ID), 'me']
    if settings.CONTROL_GROUP_ID:
        listen_chats.append(int(settings.CONTROL_GROUP_ID))
    
    listen_chats = list(set(listen_chats))

    app.register_command(
        "获取帮助", 
        _handle_help_command, 
        help_text="ℹ️ 显示此帮助菜单。", 
        category="系统", 
        aliases=["help", "菜单", "menu", "帮助"]
    )

    @client.client.on(events.NewMessage(chats=listen_chats))
    async def unified_command_handler(event):
        await execute_command(event)
