# -*- coding: utf-8 -*-
import sys
import asyncio
import pytz
from datetime import datetime
from config import settings
from app.context import get_application, get_scheduler

async def logic_restart_service() -> str:
    """安排服务重启"""
    asyncio.create_task(_shutdown_and_exit())
    return "✅ 服务将在2秒后重启..."

async def _shutdown_and_exit():
    await asyncio.sleep(2)
    sys.exit(0)

async def logic_get_task_list() -> str:
    """获取计划任务列表"""
    scheduler = get_scheduler()
    jobs = scheduler.get_jobs()
    if not jobs: return "🗓️ 当前没有正在计划中的任务。"
    
    # 任务 ID 到中文名称的映射
    job_map = {
        'biguan_xiulian_task': '闭关修炼', 'heartbeat_check_task': '被动心跳',
        'active_status_heartbeat_task': '主动心跳', 'zongmen_dianmao_task_0': '宗门点卯(1)',
        'zongmen_dianmao_task_1': '宗门点卯(2)','taiyi_yindao_task': '太一门·引道',
        'huangfeng_garden_task': '黄枫谷·小药园','inventory_refresh_task': '刷新背包',
        'learn_recipes_task': '学习图纸丹方','chuang_ta_task_0': '自动闯塔(1)',
        'chuang_ta_task_1': '自动闯塔(2)', 'sect_treasury_daily_task': '每日更新宝库'
    }
    beijing_tz = pytz.timezone(settings.TZ)
    reply_text = "🗓️ **当前计划任务列表**:\n"
    # 按下次运行时间排序
    sorted_jobs = sorted(jobs, key=lambda j: j.next_run_time or datetime.max.replace(tzinfo=pytz.utc))
    
    for job in sorted_jobs:
        if job.id.startswith('delete_msg_'): continue
        job_name = job_map.get(job.id, job.id)
        if job.next_run_time:
            next_run = job.next_run_time.astimezone(beijing_tz).strftime('%Y-%m-%d %H:%M:%S')
            reply_text += f"\n- **{job_name}**\n  `下次运行:` {next_run}"
            
    return reply_text

async def logic_reload_tasks() -> str:
    """重载所有周期性任务"""
    app = get_application()
    scheduler = get_scheduler()
    
    # 移除所有非删除任务的作业
    for job in scheduler.get_jobs():
        if not job.id.startswith('delete_msg_'):
            job.remove()
            
    # 重新执行所有启动检查函数，这将重新调度任务
    if app.startup_checks:
        await asyncio.gather(*(check() for check in app.startup_checks if check))
        
    return "✅ 所有周期任务已根据最新配置重新加载。"
