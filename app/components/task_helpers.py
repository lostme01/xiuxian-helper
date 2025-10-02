# -*- coding: utf-8 -*-
import functools
import random
import pytz
from datetime import datetime, timedelta
import logging

from app.state_manager import get_state, set_state
from app.logger import format_and_log
from app.context import get_application

def rescheduling_task(task_id: str, state_key: str, default_retry: timedelta):
    """
    一个装饰器，自动处理发送指令、解析冷却、异常处理和重新调度的通用逻辑。
    被装饰的函数应该是异步的，并且在成功时返回一个 timedelta 对象（冷却时间）。
    """
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(force_run=False):
            app = get_application()
            scheduler = app.scheduler
            
            format_and_log("TASK", func.__name__, {'阶段': '任务开始', '强制执行': force_run})
            beijing_tz = pytz.timezone(app.settings.TZ)
            next_run_time = datetime.now(beijing_tz) + default_retry

            try:
                cooldown = await func(force_run=force_run)
                
                if cooldown and isinstance(cooldown, timedelta):
                    # 可以在这里加入通用的随机延迟（jitter）
                    jitter = random.uniform(30, 90) 
                    next_run_time = datetime.now(beijing_tz) + cooldown + timedelta(seconds=jitter)
                    format_and_log("TASK", func.__name__, {'阶段': '解析成功', '冷却时间': str(cooldown), '下次运行': next_run_time.strftime('%Y-%m-%d %H:%M:%S')})
                else:
                    format_and_log("TASK", func.__name__, {'阶段': '解析失败', '详情': f'未返回有效冷却时间，将在约 {default_retry.total_seconds() / 60:.0f} 分钟后重试。'})

            except Exception as e:
                format_and_log("TASK", func.__name__, {'阶段': '任务异常', '错误': str(e)}, level=logging.ERROR)
            
            finally:
                scheduler.add_job(wrapper, 'date', run_date=next_run_time, id=task_id, replace_existing=True)
                set_state(state_key, next_run_time.isoformat())
                format_and_log("TASK", func.__name__, {'阶段': '任务完成', '详情': f'已计划下次运行时间: {next_run_time.strftime("%Y-%m-%d %H:%M:%S")}'})

        return wrapper
    return decorator


async def schedule_task_on_startup(task_id: str, state_key: str, task_func, **kwargs):
    """
    通用的任务启动检查和调度函数。
    - task_id: 任务在调度器中的唯一ID
    - state_key: 任务在状态管理器中的键
    - task_func: 要执行的任务函数
    - kwargs: 传递给 scheduler.add_job 的其他参数 (如 'interval', 'cron' 等)
    """
    app = get_application()
    scheduler = app.scheduler
    
    if scheduler.get_job(task_id):
        return

    # 检查是否有 'interval' 或 'cron' 类型的周期任务
    if 'interval' in kwargs or 'cron' in kwargs:
         scheduler.add_job(task_func, id=task_id, **kwargs)
         format_and_log("SYSTEM", "周期任务调度", {'任务ID': task_id, '类型': kwargs.get('trigger', 'interval')})
         return

    # 以下是处理基于冷却时间的 'date' 类型任务
    iso_str = get_state(state_key)
    beijing_tz = pytz.timezone(app.settings.TZ)
    state_time = datetime.fromisoformat(iso_str).astimezone(beijing_tz) if iso_str else None
    now = datetime.now(beijing_tz)
    
    # 如果状态时间存在且在未来，则按状态时间调度；否则立即执行一次（它会在finally中自己调度下一次）
    if state_time and state_time > now:
        scheduler.add_job(task_func, 'date', run_date=state_time, id=task_id)
        format_and_log("SYSTEM", "恢复任务调度", {'任务ID': task_id, '恢复时间': state_time.strftime('%Y-%m-%d %H:%M:%S')})
    else:
        # 立即执行一次
        await task_func(force_run=True)
