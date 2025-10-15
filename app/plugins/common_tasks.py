# -*- coding: utf-8 -*-
import logging
import random
import re
import sys
from datetime import date, datetime, time, timedelta

import pytz
from telethon.tl.functions.account import UpdateStatusRequest

from app import game_adaptor
from app.context import get_application
from app.data_manager import data_manager
from app.inventory_manager import inventory_manager
from app.logging_service import LogType, format_and_log
from app.task_scheduler import scheduler
from app.telegram_client import CommandTimeoutError
from app.utils import parse_cooldown_time, parse_inventory_text, resilient_task
from config import settings

TASK_ID_BIGUAN = 'biguan_xiulian_task'
STATE_KEY_BIGUAN = "biguan"
TASK_ID_CHUANG_TA_BASE = 'chuang_ta_task_'
STATE_KEY_CHUANG_TA = "chuang_ta"
TASK_ID_INVENTORY_REFRESH = 'inventory_refresh_task'

@resilient_task()
async def trigger_dianmao_chuangong(force_run=False):
    app = get_application()
    client = app.client
    format_and_log(LogType.TASK, "宗门点卯", {'阶段': '任务开始', '强制执行': force_run})
    sent_dianmao = None
    try:
        # NOTE: send_game_command_long_task is not a standard method. Assuming it exists.
        _sent, reply_dianmao = await client.send_game_command_request_response(game_adaptor.sect_check_in())
        sent_dianmao = _sent
        client.pin_message(sent_dianmao)
        format_and_log(LogType.TASK, "宗门点卯", {'阶段': '点卯指令', '返回': reply_dianmao.text.replace('\n', ' ')})
        
        max_attempts = 5
        for i in range(max_attempts):
            _sent_cg, reply_cg = await client.send_game_command_request_response(game_adaptor.sect_contribute_skill(), reply_to=sent_dianmao.id)
            format_and_log(LogType.TASK, "宗门点卯", {'阶段': f'传功尝试 {i+1}/{max_attempts}', '返回': reply_cg.text.replace('\n', ' ')})
            if "过于频繁" in reply_cg.text or "已经指点" in reply_cg.text or "今日次数已用完" in reply_cg.text:
                format_and_log(LogType.TASK, "宗门点卯", {'阶段': '传功已达上限', '详情': '任务链正常结束。'})
                if force_run: return "✅ **[立即点卯]** 任务已成功执行完毕（点卯和传功均已完成）。"
                return
        if force_run: return "✅ **[立即点卯]** 任务已成功执行完毕。"
    finally:
        if sent_dianmao:
            client.unpin_message(sent_dianmao)
            delay = settings.AUTO_DELETE_STRATEGIES.get('long_task', {}).get('delay_anchor', 30)
            client._schedule_message_deletion(sent_dianmao, delay, "宗门点卯(任务链结束)")

@resilient_task()
async def update_inventory_cache(force_run=False):
    app = get_application()
    client = app.client
    format_and_log(LogType.TASK, "刷新背包", {'阶段': '任务开始', '强制执行': force_run})
    try:
        _sent, reply = await client.send_game_command_request_response(game_adaptor.get_inventory())
        inventory = parse_inventory_text(reply)
        if inventory:
            await inventory_manager.set_inventory(inventory)
            format_and_log(LogType.TASK, "刷新背包", {'阶段': '任务成功', '详情': f'解析并校准了 {len(inventory)} 种物品。'})
            if force_run:
                return f"✅ **[校准背包]** 任务完成，已校准 {len(inventory)} 种物品。"
        else:
            raise ValueError("未能从游戏返回信息中解析到任何物品。")
    finally:
        # [逻辑修改] 移除此处的自调度逻辑，统一由 check_inventory_refresh_startup 管理
        if not force_run:
            format_and_log(LogType.TASK, "刷新背包", {'阶段': '任务完成'})


@resilient_task()
async def trigger_chuang_ta(force_run=False):
    app = get_application()
    client = app.client
    format_and_log(LogType.TASK, "自动闯塔", {'阶段': '任务开始', '强制执行': force_run})
    try:
        # [修改] 使用新的、健壮的等待函数
        _sent, final_reply = await client.send_and_wait_for_mention_reply(
            command=game_adaptor.challenge_tower(), 
            final_pattern=r"【试炼古塔 - 战报】"
        )
        if "【试炼古塔 - 战报】" in final_reply.text and "总收获" in final_reply.text:
            format_and_log(LogType.TASK, "自动闯塔", {'阶段': '成功', '详情': '事件将由事件总线处理'})
        else:
            format_and_log(LogType.WARNING, "自动闯塔", {'阶段': '解析失败', '原因': '未收到预期的战报格式', '返回': final_reply.text})
    finally:
        if not force_run and data_manager.db:
            today_str = date.today().isoformat()
            state = await data_manager.get_value(STATE_KEY_CHUANG_TA, is_json=True, default={"date": today_str, "completed_count": 0})
            if state.get("date") != today_str: state = {"date": today_str, "completed_count": 1}
            else: state["completed_count"] = state.get("completed_count", 0) + 1
            await data_manager.save_value(STATE_KEY_CHUANG_TA, state)
            format_and_log(LogType.TASK, "自动闯塔", {'阶段': '状态更新', '今日已完成': state["completed_count"]})

