# -*- coding: utf-8 -*-
import logging
import random
import pytz
import asyncio
import sys
import re
from datetime import datetime, timedelta, date, time
from app.utils import (
    parse_cooldown_time, # <-- 我们将使用这个正确的函数
    read_state, write_state, 
    read_json_state, write_json_state, parse_inventory_text
)
from config import settings
from app.logger import format_and_log
from app.task_scheduler import scheduler
from telethon.tl.functions.account import UpdateStatusRequest
from app.context import get_application

# --- 常量定义 ---
TASK_ID_BIGUAN = 'biguan_xiulian_task'
STATE_FILE_PATH_BIGUAN = f"{settings.DATA_DIR}/biguan.state"
TASK_ID_HEARTBEAT = 'heartbeat_check_task'
HEARTBEAT_TIMEOUT_MINUTES = 20
TASK_ID_DIANMAO = 'zongmen_dianmao_task'
STATE_FILE_PATH_DIANMAO = f"{settings.DATA_DIR}/dianmao.state"
TASK_ID_CHUANG_TA_1 = 'chuang_ta_task_1'
TASK_ID_CHUANG_TA_2 = 'chuang_ta_task_2'
STATE_FILE_PATH_CHUANG_TA = f"{settings.DATA_DIR}/chuang_ta.json"
TASK_ID_INVENTORY_REFRESH = 'inventory_refresh_task'
INVENTORY_FILE_PATH = f"{settings.DATA_DIR}/inventory.json"
TASK_ID_ACTIVE_HEARTBEAT = 'active_status_heartbeat_task'

# --- 核心修复：移除有缺陷的 _parse_biguan_cooldown 函数 ---
# (原错误函数已删除)

def initialize_tasks():
    app = get_application()
    app.client.register_task("biguan", trigger_biguan_xiulian)
    app.client.register_task("dianmao", trigger_dianmao_chuangong)
    app.client.register_task("chuang_ta", trigger_chuang_ta)
    app.client.register_task("update_inventory", update_inventory_cache)
    return [
        check_biguan_startup, 
        check_dianmao_startup, 
        check_chuang_ta_startup, 
        check_inventory_refresh_startup,
        check_heartbeat_startup,
        check_active_heartbeat_startup
    ]

async def active_status_heartbeat():
    client = get_application().client
    try:
        await client.client(UpdateStatusRequest(offline=False))
    except Exception: pass

async def check_active_heartbeat_startup():
    if not scheduler.get_job(TASK_ID_ACTIVE_HEARTBEAT):
        scheduler.add_job(active_status_heartbeat, 'interval', minutes=5, id=TASK_ID_ACTIVE_HEARTBEAT)

async def heartbeat_check():
    client = get_application().client
    time_since_last_update = datetime.now(pytz.timezone(settings.TZ)) - client.last_update_timestamp
    if time_since_last_update > timedelta(minutes=HEARTBEAT_TIMEOUT_MINUTES):
        await client.send_admin_notification(f"🚨 **告警：助手会话可能已沉睡，正在自动重启...**")
        await asyncio.sleep(2)
        sys.exit(1)

async def check_heartbeat_startup():
    if not scheduler.get_job(TASK_ID_HEARTBEAT):
        scheduler.add_job(heartbeat_check, 'interval', minutes=15, id=TASK_ID_HEARTBEAT)

async def update_inventory_cache(force_run=False):
    source = "管理员手动触发" if force_run else "定时调度"
    format_and_log("TASK", "任务启动", {'任务名': '刷新背包', '来源': source})
    client = get_application().client
    _sent, reply = await client.send_and_wait(".储物袋")
    if reply:
        inventory = parse_inventory_text(reply.text)
        if inventory:
            write_json_state(INVENTORY_FILE_PATH, inventory)
            format_and_log("TASK", "任务成功", {'任务名': '刷新背包', '详情': f'背包缓存已更新，共 {len(inventory)} 种物品'})

async def check_inventory_refresh_startup():
    if not settings.TASK_SWITCHES.get('inventory_refresh', True): return
    if not scheduler.get_job(TASK_ID_INVENTORY_REFRESH):
        scheduler.add_job(update_inventory_cache, 'interval', hours=6, jitter=3600, id=TASK_ID_INVENTORY_REFRESH)

async def trigger_chuang_ta(force_run=False):
    source = "管理员手动触发" if force_run else "定时调度"
    format_and_log("TASK", "任务启动", {'任务名': '闯塔', '来源': source})
    client = get_application().client
    await client.send_command(".闯塔")

