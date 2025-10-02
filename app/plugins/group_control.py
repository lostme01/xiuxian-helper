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
        command_info = app.commands.get(cmd_name_to_find)
        if command_info:
            usage_text = command_info.get('usage', '该指令没有提供详细的帮助信息。')
            await client.reply_to_admin(event, f"📄 **指令帮助: {prefix}{cmd_name_to_find}**\n\n{usage_text}")
        else:
            await client.reply_to_admin(event, f"❓ 未找到指令: `{cmd_name_to_find}`")
        return

    categorized_cmds = {}
    unique_cmds = {}
    for name, data in app.commands.items():
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
    指令执行的核心入口，现在加入了详细的“黑匣子”日志。
    """
    app = get_application()
    client = app.client
    command_text = event.text
    
    format_and_log("DEBUG", "指令分发-入口", {
        '阶段': '进入 execute_command',
        '本机ID': client.me.id,
        '消息来源': event.chat_id,
        '消息ID': event.id,
        '发送者ID': event.sender_id,
        '消息内容': command_text
    })

    text = command_text.strip()
    command_body = None

    used_prefix = next((p for p in settings.COMMAND_PREFIXES if text.startswith(p)), None)
    if used_prefix:
        command_body = text[len(used_prefix):].strip()
    
    if command_body is None:
        format_and_log("DEBUG", "指令分发-预处理", {'阶段': '忽略', '原因': '消息内容不包含指令前缀'})
        return

    try:
        parts = shlex.split(command_body)
    except ValueError:
        await client.reply_to_admin(event, "❌ 参数解析错误，请检查您的引号是否匹配。")
        return

    if not parts:
        format_and_log("DEBUG", "指令分发-预处理", {'阶段': '忽略', '原因': '指令体为空'})
        return

    cmd_name = parts[0]
    format_and_log("DEBUG", "指令分发-解析", {'解析出指令': cmd_name, '解析出参数': str(parts)})

    command_info = app.commands.get(cmd_name.lower())
    if command_info and (handler := command_info.get("handler")):
        format_and_log("INFO", "指令分发-匹配成功", {'指令': cmd_name, '将调用处理器': handler.__name__})
        try:
            await handler(event, parts)
        except Exception as e:
            format_and_log("ERROR", "指令分发-执行异常", {'指令': cmd_name, '错误': str(e)}, level=logging.CRITICAL)
            await client.reply_to_admin(event, f"❌ 执行指令 `{cmd_name}` 时发生严重错误: `{e}`")
    else:
        # 仅在非管理员发送未知指令时回复
        if event.sender_id == settings.ADMIN_USER_ID:
            await client.reply_to_admin(event, f"❓ 未知指令: `{cmd_name}`")
        format_and_log("DEBUG", "指令分发-匹配失败", {'尝试匹配的指令': cmd_name})


def initialize(app):
    client = app.client
    admin_handler_chats = [settings.ADMIN_USER_ID]
    if settings.CONTROL_GROUP_ID:
        admin_handler_chats.append(settings.CONTROL_GROUP_ID)

    app.register_command("帮助", _handle_help_command, help_text="ℹ️ 显示此帮助菜单。", category="系统管理", aliases=["help"])

    @client.client.on(events.NewMessage(
        # --- 改造：监听所有配置的群组，而不仅仅是管理员的消息 ---
        # 这样才能捕获到管理员在游戏群中发送的指令
        chats=settings.GAME_GROUP_IDS + ([settings.CONTROL_GROUP_ID] if settings.CONTROL_GROUP_ID else [])
    ))
    async def group_control_handler(event):
        # 仅处理来自管理员的消息
        if event.sender_id != settings.ADMIN_USER_ID:
            return

        if event.out:
            is_command = any(event.text.startswith(p) for p in settings.COMMAND_PREFIXES)
            if is_command:
                client._schedule_message_deletion(event.message, settings.AUTO_DELETE.get('delay_admin_command'), "管理员自己的指令")
        
        await execute_command(event)