@resilient_task()
async def trigger_biguan_xiulian(force_run=False):
    app = get_application()
    client = app.client
    format_and_log(LogType.TASK, "闭关修炼", {'阶段': '任务开始', '强制执行': force_run})
    beijing_tz = pytz.timezone(settings.TZ)
    next_run_time = datetime.now(beijing_tz) + timedelta(minutes=15)
    try:
        _sent_msg, reply = await client.send_game_command_request_response(game_adaptor.meditate())
        cooldown = parse_cooldown_time(reply)
        if cooldown:
            jitter_config = settings.TASK_JITTER['biguan']
            jitter = random.uniform(jitter_config['min'], jitter_config['max'])
            next_run_time = datetime.now(beijing_tz) + cooldown + timedelta(seconds=jitter)
            format_and_log(LogType.TASK, "闭关修炼", {'阶段': '解析成功', '冷却时间': str(cooldown), '下次运行': next_run_time.strftime('%Y-%m-%d %H:%M:%S')})
        else:
            format_and_log(LogType.TASK, "闭关修炼", {'阶段': '解析失败', '详情': '未找到冷却时间，将在15分钟后重试。'})
    finally:
        if data_manager.db:
            scheduler.add_job(trigger_biguan_xiulian, 'date', run_date=next_run_time, id=TASK_ID_BIGUAN, replace_existing=True)
            await data_manager.save_value(STATE_KEY_BIGUAN, next_run_time.isoformat())
            format_and_log(LogType.TASK, "闭关修炼", {'阶段': '任务完成', '详情': f'已计划下次运行时间: {next_run_time.strftime("%Y-%m-%d %H:%M:%S")}'})

async def check_biguan_startup():
    if not settings.TASK_SWITCHES.get('biguan') or not data_manager.db: return
    if scheduler.get_job(TASK_ID_BIGUAN): return
    iso_str = await data_manager.get_value(STATE_KEY_BIGUAN)
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
                format_and_log(LogType.TASK, "宗门点卯", {'阶段': '调度计划', '任务': f'每日第{i+1}次', '运行时间': run_time.strftime('%Y-%m-%d %H:%M:%S')})
            except ValueError:
                format_and_log(LogType.SYSTEM, "配置错误", {'模块': '宗门点卯', '错误': f'时间格式不正确: {time_str}'}, level=logging.ERROR)

async def check_inventory_refresh_startup():
    """[调度优化] 刷新背包，作为高频核心数据，每天3-4次"""
    if settings.TASK_SWITCHES.get('inventory_refresh', True) and not scheduler.get_job(TASK_ID_INVENTORY_REFRESH):
        # 使用 interval 触发器，每 6-8 小时随机执行一次
        scheduler.add_job(
            update_inventory_cache, 'interval', 
            hours=random.randint(6, 8), 
            jitter=3600, # 增加1小时的随机抖动
            id=TASK_ID_INVENTORY_REFRESH,
            replace_existing=True
        )
        format_and_log(LogType.SYSTEM, "任务调度", {'任务': '自动刷新背包 (高频)', '状态': '已计划', '频率': '每6-8小时'})

async def check_chuang_ta_startup():
    if not settings.TASK_SWITCHES.get('chuang_ta', True) or not data_manager.db: return
    today_str = date.today().isoformat()
    state = await data_manager.get_value(STATE_KEY_CHUANG_TA, is_json=True, default={"date": "1970-01-01", "completed_count": 0})
    if state.get("date") != today_str:
        state = {"date": today_str, "completed_count": 0}; await data_manager.save_value(STATE_KEY_CHUANG_TA, state)
        format_and_log(LogType.TASK, "自动闯塔", {'阶段': '状态重置', '新的一天': today_str})
    completed_count = state.get("completed_count", 0)
    total_runs_per_day = 2
    for job in scheduler.get_jobs():
        if job.id.startswith(TASK_ID_CHUANG_TA_BASE): job.remove()
    if completed_count >= total_runs_per_day:
        format_and_log(LogType.TASK, "自动闯塔", {'阶段': '调度跳过', '原因': f'今日已完成 {completed_count} 次。'})
        return
    runs_to_schedule = total_runs_per_day - completed_count
    format_and_log(LogType.TASK, "自动闯塔", {'阶段': '调度计划', '今日待办': runs_to_schedule})
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
            format_and_log(LogType.TASK, "自动闯塔", {'阶段': '任务已调度', '任务ID': job_id, '运行时间': run_time.strftime('%Y-%m-%d %H:%M:%S')})

def initialize(app):
    app.register_task(task_key="biguan", function=trigger_biguan_xiulian, command_name="立即闭关", help_text="...")
    app.register_task(task_key="dianmao", function=trigger_dianmao_chuangong, command_name="立即点卯", help_text="...")
    app.register_task(task_key="chuang_ta", function=trigger_chuang_ta, command_name="立即闯塔", help_text="...")
    # [修改] 指令名改为 "校准背包"，更清晰
    app.register_task(task_key="update_inventory", function=update_inventory_cache, command_name="校准背包", help_text="...")
    
    app.startup_checks.extend([
        check_biguan_startup, check_dianmao_startup, check_chuang_ta_startup, 
        check_inventory_refresh_startup
    ])
