# -*- coding: utf-8 -*-
import logging
import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from config import settings

# --- 恢复：直接创建并导出一个全局的、已配置好的调度器实例 ---
jobstores = {
    'default': SQLAlchemyJobStore(url=settings.SCHEDULER_DB)
}
scheduler = AsyncIOScheduler(
    jobstores=jobstores,
    timezone=pytz.timezone(settings.TZ),
    misfire_grace_time=3600
)
logging.info("全局任务调度器实例已创建。", extra={'log_type_key': 'SYSTEM'})

def shutdown():
    """安全地关闭调度器"""
    if scheduler.running:
        scheduler.shutdown()
