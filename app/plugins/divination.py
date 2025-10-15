# -*- coding: utf-8 -*-
import re
import asyncio
import random
from datetime import date, datetime, time, timedelta

import pytz
from app import game_adaptor
from app.constants import STATE_KEY_DIVINATION, TASK_ID_DIVINATION_BASE
from app.context import get_application
from app.data_manager import data_manager
from app.logging_service import LogType, format_and_log
from app.task_scheduler import scheduler
from app.telegram_client import CommandTimeoutError
from app.utils import create_error_reply, progress_manager
from config import settings
from app.character_stats_manager import stats_manager

HELP_TEXT_DIVINATION = """☯️ **卜筮问天**
**说明**: 消耗修为，窥探今日机缘，可能会有意外的收获或损失。
**用法**: `,卜筮问天` (或 `,卜筮`)
"""

async def trigger_divination_task(force_run=False):
    """[重构] 自动执行卜筮问天，并处理天道反噬"""
    app = get_application()
    client = app.client
    
    if not force_run:
        format_and_log(LogType.TASK, "自动卜筮", {'阶段': '开始执行'})
    
    try:
        # [修改] 不再是发后不理，需要等待初始回复来检查是否被反噬
        _sent, initial_reply = await client.send_game_command_request_response(game_adaptor.divination())
        
        # 检查天道反噬，并预先扣除修为
        if "天道反噬" in initial_reply.text:
            cost_match = re.search(r"消耗了\s*\*\*(\d+)\*\*\s*点修为", initial_reply.text)
            if cost_match:
                cost = int(cost_match.group(1))
                await stats_manager.remove_cultivation(cost)
                format_and_log(LogType.TASK, "自动卜筮", {'阶段': '天道反噬', '消耗修为': cost})
                # 发送通知
                await client.send_admin_notification(f"☯️ **卜筮消耗 (@{client.me.username})**: 因天道反噬，消耗修为 **{cost}** 点。")

        # 最终的卦象结果将由事件系统独立捕获和处理
        if force_run:
            return "✅ **[卜筮问天]** 指令已发送。\n最终结果将通过事件系统推送，请在控制群或私聊中查看。"

    except Exception as e:
        if force_run:
            raise e
        else:
            format_and_log(LogType.ERROR, "自动卜筮失败", {'错误': str(e)})


async def _cmd_divination(event, parts):
    """处理用户指令，执行卜筮问天功能"""
    async with progress_manager(event, "⏳ 正在发送 `.卜筮问天` 指令...") as progress:
        final_text = await trigger_divination_task(force_run=True)
        await progress.update(final_text)

async def check_divination_startup():
    """[新] 启动时检查并调度每日5次的卜筮任务"""
    if not settings.TASK_SWITCHES.get('divination'):
        return
        
    today_str = date.today().isoformat()
    # 从Redis加载今天的执行记录
    state = await data_manager.get_value(STATE_KEY_DIVINATION, is_json=True, default={"date": "1970-01-01", "completed_count": 0})
    
    # 如果是新的一天，重置计数
    if state.get("date") != today_str:
        state = {"date": today_str, "completed_count": 0}
        await data_manager.save_value(STATE_KEY_DIVINATION, state)
        format_and_log(LogType.TASK, "自动卜筮", {'阶段': '状态重置', '新的一天': today_str})

    completed_count = state.get("completed_count", 0)
    total_runs_per_day = 5
    
    # 移除旧的计划任务
    for job in scheduler.get_jobs():
        if job.id.startswith(TASK_ID_DIVINATION_BASE):
            job.remove()
            
    if completed_count >= total_runs_per_day:
        format_and_log(LogType.TASK, "自动卜筮", {'阶段': '调度跳过', '原因': f'今日已完成 {completed_count}/{total_runs_per_day} 次。'})
        return

    runs_to_schedule = total_runs_per_day - completed_count
    format_and_log(LogType.TASK, "自动卜筮", {'阶段': '调度计划', '今日待办': runs_to_schedule})
    
    beijing_tz = pytz.timezone(settings.TZ)
    now = datetime.now(beijing_tz)
    
    # 将一天分为5个时间窗口
    window_size_hours = 24 / total_runs_per_day # 4.8 hours
    
    for i in range(runs_to_schedule):
        window_index = completed_count + i
        start_h = window_size_hours * window_index
        end_h = window_size_hours * (window_index + 1)
        
        # 将小时转换为整数和小数部分
        start_hour_int = int(start_h)
        start_minute_int = int((start_h - start_hour_int) * 60)
        end_hour_int = int(end_h) -1 
        
        run_time = None
        # 尝试在当前时间之后找到一个合适的执行时间
        for _ in range(10): # 尝试10次以增加找到合适时间的概率
            rand_hour = random.randint(start_hour_int, end_hour_int)
            rand_min = random.randint(0, 59)
            
            # 确保随机时间在窗口内
            if rand_hour == start_hour_int and rand_min < start_minute_int:
                continue

            temp_run_time = now.replace(hour=rand_hour, minute=rand_min, second=random.randint(0,59), microsecond=0)
            if temp_run_time > now:
                run_time = temp_run_time
                break
        
        # 如果在今天的所有剩余窗口中都找不到时间，则安排到明天
        if not run_time:
            run_time = (now + timedelta(days=1)).replace(hour=random.randint(start_hour_int, end_hour_int), minute=random.randint(0, 59))

        job_id = f"{TASK_ID_DIVINATION_BASE}{window_index}"
        
        # 创建一个包装函数来更新执行计数
        async def job_wrapper():
            await trigger_divination_task()
            current_state = await data_manager.get_value(STATE_KEY_DIVINATION, is_json=True)
            current_state["completed_count"] += 1
            await data_manager.save_value(STATE_KEY_DIVINATION, current_state)

        scheduler.add_job(job_wrapper, 'date', run_date=run_time, id=job_id)
        format_and_log(LogType.TASK, "自动卜筮", {'阶段': '任务已调度', '任务ID': job_id, '运行时间': run_time.strftime('%Y-%m-%d %H:%M:%S')})


def initialize(app):
    """注册指令到应用"""
    app.register_command(
        name="卜筮问天",
        handler=_cmd_divination,
        help_text="☯️ 消耗修为，窥探今日机缘。",
        category="动作",
        aliases=["卜筮"],
        usage=HELP_TEXT_DIVINATION
    )
    app.startup_checks.append(check_divination_startup)
