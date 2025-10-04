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
    [最终优化版 v2]
    生成美化后的、适合移动端屏幕的三列布局帮助菜单。
    此版本放弃了复杂的宽度计算，以确保稳定性和兼容性。
    """
    app = get_application()
    client = app.client
    prefix = settings.COMMAND_PREFIXES[0]
    
    # 场景1: 查询单个指令的详细用法
    if len(parts) > 1:
        cmd_name_to_find = parts[1]
        command_info = app.commands.get(cmd_name_to_find.lower())
        if command_info:
            usage_text = command_info.get('usage', '该指令没有提供详细的帮助信息。')
            await client.reply_to_admin(event, f"📄 **指令帮助: {prefix}{cmd_name_to_find}**\n\n{usage_text}")
        else:
            await client.reply_to_admin(event, f"❓ 未找到指令: `{cmd_name_to_find}`")
        return

    # 场景2: 显示所有指令的概览菜单
    categorized_cmds = {}
    unique_cmds = {}
    # 去重，确保每个指令只显示一次（处理别名）
    for name, data in app.commands.items():
        handler = data.get('handler')
        if handler and handler not in unique_cmds:
            unique_cmds[handler] = {
                "name": name, 
                "category": data.get("category", "默认")
            }
    
    # 按分类聚合
    for cmd_info in unique_cmds.values():
        category = cmd_info["category"]
        if category not in categorized_cmds:
            categorized_cmds[category] = []
        categorized_cmds[category].append(f"`{prefix}{cmd_info['name']}`")

    # [核心优化] 开始生成简洁的三列布局
    COLUMN_COUNT = 3
    help_lines = [f"🤖 **TG 游戏助手指令菜单**\n\n_使用 `{prefix}帮助 <指令名>` 查看具体用法。_\n"]
    
    # 定义分类的显示顺序
    category_order = ["系统", "查询", "动作", "协同", "知识"]
    
    for category in category_order:
        if category in categorized_cmds:
            help_lines.append(f"**{category}**")
            
            sorted_cmds = sorted(categorized_cmds[category])
            
            # 将指令按列数分组，用简单的空格拼接
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

    cmd_name = parts[0]
    command_info = app.commands.get(cmd_name.lower())
    
    if not command_info or not command_info.get("handler"):
        if str(event.sender_id) == str(settings.ADMIN_USER_ID):
            pass
        return

    handler = command_info.get("handler")
    category = command_info.get("category")
    my_id = str(client.me.id)

    if category == "协同":
        if str(event.sender_id) == my_id:
            format_and_log("INFO", "指令分发-P2P模式", {'指令': cmd_name, '发起者': my_id})
            await handler(event, parts)
        return
    else:
        if str(event.sender_id) == str(settings.ADMIN_USER_ID):
            if event.is_group and str(client.me.id) == str(settings.ADMIN_USER_ID):
                return
            format_and_log("INFO", "指令分发-Admin模式", {'指令': cmd_name, '执行者': my_id})
            await handler(event, parts)
        return


def initialize(app):
    client = app.client
    
    listen_chats = [settings.ADMIN_USER_ID]
    if settings.CONTROL_GROUP_ID:
        listen_chats.append(settings.CONTROL_GROUP_ID)

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
