# -*- coding: utf-8 -*-
import logging
import random
import pytz
import asyncio
import sys
from datetime import datetime, timedelta, date, time
from app.state_manager import get_state, set_state
from app.utils import parse_cooldown_time, parse_inventory_text
from config import settings
from app.logger import format_and_log
from app.task_scheduler import scheduler
from telethon.tl.functions.account import UpdateStatusRequest
from app.telegram_client import CommandTimeoutError
from app.context import get_application

TASK_ID_BIGUAN = 'biguan_xiulian_task'
STATE_KEY_BIGUAN = "biguan"
TASK_ID_HEARTBEAT = 'heartbeat_check_task'
TASK_ID_CHUANG_TA_BASE = 'chuang_ta_task_'
STATE_KEY_CHUANG_TA = "chuang_ta"
TASK_ID_INVENTORY_REFRESH = 'inventory_refresh_task'
STATE_KEY_INVENTORY = "inventory"
TASK_ID_ACTIVE_HEARTBEAT = 'active_status_heartbeat_task'

# --- 改造：在超时或失败时返回明确的错误信息 ---
async def trigger_dianmao_chuangong(force_run=False):
    client = get_application().client
    format_and_log("TASK", "宗门点卯", {'阶段': '任务开始', '强制执行': force_run})
    sent_dianmao = None
    try:
        sent_dianmao, reply_dianmao = await client.send_game_command_long_task(".宗门点卯")
        client.pin_message(sent_dianmao)

        format_and_log("TASK", "宗门点卯", {'阶段': '点卯指令', '返回': reply_dianmao.text.replace('\n', ' ')})

        if "已经点过卯" in reply_dianmao.text or "过于频繁" in reply_dianmao.text:
            return "✅ **[立即点卯]** 任务完成（今日已完成）。"

        chuangong_commands = [".宗门传功"] * 3
        last_message = reply_dianmao
        for i, command in enumerate(chuangong_commands):
            try:
                _sent_cg, reply_cg = await client.send_game_command_request_response(command, reply_to=last_message.id)
                last_message = reply_cg
                format_and_log("TASK", "宗门点卯", {'阶段': f'传功 {i+1}/3', '返回': reply_cg.text.replace('\n', ' ')})
                if "过于频繁" in reply_cg.text:
                    format_and_log("TASK", "宗门点卯", {'阶段': '传功中止', '原因': '传功次数已达上限。'})
                    break
            except CommandTimeoutError:
                format_and_log("TASK", "宗门点卯", {'阶段': f'传功 {i+1}/3 失败', '原因': '等待回复超时'}, level=logging.WARNING)
                return f"⚠️ **[立即点卯]** 传功第 {i+1} 次时超时，任务提前结束。"
        
        return "✅ **[立即点卯]** 任务已成功执行完毕。"

    except CommandTimeoutError:
         format_and_log("TASK", "宗门点卯", {'阶段': '任务失败', '原因': '等待点卯初始回复超时'}, level=logging.ERROR)
         return "❌ **[立即点卯]** 任务失败：等待游戏机器人回复超时。"
    except Exception as e:
        format_and_log("TASK", "宗门点卯", {'阶段': '任务失败', '原因': f'执行过程中出错: {e}'}, level=logging.ERROR)
        return f"❌ **[立即点卯]** 任务执行失败: `{e}`"
    finally:
        if sent_dianmao:
            client.unpin_message(sent_dianmao)
            client._schedule_message_deletion(sent_dianmao, 30, "宗门点卯(任务链结束)")

# --- 改造：在超时或失败时返回明确的错误信息 ---
async def update_inventory_cache(force_run=False):
    client = get_application().client
    format_and_log("TASK", "刷新背包", {'阶段': '任务开始', '强制执行': force_run})
    try:
        _sent, reply = await client.send_game_command_request_response(".储物袋")
        inventory = parse_inventory_text(reply)
        if inventory:
            set_state(STATE_KEY_INVENTORY, inventory)
            format_and_log("TASK", "刷新背包", {'阶段': '任务成功', '详情': f'解析并缓存了 {len(inventory)} 种物品。'})
            return f"✅ **[立即刷新背包]** 任务完成，已缓存 {len(inventory)} 种物品。"
        else:
            format_and_log("TASK", "刷新背包", {'阶段': '任务失败', '原因': '未能解析到任何物品'}, level=logging.WARNING)
            return "⚠️ **[立即刷新背包]** 任务失败：未能从游戏返回信息中解析到任何物品。"
    except CommandTimeoutError:
         format_and_log("TASK", "刷新背包", {'阶段': '任务失败', '原因': '等待回复超时'}, level=logging.ERROR)
         return "❌ **[立即刷新背包]** 任务失败：等待游戏机器人回复超时。"
    except Exception as e:
        format_and_log("TASK", "刷新背包", {'阶段': '任务异常', '错误': str(e)}, level=logging.ERROR)
        return f"❌ **[立即刷新背包]** 任务执行异常: `{e}`"

async def active_status_heartbeat():
    # ... (此函数内容不变)
    client = get_application().client
    if client and client.is_connected():
        await client.client(UpdateStatusRequest(offline=False))

