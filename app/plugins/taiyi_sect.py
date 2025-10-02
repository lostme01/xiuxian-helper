# -*- coding: utf-8 -*-
import logging
import random
import pytz
import asyncio
from datetime import datetime, timedelta
from app.state_manager import get_state, set_state
from app.utils import parse_cooldown_time
from config import settings
from app.logger import format_and_log
from app.task_scheduler import scheduler
from app.telegram_client import CommandTimeoutError
from app.context import get_application

__plugin_sect__ = '太一门'

TASK_ID_YINDAO = 'taiyi_yindao_task'
STATE_KEY_YINDAO = "taiyi_yindao"

async def trigger_yindao(force_run=False):
    client = get_application().client
    format_and_log("TASK", "太一门引道", {'阶段': '任务开始', '强制执行': force_run})
    beijing_tz = pytz.timezone(settings.TZ)
    next_run_time = datetime.now(beijing_tz) + timedelta(minutes=15) 
    
    yindao_command = settings.GAME_COMMANDS.get('taiyi_yindao', '.引道 水')
    
    try:
        # --- 改造：移除硬编码的 timeout=60，使其使用全局默认值 ---
        _sent, reply = await client.send_game_command_request_response(yindao_command)
        format_and_log("TASK", "太一门引道", {'阶段': '获取状态成功', '原始返回': reply.raw_text.replace('\n', ' ')})
        
        cooldown = parse_cooldown_time(reply)
        if not cooldown and "获得" in reply.text and "神识" in reply.text:
            cooldown = timedelta(hours=settings.TAIYI_SECT_CONFIG.get('yindao_success_cooldown_hours', 12))
            format_and_log("TASK", "太一门引道", {'阶段': '解析成功', '详情': '检测到成功信息，使用默认冷却时间。', '冷却时间': str(cooldown)})
        
        if cooldown:
            jitter_config = settings.TASK_JITTER['taiyi_yindao']
            jitter = random.uniform(jitter_config['min'], jitter_config['max'])
            next_run_time = datetime.now(beijing_tz) + cooldown + timedelta(seconds=jitter)
            format_and_log("TASK", "太一门引道", {'阶段': '解析成功', '冷却时间': str(cooldown), '下次运行': next_run_time.strftime('%Y-%m-%d %H:%M:%S')})
        else:
            next_run_time = datetime.now(beijing_tz) + timedelta(hours=1)
            format_and_log("TASK", "太一门引道", {'阶段': '解析失败', '详情': '未找到冷却时间，将在1小时后重试。'})
    except (CommandTimeoutError, Exception) as e:
        format_and_log("TASK", "太一门引道", {'阶段': '任务异常', '错误': str(e)}, level=logging.ERROR)
    finally:
        scheduler.add_job(trigger_yindao, 'date', run_date=next_run_time, id=TASK_ID_YINDAO, replace_existing=True)
        set_state(STATE_KEY_YINDAO, next_run_time.isoformat())
        format_and_log("TASK", "太一门引道", {'阶段': '任务完成', '详情': f'已计划下次运行时间: {next_run_time.strftime("%Y-%m-%d %H:%M:%S")}'})

async def check_yindao_startup():
    if scheduler.get_job(TASK_ID_YINDAO): return
    iso_str = get_state(STATE_KEY_YINDAO)
    state_time = datetime.fromisoformat(iso_str).astimezone(pytz.timezone(settings.TZ)) if iso_str else None
    now = datetime.now(pytz.timezone(settings.TZ))
    run_date = state_time if state_time and state_time > now else now + timedelta(seconds=random.uniform(10, 60))
    scheduler.add_job(trigger_yindao, 'date', run_date=run_date, id=TASK_ID_YINDAO)

def initialize(app):
    app.register_task(
        task_key='yindao',
        function=trigger_yindao,
        command_name="立即引道",
        help_text="立即执行一次太一门的引道任务。"
    )
    app.startup_checks.append(check_yindao_startup)

