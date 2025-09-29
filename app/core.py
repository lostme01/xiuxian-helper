# -*- coding: utf-8 -*-
import asyncio
import logging
import logging.handlers
import pytz
import os
import sys
from config import settings
from app.task_scheduler import scheduler, shutdown
from app.telegram_client import TelegramClient
from app.redis_client import initialize_redis
from app import gemini_client
from app.plugins import (
    common_tasks, huangfeng_valley, taiyi_sect, 
    learning_tasks, xuangu_exam_solver, tianji_exam_solver,
    mojun_arrival
)
from app.logger import format_and_log, TimezoneFormatter
from app.commands import initialize_all_commands
from app.admin_commands import initialize_admin_commands
from app.context import set_application

class Application:
    def __init__(self):
        self.client: TelegramClient = None
        self.redis_db = None
        self.startup_checks = []
        set_application(self)
        
        self.setup_logging()
        
        format_and_log("SYSTEM", "应用初始化", {'阶段': '开始...'})
        format_and_log("SYSTEM", "组件初始化", {'组件': 'Redis', '状态': '开始连接...'})
        self.redis_db = initialize_redis()
        
        gemini_client.initialize_gemini()
        
        format_and_log("SYSTEM", "组件初始化", {'组件': 'Telegram 客户端', '状态': '开始实例化...'})
        self.client = TelegramClient()
        format_and_log("SYSTEM", "组件初始化", {'组件': 'Telegram 客户端', '状态': '实例化完成'})
        
    def setup_logging(self):
        print("开始配置日志系统...")
        root_logger = logging.getLogger()
        if root_logger.hasHandlers(): root_logger.handlers.clear()
        root_logger.setLevel(logging.INFO)
        console_formatter = logging.Formatter(fmt='%(message)s')
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(console_formatter)
        root_logger.addHandler(stream_handler)
        app_log_formatter = TimezoneFormatter(
            fmt='%(asctime)s - %(levelname)s:%(message)s', datefmt='%Y-%m-%d %H:%M:%S %Z', tz_name=settings.TZ
        )
        app_log_handler = logging.handlers.RotatingFileHandler(
            settings.LOG_FILE, maxBytes=settings.LOG_ROTATION_CONFIG['max_bytes'], 
            backupCount=settings.LOG_ROTATION_CONFIG['backup_count'], encoding='utf-8')
        app_log_handler.setFormatter(app_log_formatter)
        root_logger.addHandler(app_log_handler)
        logging.getLogger('apscheduler').setLevel(logging.ERROR)
        logging.getLogger('telethon').setLevel(logging.WARNING)
        logging.getLogger('asyncio').setLevel(logging.WARNING)
        raw_logger = logging.getLogger('raw_messages')
        raw_logger.setLevel(logging.INFO)
        raw_logger.propagate = False
        if raw_logger.hasHandlers(): raw_logger.handlers.clear()
        raw_log_formatter = TimezoneFormatter(
            fmt='%(asctime)s\n%(message)s\n' + '-'*50, datefmt='%Y-%m-%d %H:%M:%S %Z', tz_name=settings.TZ
        )
        raw_log_handler = logging.handlers.RotatingFileHandler(
            settings.RAW_LOG_FILE, maxBytes=settings.LOG_ROTATION_CONFIG['max_bytes'], 
            backupCount=settings.LOG_ROTATION_CONFIG['backup_count'], encoding='utf-8')
        raw_log_handler.setFormatter(raw_log_formatter)
        raw_logger.addHandler(raw_log_handler)
        print("日志系统配置完成。")
        
    def load_plugins_and_commands(self):
        format_and_log("SYSTEM", "插件加载", {'阶段': '开始加载任务插件...'})
        
        format_and_log("SYSTEM", "插件加载", {'插件': '通用任务', '状态': '初始化...'})
        # 在这里收集启动检查任务
        self.startup_checks.extend(common_tasks.initialize_tasks() or [])
        format_and_log("SYSTEM", "插件加载", {'插件': '通用任务', '状态': '已加载'})

        format_and_log("SYSTEM", "插件加载", {'插件': '学习任务', '状态': '初始化...'})
        self.startup_checks.extend(learning_tasks.initialize_tasks() or [])
        format_and_log("SYSTEM", "插件加载", {'插件': '学习任务', '状态': '已加载'})
        
        if settings.SECT_NAME == '黄枫谷':
            format_and_log("SYSTEM", "插件加载", {'插件': '黄枫谷专属', '状态': '初始化...'})
            self.startup_checks.extend(huangfeng_valley.initialize_tasks() or [])
            format_and_log("SYSTEM", "插件加载", {'插件': '黄枫谷专属', '状态': '已加载'})
        elif settings.SECT_NAME == '太一门':
            format_and_log("SYSTEM", "插件加载", {'插件': '太一门专属', '状态': '初始化...'})
            self.startup_checks.extend(taiyi_sect.initialize_tasks() or [])
            format_and_log("SYSTEM", "插件加载", {'插件': '太一门专属', '状态': '已加载'})
        
        if self.redis_db and settings.EXAM_SOLVER_CONFIG.get('enabled'):
            format_and_log("SYSTEM", "插件加载", {'插件': '玄骨校考作答', '状态': '初始化...'})
            xuangu_exam_solver.initialize_plugin(self.client, self.redis_db)
            format_and_log("SYSTEM", "插件加载", {'插件': '玄骨校考作答', '状态': '已加载'})

            format_and_log("SYSTEM", "插件加载", {'插件': '天机考验作答', '状态': '初始化...'})
            tianji_exam_solver.initialize_plugin(self.client, self.redis_db)
            format_and_log("SYSTEM", "插件加载", {'插件': '天机考验作答', '状态': '已加载'})
        
        format_and_log("SYSTEM", "插件加载", {'插件': '魔君降临', '状态': '初始化...'})
        mojun_arrival.initialize_plugin(self.client)
        
        format_and_log("SYSTEM", "插件加载", {'阶段': '任务插件加载完毕。开始加载指令集...'})
        
        format_and_log("SYSTEM", "插件加载", {'模块': '游戏指令 (commands)', '状态': '初始化...'})
        initialize_all_commands(self.client)
        format_and_log("SYSTEM", "插件加载", {'模块': '游戏指令 (commands)', '状态': '已加载'})

        format_and_log("SYSTEM", "插件加载", {'模块': '管理指令 (admin_commands)', '状态': '初始化...'})
        initialize_admin_commands(self.client)
        format_and_log("SYSTEM", "插件加载", {'模块': '管理指令 (admin_commands)', '状态': '已加载'})

        format_and_log("SYSTEM", "插件加载", {'阶段': '所有指令加载完毕'})

    async def run(self):
        try:
            format_and_log("SYSTEM", "核心服务", {'服务': '任务调度器 (APScheduler)', '状态': '启动...'})
            scheduler.start()
            format_and_log("SYSTEM", "核心服务", {'服务': '任务调度器 (APScheduler)', '状态': '启动完成'})
            
            format_and_log("SYSTEM", "核心服务", {'服务': 'Telegram 客户端', '状态': '启动并连接...'})
            await self.client.start()
            
            format_and_log("SYSTEM", "应用初始化", {'阶段': '客户端已登录，开始加载插件...'})
            self.load_plugins_and_commands()
            
            await self.client.warm_up_entity_cache()
            
            format_and_log("SYSTEM", "核心服务", {'阶段': '执行启动后任务检查...'})
            # --- 核心修复：只在这里执行已收集的检查，不再重复初始化 ---
            if self.startup_checks:
                await asyncio.gather(*(check() for check in self.startup_checks if check))
            format_and_log("SYSTEM", "核心服务", {'阶段': '启动后任务检查完毕'})
            
            await self.client.send_admin_notification("✅ **助手已成功启动并在线**")
            format_and_log("SYSTEM", "核心服务", {'阶段': '应用已准备就绪，进入监听状态'})
            await self.client.run_until_disconnected()
        except Exception:
            logging.critical("应用启动或运行过程中发生严重错误:", exc_info=True)
        finally:
            if self.client and self.client.is_connected():
                await self.client.disconnect()
            shutdown()
            format_and_log("SYSTEM", "核心服务", {'阶段': '应用已关闭'})
