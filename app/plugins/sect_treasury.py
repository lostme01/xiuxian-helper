# -*- coding: utf-8 -*-
import logging
import random
import re
from datetime import datetime, time, timedelta

import pytz
from telethon.errors.rpcerrorlist import MessageEditTimeExpiredError

from app import game_adaptor
from app.character_stats_manager import stats_manager
from app.context import get_application
from app.data_manager import data_manager
from app.task_scheduler import scheduler
from app.telegram_client import CommandTimeoutError
from app.utils import (create_error_reply, get_display_width,
                       progress_manager, send_paginated_message)

STATE_KEY_TREASURY = "sect_treasury"
TASK_ID_TREASURY = "sect_treasury_daily_task"
HELP_TEXT_QUERY_TREASURY = """ T T T T**查询宗门宝库**
**说明**: 主动向游戏机器人查询最新的宗门宝库信息，并更新本地缓存。
**用法**: `,查询宝库`
"""

def _parse_treasury_text(text: str) -> dict:
    from app.logging_service import LogType, format_and_log
    format_and_log(LogType.DEBUG, "宝库解析流程 -> _parse_treasury_text", {'阶段': '开始解析', '原始文本': text})
    data = {"contribution": 0, "items": []}
    if not text: return data
    contribution_match = re.search(r"你的贡献\s*:\s*(\d+)\s*点", text)
    if contribution_match: data["contribution"] = int(contribution_match.group(1))
    item_pattern = re.compile(r"-\s*\*\*(?P<name>.*?)\*\*:\s*(?P<desc>.*?)\s*\(\s*售价:\s*(?P<price>\d+)\s*贡献\)")
    items = []
    for match in item_pattern.finditer(text):
        item_data = match.groupdict()
        items.append({"name": item_data["name"].strip(), "description": item_data["desc"].strip(), "price": int(item_data["price"])})
    data["items"] = items
    format_and_log(LogType.DEBUG, "宝库解析流程 -> _parse_treasury_text", {'阶段': '解析完成', '贡献': data["contribution"], '物品数量': len(items)})
    return data

async def trigger_update_treasury(force_run=False):
    from app.logging_service import LogType, format_and_log
    app = get_application()
    client = app.client
    command = game_adaptor.get_sect_treasury()
    format_and_log(LogType.TASK, "更新宗门宝库", {'阶段': '任务开始', '强制执行': force_run})
    try:
        _sent_message, reply_message = await client.send_game_command_request_response(command)

        treasury_data = _parse_treasury_text(reply_message.text)
        if not treasury_data["items"]:
            raise ValueError("无法从返回的信息中解析出宝库物品。")

        await stats_manager.set_contribution(treasury_data["contribution"])
        await data_manager.save_value(STATE_KEY_TREASURY, treasury_data)
        
        format_and_log(LogType.TASK, "更新宗门宝库", {'阶段': '任务成功', '贡献': treasury_data["contribution"], '物品数量': len(treasury_data["items"])})
        if force_run:
            return f"✅ **宗门宝库信息已更新**：\n- **当前贡献**: `{treasury_data['contribution']}` (已校准)\n- **宝库物品**: 共 `{len(treasury_data['items'])}` 件"
    except Exception as e:
        if force_run:
            raise e
        else:
             format_and_log(LogType.TASK, "更新宗门宝库", {'阶段': '任务异常', '错误': str(e)}, level=logging.CRITICAL)

async def _cmd_query_treasury(event, parts):
    async with progress_manager(event, "⏳ 正在查询宗门宝库...") as progress:
        final_text = ""
        try:
            final_text = await trigger_update_treasury(force_run=True)
        except CommandTimeoutError as e:
            final_text = create_error_reply("查询宝库", "游戏指令超时", details=str(e))
        except Exception as e:
            final_text = create_error_reply("查询宝库", "任务执行异常", details=str(e))

        await progress.update(final_text)

async def _cmd_view_cached_treasury(event, parts):
    treasury_data = await data_manager.get_value(STATE_KEY_TREASURY, is_json=True)
    contribution = await stats_manager.get_contribution()

    if not treasury_data or not treasury_data.get('items'):
        reply_text = f"📄 **已缓存的宗门宝库信息**\n**当前贡献**: `{contribution}`\n\n(宝库为空或尚未缓存)"
        await get_application().client.reply_to_admin(event, reply_text)
        return

    items = treasury_data.get('items', [])
    max_width = 0
    for item in items:
        width = get_display_width(item['name'])
        if width > max_width: max_width = width
    items_text = []
    for item in items:
        current_width = get_display_width(item['name'])
        padding_spaces = ' ' * ((max_width - current_width) + 2)
        items_text.append(f"`{item['name']}{padding_spaces}售价：{item['price']}`")
    
    reply_text = f"📄 **已缓存的宗门宝库信息**\n**当前贡献**: `{contribution}`\n\n"
    reply_text += "\n".join(items_text)
    await send_paginated_message(event, reply_text)

async def check_treasury_startup():
    from app.logging_service import LogType, format_and_log
    if settings.TASK_SWITCHES.get('sect_treasury') and not scheduler.get_job(TASK_ID_TREASURY):
        run_time = time(hour=random.randint(2, 5), minute=random.randint(0, 59))
        scheduler.add_job(trigger_update_treasury, 'cron', hour=run_time.hour, minute=run_time.minute, id=TASK_ID_TREASURY, jitter=600)
        format_and_log(LogType.SYSTEM, "任务调度", {'任务': '每日自动更新宗门宝库', '状态': '已计划', '预计时间': run_time.strftime('%H:%M')})

def initialize(app):
    app.register_command(
        name="查询宝库", 
        handler=_cmd_query_treasury, 
        help_text=" T T T T查询并刷新宗门宝库的物品列表和贡献。", 
        category="查询信息",
        aliases=["宗门宝库"],
        usage=HELP_TEXT_QUERY_TREASURY
    )
    app.register_command(
        "查看宝库", 
        _cmd_view_cached_treasury, 
        help_text="📄 查看已缓存的宗门宝库信息。", 
        category="数据查询"
    )
    app.startup_checks.append(check_treasury_startup)
