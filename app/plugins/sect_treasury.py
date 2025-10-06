# -*- coding: utf-8 -*-
import re
import logging
import random
from datetime import datetime, time, timedelta
import pytz

from config import settings
from app.context import get_application
from app.task_scheduler import scheduler
from app.telegram_client import CommandTimeoutError
from app.utils import send_paginated_message, create_error_reply, get_display_width
from telethon.errors.rpcerrorlist import MessageEditTimeExpiredError
from app import game_adaptor

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
    stats_manager = app.stats_manager
    command = game_adaptor.get_sect_treasury()
    format_and_log("TASK", "更新宗门宝库", {'阶段': '任务开始', '强制执行': force_run})
    try:
        _sent_message, reply_message = await client.send_game_command_request_response(command)

        treasury_data = _parse_treasury_text(reply_message.text)
        if not treasury_data["items"]:
            raise ValueError("无法从返回的信息中解析出宝库物品。")

        await stats_manager.set_contribution(treasury_data["contribution"])
        await app.data_manager.save_value(STATE_KEY_TREASURY, treasury_data)
        
        format_and_log("TASK", "更新宗门宝库", {'阶段': '任务成功', '贡献': treasury_data["contribution"], '物品数量': len(treasury_data["items"])})
        if force_run:
            return f"✅ **宗门宝库信息已更新**：\n- **当前贡献**: `{treasury_data['contribution']}` (已校准)\n- **宝库物品**: 共 `{len(treasury_data['items'])}` 件"
    except Exception as e:
        if force_run:
            raise e
        else:
             format_and_log("TASK", "更新宗门宝库", {'阶段': '任务异常', '错误': str(e)}, level=logging.CRITICAL)

async def _cmd_query_treasury(event, parts):
    app = get_application()
    client = app.client
    progress_message = await client.reply_to_admin(event, "⏳ 正在查询宗门宝库...")
    
    if not progress_message: return
    
    client.pin_message(progress_message)
    
    final_text = ""
    try:
        final_text = await trigger_update_treasury(force_run=True)
    except CommandTimeoutError as e:
        final_text = create_error_reply("宗门宝库", "游戏指令超时", details=str(e))
    except Exception as e:
        final_text = create_error_reply("宗门宝库", "任务执行期间发生意外错误", details=str(e))
    finally:
        client.unpin_message(progress_message)
        try:
            await client._cancel_message_deletion(progress_message)
            await progress_message.edit(final_text)
        except MessageEditTimeExpiredError:
            await client.reply_to_admin(event, final_text)

async def _cmd_view_cached_treasury(event, parts):
    app = get_application()
    treasury_data = await app.data_manager.get_value(STATE_KEY_TREASURY, is_json=True)
    contribution = await app.stats_manager.get_contribution()

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
    from app.logger import format_and_log
    if settings.TASK_SWITCHES.get('sect_treasury') and not scheduler.get_job(TASK_ID_TREASURY):
        run_time = time(hour=random.randint(2, 5), minute=random.randint(0, 59))
        scheduler.add_job(trigger_update_treasury, 'cron', hour=run_time.hour, minute=run_time.minute, id=TASK_ID_TREASURY, jitter=600)
        format_and_log("SYSTEM", "任务调度", {'任务': '每日自动更新宗门宝库', '状态': '已计划', '预计时间': run_time.strftime('%H:%M')})

def initialize(app):
    app.register_command("宗门宝库", _cmd_query_treasury, help_text="主动查询并刷新宗门宝库的物品列表和贡献。", category="查询")
    app.register_command("查看宝库", _cmd_view_cached_treasury, help_text="查看已缓存的宗门宝库信息。", category="查询")
    app.startup_checks.append(check_treasury_startup)
