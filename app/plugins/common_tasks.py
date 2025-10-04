# -*- coding: utf-8 -*-
import logging
import random
import pytz
import asyncio
import sys
import re
from datetime import datetime, timedelta, date, time
from app.state_manager import get_state, set_state
from app.utils import parse_cooldown_time, parse_inventory_text, resilient_task
from config import settings
from app.logger import format_and_log
from app.task_scheduler import scheduler
from telethon.tl.functions.account import UpdateStatusRequest
from app.telegram_client import CommandTimeoutError
from app.context import get_application
from app.inventory_manager import inventory_manager
from app.character_stats_manager import stats_manager

TASK_ID_BIGUAN = 'biguan_xiulian_task'
STATE_KEY_BIGUAN = "biguan"
TASK_ID_HEARTBEAT = 'heartbeat_check_task'
TASK_ID_CHUANG_TA_BASE = 'chuang_ta_task_'
STATE_KEY_CHUANG_TA = "chuang_ta"
TASK_ID_INVENTORY_REFRESH = 'inventory_refresh_task'
STATE_KEY_INVENTORY = "inventory"
TASK_ID_ACTIVE_HEARTBEAT = 'active_status_heartbeat_task'

def _parse_and_update_contribution(reply_text: str):
    contrib_match = re.search(r"获得了 \*\*([\d,]+)\*\* 点宗门贡献", reply_text)
    if contrib_match:
        gained_contrib = int(contrib_match.group(1).replace(',', ''))
        asyncio.create_task(stats_manager.add_contribution(gained_contrib))
        format_and_log("DEBUG", "贡献度更新", {'来源': '点卯/传功', '增加': gained_contrib})

@resilient_task()
async def trigger_dianmao_chuangong(force_run=False):
    client = get_application().client
    format_and_log("TASK", "宗门点卯", {'阶段': '任务开始', '强制执行': force_run})
    sent_dianmao = None
    try:
        sent_dianmao, reply_dianmao = await client.send_game_command_long_task(".宗门点卯")
        client.pin_message(sent_dianmao)

        log_text = reply_dianmao.text.replace('\n', ' ')
        format_and_log("TASK", "宗门点卯", {'阶段': '点卯指令', '返回': log_text})
        
        if "获得了" in log_text:
            _parse_and_update_contribution(reply_dianmao.text)
        
        chuangong_commands = [".宗门传功"] * 3
        
        for i, command in enumerate(chuangong_commands):
            _sent_cg, reply_cg = await client.send_game_command_request_response(
                command, 
                reply_to=sent_dianmao.id
            )
            
            log_text_cg = reply_cg.text.replace('\n', ' ')
            format_and_log("TASK", "宗门点卯", {'阶段': f'传功 {i+1}/{len(chuangong_commands)}', '返回': log_text_cg})

            if "获得了" in log_text_cg:
                _parse_and_update_contribution(reply_cg.text)

            if "过于频繁" in log_text_cg:
                format_and_log("TASK", "宗门点卯", {'阶段': '传功已达上限', '详情': '任务链正常结束。'})
                if force_run: return "✅ **[立即点卯]** 任务已成功执行完毕（点卯和传功均已完成）。"
                return

        if force_run: return "✅ **[立即点卯]** 任务已成功执行完毕。"

    finally:
        if sent_dianmao:
            client.unpin_message(sent_dianmao)
            # [核心修复] 使用新的专用配置项
            delay = settings.AUTO_DELETE_STRATEGIES['long_task']['delay_anchor']
            client._schedule_message_deletion(sent_dianmao, delay, "宗门点卯(任务链结束)")

@resilient_task()
async def update_inventory_cache(force_run=False):
    client = get_application().client
    format_and_log("TASK", "刷新背包", {'阶段': '任务开始', '强制执行': force_run})
    
    try:
        _sent, reply = await client.send_game_command_request_response(".储物袋")
        inventory = parse_inventory_text(reply)
        if inventory:
            await inventory_manager.set_inventory(inventory)
            format_and_log("TASK", "刷新背包", {'阶段': '任务成功', '详情': f'解析并校准了 {len(inventory)} 种物品。'})
            if force_run:
                return f"✅ **[立即刷新背包]** 任务完成，已校准 {len(inventory)} 种物品。"
        else:
            raise ValueError("未能从游戏返回信息中解析到任何物品。")
    finally:
        if not force_run and settings.TASK_SWITCHES.get('inventory_refresh', True):
            random_interval_hours = random.uniform(12, 24)
            next_run_time = datetime.now(pytz.timezone(settings.TZ)) + timedelta(hours=random_interval_hours)
            scheduler.add_job(update_inventory_cache, 'date', run_date=next_run_time, id=TASK_ID_INVENTORY_REFRESH, replace_existing=True)
            format_and_log("TASK", "刷新背包", {'阶段': '任务完成', '详情': f'已计划下次校准时间: {next_run_time.strftime("%Y-%m-%d %H:%M:%S")}'})

