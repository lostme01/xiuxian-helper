# -*- coding: utf-8 -*-
import re
import logging
import asyncio
import pytz
import random
from datetime import datetime, time, timedelta, date
from telethon.errors.rpcerrorlist import MessageEditTimeExpiredError
from config import settings
from app.logger import format_and_log
from app.context import get_application
from app.state_manager import set_state, get_state
from app.task_scheduler import scheduler
from app.telegram_client import CommandTimeoutError

STATE_KEY_FORMATION = "formation_info"
TASK_ID_FORMATION_BASE = 'formation_update_task_'

def _parse_formation_text(text: str) -> dict | None:
    if "的阵法心得" not in text:
        return None

    learned_formations = []
    active_formation = None

    learned_match = re.search(r"已掌握的阵法:\s*\n(.*?)\n\n", text, re.DOTALL)
    if learned_match:
        content = learned_match.group(1).strip()
        if "尚未学习" not in content:
            learned_formations = re.findall(r"【([^】]+)】", content)

    active_match = re.search(r"当前激活的防护阵:\s*\n\s*-\s*(.*)", text)
    if active_match:
        content = active_match.group(1).strip()
        if content != "无":
            m = re.search(r"【([^】]+)】", content)
            if m:
                active_formation = m.group(1)

    return {"learned": learned_formations, "active": active_formation}

def _format_formation_reply(formation_data: dict, title: str) -> str:
    lines = [title]
    
    learned_str = '、'.join([f"`{f}`" for f in formation_data.get('learned', [])]) or "`无`"
    lines.append(f"- **已掌握**: {learned_str}")
    
    active_str = f"`{formation_data.get('active')}`" if formation_data.get('active') else "`无`"
    lines.append(f"- **已激活**: {active_str}")
    
    return "\n".join(lines)

async def trigger_update_formation(force_run=False):
    app = get_application()
    client = app.client
    command = ".我的阵法"
    
    format_and_log("TASK", "查询阵法", {'阶段': '任务开始', '强制执行': force_run})

    try:
        _sent, reply = await client.send_game_command_request_response(command)
        
        formation_data = _parse_formation_text(reply.raw_text)

        if formation_data is None:
            if force_run:
                return f"❌ **[查询阵法]** 任务失败：返回信息格式不正确。\n\n**原始返回**:\n`{reply.text}`"
            return

        await set_state(STATE_KEY_FORMATION, formation_data)
        format_and_log("TASK", "查询阵法", {'阶段': '成功', '数据': formation_data})
        
        if force_run:
            return _format_formation_reply(formation_data, "✅ **[查询阵法]** 任务完成，数据已缓存:")

    except CommandTimeoutError:
         if force_run:
            return "❌ **[查询阵法]** 任务失败：等待游戏机器人回复超时。"
    except Exception as e:
        if force_run:
            return f"❌ **[查询阵法]** 任务执行异常: `{e}`"

async def _cmd_query_formation(event, parts):
    app = get_application()
    await app.client.reply_to_admin(event, await trigger_update_formation(force_run=True))

async def _cmd_view_cached_formation(event, parts):
    app = get_application()
    formation_data = await get_state(STATE_KEY_FORMATION, is_json=True)
    if not formation_data:
        await app.client.reply_to_admin(event, "ℹ️ 尚未缓存任何阵法信息，请先使用 `,我的阵法` 查询一次。")
        return
    reply_text = _format_formation_reply(formation_data, "📄 **已缓存的阵法信息**:")
    await app.client.reply_to_admin(event, reply_text)

async def check_formation_update_startup():
    if not settings.TASK_SWITCHES.get('formation_update', True):
        return
    
    for job in scheduler.get_jobs():
        if job.id.startswith(TASK_ID_FORMATION_BASE):
            job.remove()
            
    beijing_tz = pytz.timezone(settings.TZ)
    now = datetime.now(beijing_tz)
    
    time_windows = [(8, 12), (14, 22)]
    
    for i, (start_h, end_h) in enumerate(time_windows):
        run_time = None
        for _ in range(10):
            temp_run_time = now.replace(hour=random.randint(start_h, end_h-1), minute=random.randint(0, 59))
            if temp_run_time > now:
                run_time = temp_run_time
                break
        
        if not run_time:
            run_time = (now + timedelta(days=1)).replace(hour=random.randint(start_h, end_h-1), minute=random.randint(0, 59))

        job_id = f"{TASK_ID_FORMATION_BASE}{i}"
        scheduler.add_job(trigger_update_formation, 'date', run_date=run_time, id=job_id)
        format_and_log("TASK", "查询阵法", {'阶段': '调度计划', '任务': f'每日第{i+1}次', '运行时间': run_time.strftime('%Y-%m-%d %H:%M:%S')})


def initialize(app):
    app.register_command("我的阵法", _cmd_query_formation, help_text="查询并刷新当前角色的阵法信息。", category="查询")
    app.register_command("查看阵法", _cmd_view_cached_formation, help_text="查看已缓存的最新阵法信息。", category="查询")
    
    app.startup_checks.append(check_formation_update_startup)
