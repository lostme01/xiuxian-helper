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
    
    # [优化] 补全所有已知任务的汉化
    job_map = {
        'biguan_xiulian_task': '闭关修炼',
        'active_heartbeat_task': '主动心跳',
        'passive_heartbeat_task': '被动心跳监测',
        'daily_dialog_sync_task': '每日对话同步',
        'zongmen_dianmao_task_0': '宗门点卯 (任务1)',
        'zongmen_dianmao_task_1': '宗门点卯 (任务2)',
        'taiyi_yindao_task': '太一门·引道',
        'huangfeng_garden_task': '黄枫谷·小药园',
        'inventory_refresh_task': '刷新背包',
        'learn_recipes_task': '自动学习图纸丹方',
        'chuang_ta_task_0': '自动闯塔 (任务1)',
        'chuang_ta_task_1': '自动闯塔 (任务2)',
        'sect_treasury_daily_task': '每日更新宝库',
        'formation_update_task_0': '自动更新阵法 (任务1)',
        'formation_update_task_1': '自动更新阵法 (任务2)',
        'auto_resource_management_task': '智能资源管理',
        'auto_knowledge_sharing_task': '自动化知识共享',
        'knowledge_timeout_checker_task': '知识共享超时检查',
        'crafting_timeout_checker_task': '智能炼制超时检查',
    }
    beijing_tz = pytz.timezone(settings.TZ)
    reply_text = "🗓️ **当前计划任务列表**:\n"
    # 按下次运行时间排序
    sorted_jobs = sorted(jobs, key=lambda j: j.next_run_time or datetime.max.replace(tzinfo=pytz.utc))
    
    for job in sorted_jobs:
        if job.id.startswith('delete_msg_'): continue
        job_name = job_map.get(job.id, job.id) # 如果没找到翻译，则显示原始ID
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