async def check_chuang_ta_startup():
    if not settings.TASK_SWITCHES.get('chuang_ta', True): return
    today_str = date.today().isoformat()
    state = read_json_state(STATE_FILE_PATH_CHUANG_TA) or {}
    if state.get("date") != today_str or not (scheduler.get_job(TASK_ID_CHUANG_TA_1) or scheduler.get_job(TASK_ID_CHUANG_TA_2)):
        for job_id in [TASK_ID_CHUANG_TA_1, TASK_ID_CHUANG_TA_2]:
            if scheduler.get_job(job_id): scheduler.remove_job(job_id)
        beijing_tz = pytz.timezone(settings.TZ)
        now = datetime.now(beijing_tz)
        for i, (start_h, end_h) in enumerate([(8, 14), (15, 23)]):
            run_time = now.replace(hour=random.randint(start_h, end_h), minute=random.randint(0, 59))
            if run_time > now:
                scheduler.add_job(trigger_chuang_ta, 'date', run_date=run_time, id=f'chuang_ta_task_{i+1}')
        write_json_state(STATE_FILE_PATH_CHUANG_TA, {"date": today_str, "count": 0})

async def trigger_biguan_xiulian(force_run=False):
    source = "管理员手动触发" if force_run else "定时调度"
    format_and_log("TASK", "任务启动", {'任务名': '闭关修炼', '来源': source})
    client = get_application().client
    beijing_tz = pytz.timezone(settings.TZ)
    next_run_time = None
    try:
        _sent_msg, reply = await client.send_and_wait(".闭关修炼")
        if reply:
            # --- 核心修复：调用通用的、正确的 parse_cooldown_time 函数 ---
            cooldown = parse_cooldown_time(reply.text)
            if cooldown:
                next_run_time = datetime.now(beijing_tz) + cooldown + timedelta(seconds=random.uniform(30, 90))
                format_and_log("TASK", "任务成功", {'任务名': '闭关修炼', '冷却时间': str(cooldown), '下次执行': next_run_time.strftime('%H:%M:%S')})
            else:
                next_run_time = datetime.now(beijing_tz) + timedelta(minutes=15)
                format_and_log("TASK", "任务警告", {'任务名': '闭关修炼', '原因': '无法解析冷却时间，15分钟后重试'}, level=logging.WARNING)
        else:
            next_run_time = datetime.now(beijing_tz) + timedelta(minutes=15)
    except Exception as e:
        next_run_time = datetime.now(beijing_tz) + timedelta(minutes=30)
    finally:
        if next_run_time:
            scheduler.add_job(trigger_biguan_xiulian, 'date', run_date=next_run_time, id=TASK_ID_BIGUAN, replace_existing=True)
            write_state(STATE_FILE_PATH_BIGUAN, next_run_time.isoformat())

async def check_biguan_startup():
    if not settings.TASK_SWITCHES.get('biguan'): return
    if scheduler.get_job(TASK_ID_BIGUAN): return
    iso_str = read_state(STATE_FILE_PATH_BIGUAN)
    beijing_tz = pytz.timezone(settings.TZ)
    state_time = datetime.fromisoformat(iso_str).astimezone(beijing_tz) if iso_str else None
    if state_time and state_time > datetime.now(beijing_tz):
        scheduler.add_job(trigger_biguan_xiulian, 'date', run_date=state_time, id=TASK_ID_BIGUAN)
    else: asyncio.create_task(trigger_biguan_xiulian(force_run=True))

async def trigger_dianmao_chuangong(force_run=False):
    source = "管理员手动触发" if force_run else "定时调度"
    format_and_log("TASK", "任务启动", {'任务名': '宗门点卯', '来源': source})
    client = get_application().client
    today_str = date.today().isoformat()
    if not force_run and read_state(STATE_FILE_PATH_DIANMAO) == today_str: return
    sent_dianmao_message, reply = await client.send_and_wait(".宗门点卯")
    if reply and "已经点过卯" not in reply.text:
        commands_to_chain = [".宗门传功", ".宗门传功", ".宗门传功"]
        await client.send_command_chain(commands_to_chain, initial_reply_to_message=sent_dianmao_message)
    write_state(STATE_FILE_PATH_DIANMAO, today_str)
    beijing_tz = pytz.timezone(settings.TZ)
    tomorrow = datetime.now(beijing_tz).date() + timedelta(days=1)
    run_time = beijing_tz.localize(datetime.combine(tomorrow, time(hour=8, minute=random.randint(0, 30))))
    scheduler.add_job(trigger_dianmao_chuangong, 'date', run_date=run_time, id=TASK_ID_DIANMAO, replace_existing=True)

async def check_dianmao_startup():
    if not settings.TASK_SWITCHES.get('dianmao'): return
    if scheduler.get_job(TASK_ID_DIANMAO): return
    today_str = date.today().isoformat()
    # --- 修复：修复了dianmao.state不存在时，read_state返回None导致和today_str比较报错的问题
    if read_state(STATE_FILE_PATH_DIANMAO) != today_str:
        asyncio.create_task(trigger_dianmao_chuangong(force_run=True))
    else:
        beijing_tz = pytz.timezone(settings.TZ)
        tomorrow = datetime.now(beijing_tz).date() + timedelta(days=1)
        run_time = beijing_tz.localize(datetime.combine(tomorrow, time(hour=8, minute=random.randint(0, 30))))
        scheduler.add_job(trigger_dianmao_chuangong, 'date', run_date=run_time, id=TASK_ID_DIANMAO, replace_existing=True)