@resilient_task()
async def trigger_chuang_ta(force_run=False):
    client = get_application().client
    format_and_log("TASK", "自动闯塔", {'阶段': '任务开始', '强制执行': force_run})
    
    try:
        _sent, final_reply = await client.send_and_wait_for_edit(".闯塔", initial_reply_pattern=r"踏入了古塔")
        
        if "【试炼古塔 - 战报】" in final_reply.text and "总收获" in final_reply.text:
            gain_match = re.search(r"获得了【(.+?)】x([\d,]+)", final_reply.text)
            if gain_match:
                item, quantity_str = gain_match.groups()
                quantity = int(quantity_str.replace(',', ''))
                await inventory_manager.add_item(item, quantity)
                format_and_log("TASK", "自动闯塔", {'阶段': '成功', '奖励已入库': f'{item} x{quantity}'})
            else:
                format_and_log("TASK", "自动闯塔", {'阶段': '完成', '详情': '本次闯塔无物品奖励。'})
        else:
            format_and_log("WARNING", "自动闯塔", {'阶段': '解析失败', '原因': '未收到预期的战报格式', '返回': final_reply.text})
    finally:
        if not force_run:
            today_str = date.today().isoformat()
            state = await get_state(STATE_KEY_CHUANG_TA, is_json=True, default={"date": today_str, "completed_count": 0})
            if state.get("date") != today_str: state = {"date": today_str, "completed_count": 1}
            else: state["completed_count"] = state.get("completed_count", 0) + 1
            await set_state(STATE_KEY_CHUANG_TA, state)
            format_and_log("TASK", "自动闯塔", {'阶段': '状态更新', '今日已完成': state["completed_count"]})

@resilient_task()
async def trigger_biguan_xiulian(force_run=False):
    client = get_application().client
    format_and_log("TASK", "闭关修炼", {'阶段': '任务开始', '强制执行': force_run})
    beijing_tz = pytz.timezone(settings.TZ)
    next_run_time = datetime.now(beijing_tz) + timedelta(minutes=15)
    try:
        _sent_msg, reply = await client.send_game_command_request_response(".闭关修炼")
        cooldown = parse_cooldown_time(reply)
        if cooldown:
            jitter_config = settings.TASK_JITTER['biguan']
            jitter = random.uniform(jitter_config['min'], jitter_config['max'])
            next_run_time = datetime.now(beijing_tz) + cooldown + timedelta(seconds=jitter)
            format_and_log("TASK", "闭关修炼", {'阶段': '解析成功', '冷却时间': str(cooldown), '下次运行': next_run_time.strftime('%Y-%m-%d %H:%M:%S')})
        else:
            format_and_log("TASK", "闭关修炼", {'阶段': '解析失败', '详情': '未找到冷却时间，将在15分钟后重试。'})
    finally:
        scheduler.add_job(trigger_biguan_xiulian, 'date', run_date=next_run_time, id=TASK_ID_BIGUAN, replace_existing=True)
        await set_state(STATE_KEY_BIGUAN, next_run_time.isoformat())
        format_and_log("TASK", "闭关修炼", {'阶段': '任务完成', '详情': f'已计划下次运行时间: {next_run_time.strftime("%Y-%m-%d %H:%M:%S")}'})

# ... (剩余的 check_*_startup 和 initialize 函数保持不变) ...

async def active_status_heartbeat():
    client = get_application().client
    if client and client.is_connected():
        await client.client(UpdateStatusRequest(offline=False))

async def heartbeat_check():
    client = get_application().client
    heartbeat_timeout_seconds = settings.HEARTBEAT_TIMEOUT
    time_since_last_update = datetime.now(pytz.timezone(settings.TZ)) - client.last_update_timestamp
    if time_since_last_update > timedelta(seconds=heartbeat_timeout_seconds):
        format_and_log("SYSTEM", "心跳检查", {'状态': '超时', '详情': f'超过 {heartbeat_timeout_seconds} 秒无活动，准备重启...'}, level=logging.CRITICAL)
        await client.send_admin_notification(f"🚨 **告警：助手会话可能已沉睡，正在自动重启...**")
        await asyncio.sleep(2); sys.exit(1)

async def check_biguan_startup():
    if not settings.TASK_SWITCHES.get('biguan'): return
    if scheduler.get_job(TASK_ID_BIGUAN): return
    iso_str = await get_state(STATE_KEY_BIGUAN)
    beijing_tz = pytz.timezone(settings.TZ)
    state_time = datetime.fromisoformat(iso_str).astimezone(beijing_tz) if iso_str else None
    if state_time and state_time > datetime.now(beijing_tz):
        scheduler.add_job(trigger_biguan_xiulian, 'date', run_date=state_time, id=TASK_ID_BIGUAN)
    else: await trigger_biguan_xiulian(force_run=True)

