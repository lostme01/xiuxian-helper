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
    
    # 场景1：查询特定指令的详细用法
    if len(parts) > 1:
        cmd_name_to_find = parts[1]
        command_info = app.commands.get(cmd_name_to_find)
        if command_info:
            usage_text = command_info.get('usage', '该指令没有提供详细的帮助信息。')
            await client.reply_to_admin(event, f"📄 **指令帮助: {prefix}{cmd_name_to_find}**\n\n{usage_text}")
        else:
            await client.reply_to_admin(event, f"❓ 未找到指令: `{cmd_name_to_find}`")
        return

    # 场景2：显示所有指令的概览 (优化后)
    categorized_cmds = {}
    unique_cmds = {}
    # 去重，确保每个指令的处理器只显示一次
    for name, data in app.commands.items():
        handler = data['handler']
        if handler not in unique_cmds:
            unique_cmds[handler] = {"name": name, "category": data.get("category", "默认")}
    
    for cmd_info in unique_cmds.values():
        category = cmd_info["category"]
        if category not in categorized_cmds:
            categorized_cmds[category] = []
        # --- 优化：只添加指令本身，不再添加说明 ---
        categorized_cmds[category].append(f"`{prefix}{cmd_info['name']}`")

    sorted_categories = sorted(categorized_cmds.keys())
    help_text = f"🤖 **TG 游戏助手指令菜单**\n\n_使用 `{prefix}帮助 <指令名>` 查看具体用法。_\n"
    for category in sorted_categories:
        # 对每个分类下的指令进行排序
        sorted_cmds = sorted(categorized_cmds[category])
        # --- 优化：使用空格连接，更紧凑 ---
        help_text += f"\n**{category}**\n{' '.join(sorted_cmds)}"
        
    await client.reply_to_admin(event, help_text)


async def execute_command(event):
    app = get_application()
    client = app.client
    command_text = event.text
    text = command_text.strip()
    command_body = None

    if text.startswith(("*all ", "*run ")):
        command_body = text[text.find(" ") + 1:].strip()
    else:
        used_prefix = next((p for p in settings.COMMAND_PREFIXES if text.startswith(p)), None)
        if used_prefix:
            command_body = text[len(used_prefix):].strip()

    if command_body is None:
        return

    if text.startswith("*all "):
        target_group = settings.GAME_GROUP_IDS[0] if settings.GAME_GROUP_IDS else None
        if target_group:
            await client.send_game_command_fire_and_forget(command_body, target_chat_id=target_group)
            await client.reply_to_admin(event, f"✅ 已向游戏群广播指令: `{command_body}`")
        return

    try:
        parts = shlex.split(command_body)
    except ValueError:
        await client.reply_to_admin(event, "❌ 参数解析错误，请检查您的引号是否匹配。")
        return

    if not parts:
        return

    cmd_name = parts[0]

    # 帮助指令已被注册，这里直接调用
    command_info = app.commands.get(cmd_name.lower())
    if command_info and (handler := command_info.get("handler")):
        try:
            await handler(event, parts)
        except Exception as e:
            format_and_log("SYSTEM", "指令执行失败", {'指令': cmd_name, '错误': str(e)}, level=logging.ERROR)
            await client.reply_to_admin(event, f"❌ 执行指令 `{cmd_name}` 时发生错误: `{e}`")
    elif not text.startswith("*all "):
        await client.reply_to_admin(event, f"❓ 未知指令: `{cmd_name}`")


def initialize(app):
    client = app.client
    admin_handler_chats = [settings.ADMIN_USER_ID]
    if settings.CONTROL_GROUP_ID:
        admin_handler_chats.append(settings.CONTROL_GROUP_ID)

    # 注册帮助指令
    app.register_command("帮助", _handle_help_command, help_text="ℹ️ 显示此帮助菜单。", category="系统管理", aliases=["help"])

    @client.client.on(events.NewMessage(
        from_users=settings.ADMIN_USER_ID,
        chats=admin_handler_chats
    ))
    async def group_control_handler(event):
        if event.out:
            is_command = any(event.text.startswith(p) for p in settings.COMMAND_PREFIXES + ['*all ', '*run '])
            if is_command:
                client._schedule_message_deletion(event.message, settings.AUTO_DELETE.get('delay_admin_command'), "管理员自己的指令")
        
        await execute_command(event)
