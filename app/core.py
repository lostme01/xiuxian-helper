# -*- coding: utf-8 -*-
import asyncio
import logging
import logging.handlers
import pytz
import importlib
import os
from datetime import datetime
from config import settings
from app.task_scheduler import scheduler, shutdown
from app.telegram_client import TelegramClient
from app.redis_client import initialize_redis
from app.plugins import (
    common_tasks, huangfeng_valley, taiyi_sect, 
    learning_tasks, exam_solver, tianji_exam_solver
)
from app.logger import format_and_log

class Application:
    def __init__(self):
        self.setup_logging()
        format_and_log("SYSTEM", "系统初始化", {'状态': '应用开始初始化...'})
        
        self.redis_db = initialize_redis()
        
        self.startup_checks = []
        self.client = TelegramClient()
        
        # *** 新增：启动时检查关键配置 ***
        self.startup_notifications = []
        self._check_critical_configs()
        
        self.load_plugins_and_commands()
        format_and_log("SYSTEM", "系统初始化", {'状态': '所有模块加载完毕。'})

    def _check_critical_configs(self):
        """检查所有关键配置，并将缺失项记录到日志和通知列表"""
        # 检查 Redis 配置
        if not settings.REDIS_CONFIG.get('enabled'):
            msg = "未配置 Redis，所有答题功能将禁用。"
            self.startup_notifications.append(msg)
            format_and_log("SYSTEM", "配置检查", {'问题': msg}, level=logging.WARNING)

        # 检查答题功能配置
        if settings.EXAM_SOLVER_CONFIG.get('enabled') or settings.TIANJI_EXAM_CONFIG.get('enabled'):
            if not self.redis_db:
                msg = "答题功能已启用，但 Redis 连接失败。"
                self.startup_notifications.append(msg)
                format_and_log("SYSTEM", "配置检查", {'问题': msg}, level=logging.CRITICAL)
            if not settings.EXAM_SOLVER_CONFIG.get('gemini_api_key'):
                msg = "答题功能已启用，但缺少 Gemini API Key。"
                self.startup_notifications.append(msg)
                format_and_log("SYSTEM", "配置检查", {'问题': msg}, level=logging.CRITICAL)

    def setup_logging(self):
        # ... (此函数内容保持不变) ...
        log_format = '%(message)s'
        log_level = logging.INFO
        root_logger = logging.getLogger()
        if root_logger.hasHandlers(): root_logger.handlers.clear()
        formatter = logging.Formatter(fmt=log_format)
        file_handler = logging.handlers.RotatingFileHandler(
            settings.LOG_FILE, maxBytes=settings.LOG_ROTATION_CONFIG['max_bytes'], 
            backupCount=settings.LOG_ROTATION_CONFIG['backup_count'], encoding='utf-8')
        file_handler.setFormatter(formatter)
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
        root_logger.addHandler(stream_handler)
        root_logger.setLevel(log_level)
        logging.getLogger('apscheduler').setLevel(logging.ERROR)
        logging.getLogger('telethon').setLevel(logging.WARNING)
        logging.getLogger('asyncio').setLevel(logging.WARNING)
        raw_logger = logging.getLogger('raw_messages')
        raw_logger.setLevel(logging.INFO)
        raw_logger.propagate = False
        if raw_logger.hasHandlers(): raw_logger.handlers.clear()
        raw_handler = logging.handlers.RotatingFileHandler(
            settings.RAW_LOG_FILE, maxBytes=settings.LOG_ROTATION_CONFIG['max_bytes'], 
            backupCount=settings.LOG_ROTATION_CONFIG['backup_count'], encoding='utf-8')
        raw_formatter = logging.Formatter('%(asctime)s\n%(message)s\n' + '-'*50, datefmt='%Y-%m-%d %H:%M:%S')
        raw_handler.setFormatter(raw_formatter)
        raw_logger.addHandler(raw_handler)
        
    def load_plugins_and_commands(self):
        # ... (此函数内容保持不变) ...
        common_checks = common_tasks.initialize_tasks(self.client)
        if common_checks: self.startup_checks.extend(common_checks)
        learning_checks = learning_tasks.initialize_tasks(self.client)
        if learning_checks: self.startup_checks.extend(learning_checks)
        if settings.SECT_NAME == '黄枫谷':
            sect_checks = huangfeng_valley.initialize_tasks(self.client)
            if sect_checks: self.startup_checks.extend(sect_checks)
        elif settings.SECT_NAME == '太一门':
            sect_checks = taiyi_sect.initialize_tasks(self.client)
            if sect_checks: self.startup_checks.extend(sect_checks)
        format_and_log("SYSTEM", "插件加载", {'状态': f"已加载【通用】及【{settings.SECT_NAME or '无'}】任务插件"})
        cmd_path = 'app/commands'
        for filename in os.listdir(cmd_path):
            if filename.endswith('.py') and not filename.startswith('__'):
                module_name = f"{cmd_path.replace('/', '.')}.{filename[:-3]}"
                try:
                    cmd_module = importlib.import_module(module_name)
                    cmd_module.initialize_commands(self.client)
                    format_and_log("SYSTEM", "指令加载", {'模块': filename, '状态': '加载成功'})
                except Exception as e:
                    format_and_log("SYSTEM", "指令加载", {'模块': filename, '状态': f'加载失败: {e}'}, level=logging.ERROR)
        if self.redis_db:
            exam_solver.initialize_plugin(self.client, self.redis_db)
            tianji_exam_solver.initialize_plugin(self.client, self.redis_db)
        else:
            format_and_log("SYSTEM", "插件跳过", {'模块': '所有答题插件', '原因': 'Redis 连接不可用'})


    async def run(self):
        try:
            scheduler.start()
            format_and_log("SYSTEM", "核心服务", {'状态': '任务调度器已启动。'})
            await self.client.start()

            # *** 新增：发送启动告警 ***
            if self.startup_notifications:
                notification_message = "🚨 **助手启动异常告警** 🚨\n\n您的助手已启动，但检测到以下配置问题：\n"
                for i, msg in enumerate(self.startup_notifications, 1):
                    notification_message += f"\n{i}. {msg}"
                notification_message += "\n\n请检查您的 `config/prod.yaml` 文件并使用 `,重启` 指令。"
                await self.client.send_admin_notification(notification_message)
            
            format_and_log("SYSTEM", "核心服务", {'状态': '正在执行启动后任务检查...'})
            
            try:
                await asyncio.gather(*(check() for check in self.startup_checks))
            except LookupError:
                logging.warning("="*60)
                logging.warning("检测到调度器数据库与当前代码不兼容，开始自动修复...")
                if scheduler.running:
                    scheduler.shutdown(wait=False)
                db_path = settings.SCHEDULER_DB.replace('sqlite:///', '')
                if os.path.exists(db_path):
                    os.remove(db_path)
                    logging.warning(f"已成功删除不兼容的调度文件: {db_path}")
                logging.warning("自动修复完成。程序将安全退出，请重新启动以应用更改。")
                logging.warning("="*60)
                return

            format_and_log("SYSTEM", "核心服务", {'状态': '应用已准备就绪。'})
            await self.client.run_until_disconnected()
        except Exception as e:
            logging.critical("应用启动或运行过程中发生严重错误:", exc_info=True)
        finally:
            format_and_log("SYSTEM", "核心服务", {'状态': '正在关闭任务调度器...'})
            shutdown()
            format_and_log("SYSTEM", "核心服务", {'状态': '应用已关闭。'})