async def check_dianmao_startup():
    if not settings.TASK_SWITCHES.get('dianmao'): return
    beijing_tz, now = pytz.timezone(settings.TZ), datetime.now(pytz.timezone(settings.TZ))
    dianmao_times = settings.TASK_SCHEDULES.get('dianmao', [])
    for job in scheduler.get_jobs():
        if job.id.startswith('zongmen_dianmao_task_'):
            job.remove()
    for i, time_str in enumerate(dianmao_times):
        job_id = f'zongmen_dianmao_task_{i}'
        if not scheduler.get_job(job_id):
            try:
                hour, minute = map(int, time_str.split(':'))
                run_time = now.replace(hour=hour, minute=minute + random.randint(0, 5), second=0, microsecond=0)
                if run_time < now: run_time += timedelta(days=1)
                scheduler.add_job(trigger_dianmao_chuangong, 'date', run_date=run_time, id=job_id)
                format_and_log("TASK", "宗门点卯", {'阶段': '调度计划', '任务': f'每日第{i+1}次', '运行时间': run_time.strftime('%Y-%m-%d %H:%M:%S')})
            except ValueError:
                format_and_log("SYSTEM", "配置错误", {'模块': '宗门点卯', '错误': f'时间格式不正确: {time_str}'}, level=logging.ERROR)

async def check_active_heartbeat_startup():
    if not scheduler.get_job(TASK_ID_ACTIVE_HEARTBEAT):
        scheduler.add_job(active_status_heartbeat, 'interval', minutes=5, id=TASK_ID_ACTIVE_HEARTBEAT)

async def check_heartbeat_startup():
    if not scheduler.get_job(TASK_ID_HEARTBEAT):
        scheduler.add_job(heartbeat_check, 'interval', minutes=15, id=TASK_ID_HEARTBEAT)

async def check_inventory_refresh_startup():
    if settings.TASK_SWITCHES.get('inventory_refresh', True) and not scheduler.get_job(TASK_ID_INVENTORY_REFRESH):
        first_run_time = datetime.now(pytz.timezone(settings.TZ)) + timedelta(minutes=1)
        scheduler.add_job(update_inventory_cache, 'date', run_date=first_run_time, id=TASK_ID_INVENTORY_REFRESH)
        format_and_log("TASK", "刷新背包", {'阶段': '调度计划', '详情': '首次校准任务已计划在1分钟后运行'})

async def check_chuang_ta_startup():
    if not settings.TASK_SWITCHES.get('chuang_ta', True): return
    today_str = date.today().isoformat()
    state = await get_state(STATE_KEY_CHUANG_TA, is_json=True, default={"date": "1970-01-01", "completed_count": 0})
    if state.get("date") != today_str:
        state = {"date": today_str, "completed_count": 0}; await set_state(STATE_KEY_CHUANG_TA, state)
        format_and_log("TASK", "自动闯塔", {'阶段': '状态重置', '新的一天': today_str})
    completed_count = state.get("completed_count", 0)
    total_runs_per_day = 2
    for job in scheduler.get_jobs():
        if job.id.startswith(TASK_ID_CHUANG_TA_BASE): job.remove()
    if completed_count >= total_runs_per_day:
        format_and_log("TASK", "自动闯塔", {'阶段': '调度跳过', '原因': f'今日已完成 {completed_count} 次。'})
        return
    runs_to_schedule = total_runs_per_day - completed_count
    format_and_log("TASK", "自动闯塔", {'阶段': '调度计划', '今日待办': runs_to_schedule})
    beijing_tz, now = pytz.timezone(settings.TZ), datetime.now(pytz.timezone(settings.TZ))
    time_windows = [(8, 14), (15, 23)]
    for i in range(runs_to_schedule):
        window_index = (completed_count + i) % len(time_windows)
        start_h, end_h = time_windows[window_index]
        run_time = None
        for _ in range(10):
            temp_run_time = now.replace(hour=random.randint(start_h, end_h-1), minute=random.randint(0, 59))
            if temp_run_time > now: run_time = temp_run_time; break
        if not run_time and window_index + 1 < len(time_windows):
            start_h, end_h = time_windows[window_index+1]
            run_time = now.replace(hour=random.randint(start_h, end_h-1), minute=random.randint(0, 59))
        if run_time:
            job_id = f"{TASK_ID_CHUANG_TA_BASE}{completed_count + i}"
            scheduler.add_job(trigger_chuang_ta, 'date', run_date=run_time, id=job_id)
            format_and_log("TASK", "自动闯塔", {'阶段': '任务已调度', '任务ID': job_id, '运行时间': run_time.strftime('%Y-%m-%d %H:%M:%S')})

def initialize(app):
    app.register_task(task_key="biguan", function=trigger_biguan_xiulian, command_name="立即闭关", help_text="...")
    app.register_task(task_key="dianmao", function=trigger_dianmao_chuangong, command_name="立即点卯", help_text="...")
    app.register_task(task_key="chuang_ta", function=trigger_chuang_ta, command_name="立即闯塔", help_text="...")
    app.register_task(task_key="update_inventory", function=update_inventory_cache, command_name="立即刷新背包", help_text="...")
    app.startup_checks.extend([
        check_biguan_startup, check_dianmao_startup, check_chuang_ta_startup, 
        check_inventory_refresh_startup, check_heartbeat_startup, check_active_heartbeat_startup
    ])
