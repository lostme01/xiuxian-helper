# -*- coding: utf-8 -*-
import re
import logging
import asyncio
import pytz
import random
from datetime import datetime, time, timedelta, date
from telethon.errors.rpcerrorlist import MessageEditTimeExpiredError
from config import settings
from app.logging_service import LogType, format_and_log
from app.context import get_application
from app.task_scheduler import scheduler
from app.telegram_client import CommandTimeoutError
from app import game_adaptor
from app.data_manager import data_manager

STATE_KEY_FORMATION = "formation_info"
TASK_ID_FORMATION_BASE = 'formation_update_task_daily' # 修改ID以避免冲突
HELP_TEXT_QUERY_FORMATION = """ T T T T**查询阵法信息**
**说明**: 主动向游戏机器人查询最新的阵法信息，并更新本地缓存。
**用法**: `,查询阵法`
"""

def _parse_formation_text(text: str) -> dict | None:
    if "的阵法心得" not in text:
        return None

    learned_formations = []
    active_formation = None

    learned_match = re.search(r"\*\*已掌握的阵法:\*\*\s*\n(.*?)\n\n", text, re.DOTALL)
    if learned_match:
        content = learned_match.group(1).strip()
        if "尚未学习" not in content:
            # [BUG 修正] 对解析出的每个阵法名称进行 strip() 清理
            raw_names = re.findall(r"【([^】]+)】", content)
            learned_formations = [name.strip() for name in raw_names]

    active_match = re.search(r"\*\*当前激活的防护阵:\*\*\s*\n\s*-\s*(.*)", text)
    if active_match:
        content = active_match.group(1).strip()
        if content != "无":
            m = re.search(r"【([^】]+)】", content)
            if m:
                # [BUG 修正] 对解析出的激活阵法名称进行 strip() 清理
                active_formation = m.group(1).strip()

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
    command = game_adaptor.get_formation_info()
    
    format_and_log(LogType.TASK, "查询阵法", {'阶段': '任务开始', '强制执行': force_run})

    try:
        _sent, reply = await client.send_game_command_request_response(command)
        
        formation_data = _parse_formation_text(reply.text)

        if formation_data is None:
            if force_run:
                return f"❌ **[查询阵法]** 任务失败：返回信息格式不正确。\n\n**原始返回**:\n`{reply.text}`"
            return

        await data_manager.save_value(STATE_KEY_FORMATION, formation_data)
        format_and_log(LogType.TASK, "查询阵法", {'阶段': '成功', '数据': formation_data})
        
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
    formation_data = await data_manager.get_value(STATE_KEY_FORMATION, is_json=True)
    if not formation_data:
        await get_application().client.reply_to_admin(event, "ℹ️ 尚未缓存任何阵法信息，请先使用 `,查询阵法` 查询一次。")
        return
    reply_text = _format_formation_reply(formation_data, "📄 **已缓存的阵法信息**:")
    await get_application().client.reply_to_admin(event, reply_text)

async def check_formation_update_startup():
    """[调度优化] 低频校验数据：每天中午12-14点之间随机执行一次"""
    if settings.TASK_SWITCHES.get('formation_update', True) and not scheduler.get_job(TASK_ID_FORMATION_BASE):
        run_time = time(hour=random.randint(12, 13), minute=random.randint(0, 59), tzinfo=pytz.timezone(settings.TZ))
        scheduler.add_job(
            trigger_update_formation, 'cron', 
            hour=run_time.hour, minute=run_time.minute, 
            id=TASK_ID_FORMATION_BASE, 
            jitter=1800 # 增加30分钟随机抖动
        )
        format_and_log(LogType.SYSTEM, "任务调度", {'任务': '自动查询阵法 (低频)', '状态': '已计划', '预计时间': run_time.strftime('%H:%M')})


def initialize(app):
    app.register_command(
        name="查询阵法", 
        handler=_cmd_query_formation, 
        help_text=" T T T T查询并刷新当前角色的阵法信息。", 
        category="查询信息",
        aliases=["我的阵法"],
        usage=HELP_TEXT_QUERY_FORMATION
    )
    app.register_command(
        "查看阵法", 
        _cmd_view_cached_formation, 
        help_text="📄 查看已缓存的最新阵法信息。", 
        category="数据查询"
    )
    app.startup_checks.append(check_formation_update_startup)
