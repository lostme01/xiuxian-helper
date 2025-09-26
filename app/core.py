# -*- coding: utf-8 -*-
import asyncio
import logging
import pytz
import importlib
import os
from datetime import datetime
from config import settings
from app.task_scheduler import scheduler, shutdown
from app.telegram_client import TelegramClient
from app.plugins import common_tasks, huangfeng_valley, taiyi_sect, learning_tasks
from app.logger import format_and_log

class Application:
    def __init__(self):
        self.setup_logging()
        self.startup_checks = []
        format_and_log("SYSTEM", "系统初始化", {'状态': '应用开始初始化...'})
        self.client = TelegramClient()
        self.load_plugins_and_commands()
        format_and_log("SYSTEM", "系统初始化", {'状态': '所有模块加载完毕。'})

    def setup_logging(self):
        log_format = '%(message)s'
        # 移除日志级别设置，恢复为默认 INFO
        log_level = logging.INFO
        
        root_logger = logging.getLogger()
        if root_logger.hasHandlers(): root_logger.handlers.clear()
        
        formatter = logging.Formatter(fmt=log_format)
        
        file_handler = logging.FileHandler(settings.LOG_FILE, encoding='utf-8')
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
        raw_handler = logging.FileHandler(settings.RAW_LOG_FILE, encoding='utf-8')
        raw_formatter = logging.Formatter('%(asctime)s\n%(message)s\n' + '-'*50, datefmt='%Y-%m-%d %H:%M:%S')
        raw_handler.setFormatter(raw_formatter)
        raw_logger.addHandler(raw_handler)
        
    def load_plugins_and_commands(self):
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
                except Exception as e:
                    format_and_log("SYSTEM", "指令加载", {'模块': filename, '状态': f'加载失败: {e}'}, level=logging.ERROR)

    async def run(self):
        try:
            scheduler.start()
            format_and_log("SYSTEM", "核心服务", {'状态': '任务调度器已启动。'})
            await self.client.start()
            format_and_log("SYSTEM", "核心服务", {'状态': '正在执行启动后任务检查...'})
            
            try:
                await asyncio.gather(*(check() for check in self.startup_checks))
            except LookupError:
                logging.critical("="*60)
                logging.critical("检测到调度器数据库与当前代码不兼容！请删除旧的调度文件后重试:")
                logging.critical(f"rm {settings.DATA_DIR}/jobs.sqlite")
                logging.critical("="*60)
                return

            format_and_log("SYSTEM", "核心服务", {'状态': '应用已准备就绪。'})
            await self.client.run_until_disconnected()
        except Exception as e:
            logging.critical("应用启动或运行过程中发生严重错误:", exc_info=True)
        finally:
            format_and_log("SYSTEM", "核心服务", {'状态': '正在关闭任务调度器...'})
            shutdown()
            format_and_log("SYSTEM", "核心服务", {'状态': '应用已关闭。'})