async def heartbeat_check():
    # ... (此函数内容不变)
    client = get_application().client
    heartbeat_timeout_seconds = settings.HEARTBEAT_TIMEOUT
    time_since_last_update = datetime.now(pytz.timezone(settings.TZ)) - client.last_update_timestamp
    if time_since_last_update > timedelta(seconds=heartbeat_timeout_seconds):
        format_and_log("SYSTEM", "心跳检查", {'状态': '超时', '详情': f'超过 {heartbeat_timeout_seconds} 秒无活动，准备重启...'}, level=logging.CRITICAL)
        await client.send_admin_notification(f"🚨 **告警：助手会话可能已沉睡，正在自动重启...**")
        await asyncio.sleep(2); sys.exit(1)

async def trigger_chuang_ta(force_run=False):
    # ... (此函数内容不变)
    format_and_log("TASK", "自动闯塔", {'阶段': '发送指令', '强制执行': force_run})
    await get_application().client.send_game_command_fire_and_forget(".闯塔")
    if not force_run:
        today_str = date.today().isoformat()
        state = get_state(STATE_KEY_CHUANG_TA, is_json=True, default={"date": today_str, "completed_count": 0})
        if state.get("date") != today_str: state = {"date": today_str, "completed_count": 1}
        else: state["completed_count"] = state.get("completed_count", 0) + 1
        set_state(STATE_KEY_CHUANG_TA, state)
        format_and_log("TASK", "自动闯塔", {'阶段': '状态更新', '今日已完成': state["completed_count"]})

async def trigger_biguan_xiulian(force_run=False):
    # ... (此函数内容不变)
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
            format_and_log("TASK", "闭关修炼", {'阶段': '解析失败', '详情': '未找到冷却时间，将在15分钟后重试。', '原始返回': reply.text.replace('\n', ' ')})
    except (CommandTimeoutError, Exception) as e:
        format_and_log("TASK", "闭关修炼", {'阶段': '任务异常', '错误': str(e)}, level=logging.ERROR)
    finally:
        scheduler.add_job(trigger_biguan_xiulian, 'date', run_date=next_run_time, id=TASK_ID_BIGUAN, replace_existing=True)
        set_state(STATE_KEY_BIGUAN, next_run_time.isoformat())
        format_and_log("TASK", "闭关修炼", {'阶段': '任务完成', '详情': f'已计划下次运行时间: {next_run_time.strftime("%Y-%m-%d %H:%M:%S")}'})

async def check_biguan_startup():
    # ... (此函数内容不变)
    if not settings.TASK_SWITCHES.get('biguan'): return
    if scheduler.get_job(TASK_ID_BIGUAN): return
    iso_str = get_state(STATE_KEY_BIGUAN)
    beijing_tz = pytz.timezone(settings.TZ)
    state_time = datetime.fromisoformat(iso_str).astimezone(beijing_tz) if iso_str else None
    if state_time and state_time > datetime.now(beijing_tz):
        scheduler.add_job(trigger_biguan_xiulian, 'date', run_date=state_time, id=TASK_ID_BIGUAN)
    else: await trigger_biguan_xiulian(force_run=True)
async def check_dianmao_startup():
    # ... (此函数内容不变)
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
    # ... (此函数内容不变)
    if not scheduler.get_job(TASK_ID_ACTIVE_HEARTBEAT):
        scheduler.add_job(active_status_heartbeat, 'interval', minutes=5, id=TASK_ID_ACTIVE_HEARTBEAT)
async def check_heartbeat_startup():
    # ... (此函数内容不变)
    if not scheduler.get_job(TASK_ID_HEARTBEAT):
        scheduler.add_job(heartbeat_check, 'interval', minutes=15, id=TASK_ID_HEARTBEAT)
async def check_inventory_refresh_startup():
    # ... (此函数内容不变)
    if settings.TASK_SWITCHES.get('inventory_refresh', True) and not scheduler.get_job(TASK_ID_INVENTORY_REFRESH):
        scheduler.add_job(update_inventory_cache, 'interval', hours=6, jitter=3600, id=TASK_ID_INVENTORY_REFRESH)
async def check_chuang_ta_startup():
    # ... (此函数内容不变)
    if not settings.TASK_SWITCHES.get('chuang_ta', True): return
    today_str = date.today().isoformat()
    state = get_state(STATE_KEY_CHUANG_TA, is_json=True, default={"date": "1970-01-01", "completed_count": 0})
    if state.get("date") != today_str:
        state = {"date": today_str, "completed_count": 0}; set_state(STATE_KEY_CHUANG_TA, state)
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
    # ... (此函数内容不变)
    app.register_task(task_key="biguan", function=trigger_biguan_xiulian, command_name="立即闭关", help_text="...")
    app.register_task(task_key="dianmao", function=trigger_dianmao_chuangong, command_name="立即点卯", help_text="...")
    app.register_task(task_key="chuang_ta", function=trigger_chuang_ta, command_name="立即闯塔", help_text="...")
    app.register_task(task_key="update_inventory", function=update_inventory_cache, command_name="立即刷新背包", help_text="...")
    app.startup_checks.extend([
        check_biguan_startup, check_dianmao_startup, check_chuang_ta_startup, 
        check_inventory_refresh_startup, check_heartbeat_startup, check_active_heartbeat_startup
    ])

