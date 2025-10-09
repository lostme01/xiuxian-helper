# -*- coding: utf-8 -*-
import asyncio
import random
import pytz
from datetime import datetime, timedelta
from telethon.tl.functions.account import UpdateStatusRequest
from app.context import get_application
from app.logging_service import LogType, format_and_log
from config import settings
from app.task_scheduler import scheduler

HEARTBEAT_CONFIG = settings.HEARTBEAT_CONFIG

async def active_heartbeat():
    """主动心跳：通过更新在线状态来保持会话活跃"""
    if not HEARTBEAT_CONFIG.get('active_enabled'):
        return
    
    app = get_application()
    try:
        await app.client.client(UpdateStatusRequest(offline=False))
        format_and_log(LogType.DEBUG, "心跳服务", {'类型': '主动心跳', '状态': '成功'})
    except Exception as e:
        format_and_log(LogType.WARNING, "心跳服务", {'类型': '主动心跳', '状态': '失败', '错误': str(e)})

async def passive_heartbeat():
    """被动心跳：检查与Telegram的最后通信时间，如果过长则发出警报"""
    if not HEARTBEAT_CONFIG.get('passive_enabled'):
        return
        
    app = get_application()
    now = datetime.now(pytz.timezone(settings.TZ))
    time_since_last_update = (now - app.client.last_update_timestamp).total_seconds()
    
    threshold = HEARTBEAT_CONFIG.get('passive_threshold_minutes', 30) * 60
    
    if time_since_last_update > threshold:
        format_and_log(LogType.WARNING, "心跳服务-警报", {
            '类型': '被动心跳',
            '问题': '可能已与Telegram失联',
            '最后通信距今': f"{time_since_last_update:.0f} 秒 (阈值: {threshold} 秒)"
        })
        await app.client.send_admin_notification(
            f"⚠️ **连接健康警报**\n\n"
            f"助手似乎已超过 **{int(threshold/60)}** 分钟未收到来自 Telegram 的任何消息。\n"
            f"连接可能已中断，请检查程序日志或网络状态。"
        )
        # 发送一次警报后，更新时间戳以避免短时间内重复发送
        app.client.last_update_timestamp = now

async def daily_dialog_sync():
    """每日全量同步：刷新对话列表以更新实体缓存"""
    if not HEARTBEAT_CONFIG.get('sync_enabled'):
        return
        
    app = get_application()
    format_and_log(LogType.TASK, "每日同步", {'阶段': '开始'})
    try:
        # 迭代少量对话即可触发 Telethon 的内部更新机制
        async for _ in app.client.client.iter_dialogs(limit=20):
            pass
        format_and_log(LogType.TASK, "每日同步", {'阶段': '成功'})
    except Exception as e:
        format_and_log(LogType.ERROR, "每日同步", {'阶段': '失败', '错误': str(e)})


def initialize(app):
    """初始化并调度所有心跳和维护任务"""
    if HEARTBEAT_CONFIG.get('active_enabled'):
        interval = HEARTBEAT_CONFIG.get('active_interval_minutes', 10)
        scheduler.add_job(
            active_heartbeat, 'interval', minutes=interval, 
            id='active_heartbeat_task', replace_existing=True
        )
        format_and_log(LogType.SYSTEM, "任务调度", {'任务': '主动心跳', '频率': f'每 {interval} 分钟'})

    if HEARTBEAT_CONFIG.get('passive_enabled'):
        interval = HEARTBEAT_CONFIG.get('passive_check_interval_minutes', 5)
        scheduler.add_job(
            passive_heartbeat, 'interval', minutes=interval,
            id='passive_heartbeat_task', replace_existing=True
        )
        format_and_log(LogType.SYSTEM, "任务调度", {'任务': '被动心跳监测', '频率': f'每 {interval} 分钟'})
        
    if HEARTBEAT_CONFIG.get('sync_enabled'):
        run_time_str = HEARTBEAT_CONFIG.get('sync_run_time', '04:30')
        hour, minute = map(int, run_time_str.split(':'))
        scheduler.add_job(
            daily_dialog_sync, 'cron', hour=hour, minute=minute, 
            jitter=300, id='daily_dialog_sync_task', replace_existing=True
        )
        format_and_log(LogType.SYSTEM, "任务调度", {'任务': '每日全量同步', '计划时间': f'每日 {run_time_str} 左右'})
