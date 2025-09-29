# -*- coding: utf-8 -*-
import logging
import random
import pytz
import asyncio
from datetime import datetime, timedelta
from app.utils import parse_cooldown_time, read_state, write_state
from config import settings
from app.logger import format_and_log
from app.task_scheduler import scheduler
from app.context import get_application

TASK_ID_YINDAO = 'taiyi_yindao_task'
STATE_FILE_PATH_YINDAO = f"{settings.DATA_DIR}/taiyi_yindao.state"
YINDAO_COMMAND = ".引道 水"

def initialize_tasks():
    app = get_application()
    app.client.register_task('yindao', trigger_yindao)
    return [check_yindao_startup]

async def check_yindao_startup():
    if scheduler.get_job(TASK_ID_YINDAO): return
    iso_str = read_state(STATE_FILE_PATH_YINDAO)
    state_time = datetime.fromisoformat(iso_str).astimezone(pytz.timezone(settings.TZ)) if iso_str else None
    now = datetime.now(pytz.timezone(settings.TZ))
    
    if state_time and state_time > now:
        scheduler.add_job(trigger_yindao, 'date', run_date=state_time, id=TASK_ID_YINDAO)
    else:
        delay = random.uniform(10, 60)
        run_at = now + timedelta(seconds=delay)
        scheduler.add_job(trigger_yindao, 'date', run_date=run_at, id=TASK_ID_YINDAO)

async def trigger_yindao(force_run=False):
    """
    (逻辑恢复与优化) 使用 send_and_wait 处理单条回复，并优化判断逻辑。
    """
    client = get_application().client
    beijing_tz = pytz.timezone(settings.TZ)
    next_run_time = None
    
    try:
        format_and_log("TASK", "任务启动", {'任务名': '引道'})
        _sent_msg, reply = await client.send_and_wait(YINDAO_COMMAND, timeout=60)
        
        if reply:
            cooldown = None
            # 1. 优先检查是否包含精确的冷却时间
            if "后再次引道" in reply.text:
                cooldown = parse_cooldown_time(reply.text)
                format_and_log("DEBUG", "引道任务", {'详情': f'从回复中解析到精确冷却时间: {cooldown}'})
            # 2. 如果没有精确时间，再检查是否是成功信息
            elif "获得" in reply.text and "神识" in reply.text:
                # 使用可配置的默认冷却时间
                default_hours = settings.TAIYI_SECT_CONFIG.get('yindao_success_cooldown_hours', 12)
                cooldown = timedelta(hours=default_hours)
                format_and_log("DEBUG", "引道任务", {'详情': f'匹配到成功信息，使用默认冷却: {default_hours} 小时'})

            if cooldown:
                next_run_time = datetime.now(beijing_tz) + cooldown + timedelta(seconds=random.uniform(5 * 60, 20 * 60))
                format_and_log("TASK", "任务成功", {'任务名': '引道', '下次执行': next_run_time.strftime('%H:%M:%S')})
            else:
                # 3. 如果是未知回复
                next_run_time = datetime.now(beijing_tz) + timedelta(hours=1)
                format_and_log("TASK", "任务警告", {'任务名': '引道', '原因': '无法解析回复内容，1小时后重试'}, level=logging.WARNING)
        else:
            # 4. 如果超时未收到回复
            next_run_time = datetime.now(beijing_tz) + timedelta(minutes=15)
            format_and_log("TASK", "任务失败", {'任务名': '引道', '原因': '发送指令后未收到回复，15分钟后重试'}, level=logging.WARNING)

    except Exception as e:
        # 5. 如果发生程序异常
        next_run_time = datetime.now(beijing_tz) + timedelta(minutes=30)
        format_and_log("TASK", "任务异常", {'任务名': '引道', '错误': str(e), '原因': '30分钟后重试'}, level=logging.ERROR)
        
    finally:
        if next_run_time:
            scheduler.add_job(trigger_yindao, 'date', run_date=next_run_time, id=TASK_ID_YINDAO, replace_existing=True)
            write_state(STATE_FILE_PATH_YINDAO, next_run_time.isoformat())

