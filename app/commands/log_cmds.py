# -*- coding: utf-8 -*-
import logging
from config import settings
from app.config_manager import update_setting
from app.telegram_client import LOG_TYPE_MAP_ZH_TO_EN

HELP_DETAILS = {
    "日志状态": "查看所有日志模块的当前开关状态。",
    "日志设置": "设置特定日志模块的开关。\n用法: `,日志设置 <类型> <开|关>`\n类型: `系统`|`任务`|`指令`|`消息`|`回复`|`编辑`|`删除`|`原始`|`调试`",
}

async def _cmd_log_status(client, event, parts):
    status_text = "**各模块日志开关状态**:\n"
    en_to_zh_map = {v: k for k, v in LOG_TYPE_MAP_ZH_TO_EN.items()}
    for key_en, value in settings.LOGGING_SWITCHES.items():
        key_zh = en_to_zh_map.get(key_en, key_en)
        status_text += f"- **{key_zh}**: **{'开启' if value else '关闭'}**\n"
    await event.reply(status_text, parse_mode='md')

async def _cmd_log_toggle(client, event, parts):
    help_text = client.admin_commands['日志设置']['help']
    if len(parts) != 3 or parts[2] not in ["开", "关"]:
        await event.reply(help_text, parse_mode='md')
        return
    
    log_type_zh, switch_action = parts[1], parts[2]
    log_type_en = LOG_TYPE_MAP_ZH_TO_EN.get(log_type_zh)
    
    if not log_type_en:
        await event.reply(f"错误: 未知的日志类型 '{log_type_zh}'。")
        return
        
    new_status = (switch_action == "开")
    await update_setting(event,
        root_key='logging_switches',
        sub_key=log_type_en,
        value=new_status,
        success_message=f"**{log_type_zh}** 日志已 **{switch_action}**"
    )

def initialize_commands(client):
    client.register_admin_command("日志状态", _cmd_log_status, HELP_DETAILS["日志状态"])
    client.register_admin_command("日志设置", _cmd_log_toggle, HELP_DETAILS["日志设置"])
