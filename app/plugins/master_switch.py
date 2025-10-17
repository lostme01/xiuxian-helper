# -*- coding: utf-8 -*-
from app.context import get_application, get_scheduler
from app.config_manager import update_nested_setting
from config import settings
from app.logging_service import LogType, format_and_log

HELP_TEXT_MASTER_SWITCH = """ T T T T**全局开关**
**说明**: [仅限管理员] 控制整个助手的运行状态。关闭后，助手将停止响应所有指令（“全局开关”除外）、暂停所有计划任务并忽略来自其他助手的任务。
**用法**: `,全局开关 <开|关>`
"""

async def _cmd_toggle_master_switch(event, parts):
    app = get_application()
    client = app.client
    scheduler = get_scheduler()

    if len(parts) != 2 or parts[1] not in ["开", "关"]:
        is_enabled = app.master_switch
        status = "✅ 开启中" if is_enabled else "❌ 已关闭"
        await client.reply_to_admin(event, f"ℹ️ **当前全局开关状态**: {status}\n\n{HELP_TEXT_MASTER_SWITCH}")
        return

    switch_str = parts[1]
    new_status = (switch_str == "开")

    # 更新配置文件和内存
    result = await update_nested_setting('master_switch', new_status)

    if "✅" in result:
        # 控制计划任务
        if new_status and scheduler.state == 2: # 2 表示 PAUSED
            scheduler.resume()
            format_and_log(LogType.SYSTEM, "核心服务", {'服务': '计划任务', '状态': '已恢复'})
        elif not new_status and scheduler.state == 1: # 1 表示 RUNNING
            scheduler.pause()
            format_and_log(LogType.SYSTEM, "核心服务", {'服务': '计划任务', '状态': '已暂停'})
        
        await client.reply_to_admin(event, f"✅ **全局开关已设置为 [{switch_str}]**\n所有服务（指令、计划任务、跨助手通信）均已切换至新状态。")
    else:
        await client.reply_to_admin(event, f"❌ **全局开关设置失败**\n\n{result}")

def initialize(app):
    app.register_command(
        name="全局开关",
        handler=_cmd_toggle_master_switch,
        help_text=" T T T T[管理员] 控制助手的总运行状态。",
        category="系统",
        aliases=["masterswitch"],
        usage=HELP_TEXT_MASTER_SWITCH
    )

