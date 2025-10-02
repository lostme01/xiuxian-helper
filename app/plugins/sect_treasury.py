# -*- coding: utf-8 -*-
import re
import logging
import random
from datetime import datetime, time, timedelta
import pytz

from config import settings
from app.context import get_application
from app.state_manager import set_state, get_state
from app.task_scheduler import scheduler
from app.telegram_client import CommandTimeoutError
from app.utils import send_paginated_message
from telethon.errors.rpcerrorlist import MessageEditTimeExpiredError

STATE_KEY_TREASURY = "sect_treasury"
TASK_ID_TREASURY = "sect_treasury_daily_task"

def _parse_treasury_text(text: str) -> dict:
    from app.logger import format_and_log
    format_and_log("DEBUG", "宝库解析流程 -> _parse_treasury_text", {'阶段': '开始解析', '原始文本': text})
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
    format_and_log("DEBUG", "宝库解析流程 -> _parse_treasury_text", {'阶段': '解析完成', '贡献': data["contribution"], '物品数量': len(items)})
    return data

async def trigger_update_treasury(force_run=False):
    from app.logger import format_and_log
    app = get_application()
    client = app.client
    command = ".宗门宝库"
    format_and_log("TASK", "更新宗门宝库", {'阶段': '任务开始', '强制执行': force_run})
    try:
        _sent_message, reply_message = await client.send_game_command_request_response(command)

        treasury_data = _parse_treasury_text(reply_message.text)
        if not treasury_data["items"]:
            format_and_log("TASK", "更新宗门宝库", {'阶段': '任务失败', '原因': '未能解析出任何物品信息'}, level=logging.WARNING)
            return False, "❌ **解析失败**: 无法从返回的信息中解析出宝库物品。"

        await set_state(STATE_KEY_TREASURY, treasury_data)
        format_and_log("TASK", "更新宗门宝库", {'阶段': '任务成功', '贡献': treasury_data["contribution"], '物品数量': len(treasury_data["items"])})
        return True, f"✅ **宗门宝库信息已更新**：\n- **当前贡献**: `{treasury_data['contribution']}`\n- **宝库物品**: 共 `{len(treasury_data['items'])}` 件"
    except CommandTimeoutError:
        format_and_log("TASK", "更新宗门宝库", {'阶段': '任务失败', '原因': '等待宝库回复超时'}, level=logging.ERROR)
        return False, "❌ **查询失败**: 发送指令后，游戏机器人无响应。"
    except Exception as e:
        format_and_log("TASK", "更新宗门宝库", {'阶段': '任务异常', '错误': str(e)}, level=logging.CRITICAL)
        return False, f"❌ **发生意外错误**: `{str(e)}`"

async def _cmd_query_treasury(event, parts):
    app = get_application()
    client = app.client
    progress_message = await client.reply_to_admin(event, "⏳ 正在查询宗门宝库...")
    
    if not progress_message: return
    
    client.pin_message(progress_message)
    
    _is_success, result = await trigger_update_treasury(force_run=True)
    
    client.unpin_message(progress_message)

    try:
        await client._cancel_message_deletion(progress_message)
        edited_message = await progress_message.edit(result)
        client._schedule_message_deletion(edited_message, settings.AUTO_DELETE.get('delay_admin_command'), "宝库查询结果")
    except MessageEditTimeExpiredError:
        await client.reply_to_admin(event, result)

def get_display_width(text: str) -> int:
    width = 0
    for char in text:
        if '\u4e00' <= char <= '\u9fff': width += 2
        else: width += 1
    return width

async def _cmd_view_cached_treasury(event, parts):
    treasury_data = await get_state(STATE_KEY_TREASURY, is_json=True)
    if not treasury_data:
        app = get_application()
        await app.client.reply_to_admin(event, "ℹ️ 尚未缓存任何宝库信息，请先使用 `,宗门宝库` 查询一次。")
        return
    items = treasury_data.get('items', [])
    if not items:
        reply_text = f"📄 **已缓存的宗门宝库信息**\n**当前贡献**: `{treasury_data.get('contribution', '未知')}`\n\n(宝库为空)"
        await get_application().client.reply_to_admin(event, reply_text)
        return
    max_width = 0
    for item in items:
        width = get_display_width(item['name'])
        if width > max_width: max_width = width
    items_text = []
    for item in items:
        current_width = get_display_width(item['name'])
        padding_spaces = ' ' * ((max_width - current_width) + 2)
        items_text.append(f"`{item['name']}{padding_spaces}售价：{item['price']}`")
    reply_text = f"📄 **已缓存的宗门宝库信息**\n**当前贡献**: `{treasury_data.get('contribution', '未知')}`\n"
    reply_text += "\n".join(items_text)
    await send_paginated_message(event, reply_text)

async def check_treasury_startup():
    from app.logger import format_and_log
    if settings.TASK_SWITCHES.get('sect_treasury') and not scheduler.get_job(TASK_ID_TREASURY):
        run_time = time(hour=random.randint(2, 5), minute=random.randint(0, 59))
        scheduler.add_job(trigger_update_treasury, 'cron', hour=run_time.hour, minute=run_time.minute, id=TASK_ID_TREASURY, jitter=600)
        format_and_log("SYSTEM", "任务调度", {'任务': '每日自动更新宗门宝库', '状态': '已计划', '预计时间': run_time.strftime('%H:%M')})

def initialize(app):
    app.register_command("宗门宝库", _cmd_query_treasury, help_text="主动查询并刷新宗门宝库的物品列表和贡献。", category="游戏查询")
    app.register_command("查看宝库", _cmd_view_cached_treasury, help_text="查看已缓存的宗门宝库信息。", category="游戏查询")
    app.startup_checks.append(check_treasury_startup)
