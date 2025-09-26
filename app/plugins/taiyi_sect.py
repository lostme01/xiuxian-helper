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

client = None
TASK_ID_YINDAO = 'taiyi_yindao_task'
STATE_FILE_PATH_YINDAO = f"{settings.DATA_DIR}/taiyi_yindao.state"
YINDAO_COMMAND = ".引道 水"

def initialize_tasks(tg_client):
    global client
    client = tg_client
    client.register_task('yindao', trigger_yindao)
    client.register_admin_command("引道", manual_trigger_yindao, "手动触发一次太一门引道任务。")
    return [check_yindao_startup]

async def manual_trigger_yindao(client, event, parts):
    format_and_log("TASK", "任务触发", {'任务名': '引道', '来源': '管理员手动触发'})
    await event.reply("好的，已手动触发 **[引道]** 任务。", parse_mode='md')
    asyncio.create_task(trigger_yindao())

async def trigger_yindao(force_run=False):
    format_and_log("TASK", "任务启动", {'任务名': '引道'})
    _sent_msg, reply = await client.send_and_wait(YINDAO_COMMAND)
    beijing_tz = pytz.timezone(settings.TZ)
    cooldown, next_run_time = None, datetime.now(beijing_tz)
    
    if reply:
        if "后再次引道" in reply.text:
            cooldown = parse_cooldown_time(reply.text)
        elif "获得" in reply.text and "神识" in reply.text:
            cooldown = timedelta(hours=12)
    
    if cooldown:
        next_run_time += cooldown + timedelta(seconds=random.uniform(5 * 60, 20 * 60))
        format_and_log("TASK", "任务成功", {'任务名': '引道', '下次执行': next_run_time.strftime('%Y-%m-%d %H:%M:%S')})
    else:
        next_run_time += timedelta(hours=1)
        format_and_log("TASK", "任务失败", {'任务名': '引道', '原因': '未能解析冷却时间，1小时后重试'}, level=logging.WARNING)
    
    scheduler.add_job(trigger_yindao, 'date', run_date=next_run_time, id=TASK_ID_YINDAO, replace_existing=True)
    write_state(STATE_FILE_PATH_YINDAO, next_run_time.isoformat())
        
async def check_yindao_startup():
    if scheduler.get_job(TASK_ID_YINDAO): return
    iso_str = read_state(STATE_FILE_PATH_YINDAO)
    state_time = datetime.fromisoformat(iso_str).astimezone(pytz.timezone(settings.TZ)) if iso_str else None
    if state_time and state_time > datetime.now(pytz.timezone(settings.TZ)):
        scheduler.add_job(trigger_yindao, 'date', run_date=state_time, id=TASK_ID_YINDAO)
    else: asyncio.create_task(trigger_yindao())
