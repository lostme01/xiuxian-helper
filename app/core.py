# -*- coding: utf-8 -*-
import asyncio
import logging
import logging.handlers
import pytz
import os
import sys
import time
from importlib import reload, import_module
from telethon.errors.rpcerrorlist import MessageEditTimeExpiredError
import redis.asyncio as redis

from config import settings
from app.task_scheduler import scheduler, shutdown
from app.telegram_client import TelegramClient
from app.redis_client import initialize_redis
from app import gemini_client
from app.plugins import load_all_plugins
from app.logger import format_and_log, TimezoneFormatter
from app.context import set_application, set_scheduler
from app.plugins.trade_coordination import redis_message_handler
from app.plugins.logic.trade_logic import TASK_CHANNEL


class Application:
    def __init__(self):
        self.client: TelegramClient = None
        self.redis_db = None
        self.startup_checks = []
        self.commands = {}
        self.task_functions = {}
        
        set_application(self)
        set_scheduler(scheduler)
        
        self.setup_logging()
        format_and_log("SYSTEM", "应用初始化", {'阶段': '开始...'})
        gemini_client.initialize_gemini()
        self.client = TelegramClient()
        format_and_log("SYSTEM", "组件初始化", {'组件': 'Telegram 客户端', '状态': '实例化完成'})

    async def _redis_listener_loop(self):
        from app.redis_client import db
        if not db: 
            format_and_log("WARNING", "Redis 监听器", {'状态': '未启动', '原因': 'Redis 未连接'})
            return

        while True: 
            try:
                async with db.pubsub() as pubsub:
                    await pubsub.subscribe(TASK_CHANNEL)
                    format_and_log("SYSTEM", "核心服务", {'服务': 'Redis 任务监听器', '状态': '已订阅', '频道': TASK_CHANNEL})
                    
                    async for message in pubsub.listen():
                        if message and message.get('type') == 'message':
                            format_and_log("DEBUG", "Redis 监听器", {'阶段': '收到消息', '原始返回': str(message)})
                            asyncio.create_task(redis_message_handler(message))

            except (redis.exceptions.ConnectionError, asyncio.CancelledError) as e:
                format_and_log("ERROR", "Redis 监听连接断开", {'错误': str(e)}, level=logging.ERROR)
            except Exception as e:
                format_and_log("ERROR", "Redis 监听循环异常", {'错误': str(e)}, level=logging.CRITICAL)
            finally:
                format_and_log("SYSTEM", "核心服务", {'服务': 'Redis 任务监听器', '状态': '将在5秒后尝试重连...'})
                await asyncio.sleep(5)
        
    def setup_logging(self):
        print("开始配置日志系统...")
        root_logger = logging.getLogger()
        if root_logger.hasHandlers(): root_logger.handlers.clear()

        log_level = logging.DEBUG if settings.LOGGING_SWITCHES.get('debug_log') else logging.INFO
        root_logger.setLevel(log_level)
        
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
        print(f"日志系统配置完成。当前日志级别: {logging.getLevelName(log_level)}")

    def load_plugins_and_commands(self, is_reload=False):
        if is_reload:
            self.commands.clear()
            self.task_functions.clear()
            self.startup_checks.clear()
            for handler, callback in list(self.client.client.list_event_handlers()):
                if callback not in [self.client._message_handler, self.client._message_edited_handler, self.client._deleted_message_handler]:
                    # --- 修复：添加正确的缩进 ---
                    self.client.client.remove_event_handler(callback, handler)
        load_all_plugins(self)

    async def _run_startup_checks(self):
        """A helper function to run all startup checks."""
        format_and_log("SYSTEM", "核心服务", {'阶段': '开始执行启动检查任务...'})
        if self.startup_checks:
            await asyncio.gather(*(check() for check in self.startup_checks if check), return_exceptions=True)
        format_and_log("SYSTEM", "核心服务", {'阶段': '启动检查任务执行完毕。'})

    async def run(self):
        """
        [重构版]
        编排所有服务的启动、运行和关闭。
        """
        background_tasks = set()
        try:
            self.redis_db = await initialize_redis()
            if settings.REDIS_CONFIG.get('enabled') and not self.redis_db:
                sys.exit(1)
            
            scheduler.start()
            await self.client.start()
            settings.ACCOUNT_ID = str(self.client.me.id)
            format_and_log("SYSTEM", "账户初始化", {'账户ID': settings.ACCOUNT_ID, '状态': '已设置为全局标识'})
            
            self.load_plugins_and_commands()
            
            # --- 核心重构：先让核心服务在后台运行起来 ---
            if self.redis_db:
                redis_task = asyncio.create_task(self._redis_listener_loop())
                background_tasks.add(redis_task)
            
            # 给予后台任务一点时间来完成初始化
            await asyncio.sleep(2) 

            # --- 然后再执行可能会发送指令的启动检查 ---
            await self.client._cache_chat_info()
            await self.client.warm_up_entity_cache()
            
            startup_task = asyncio.create_task(self._run_startup_checks())
            background_tasks.add(startup_task)

            await self.client.send_admin_notification("✅ **助手已成功启动并在线**")
            format_and_log("SYSTEM", "核心服务", {'阶段': '所有服务已启动，进入主循环...'})
            
            # 主程序现在等待 Telegram 客户端断开连接
            await self.client.client.disconnected

        except Exception as e:
            logging.critical(f"应用主流程发生严重错误: {e}", exc_info=True)
        finally:
            for task in background_tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

            if self.client and self.client.is_connected():
                await self.client.disconnect()
            shutdown()
            format_and_log("SYSTEM", "核心服务", {'阶段': '应用已关闭'})

    # --- 以下方法保持不变 ---
    def register_command(self, name, handler, help_text="", category="默认", aliases=None, usage=None):
        if aliases is None: aliases = []
        usage = usage or help_text
        command_data = { "handler": handler, "help": help_text, "category": category, "aliases": aliases, "usage": usage }
        for cmd_name in [name] + aliases: self.commands[cmd_name] = command_data
    def register_task(self, task_key, function, command_name, help_text):
        self.task_functions[task_key] = function
        async def task_trigger_handler(event, parts):
            from app.context import get_application
            client = get_application().client
            progress_message = await client.reply_to_admin(event, f"⏳ 好的，正在手动执行 **[{command_name}]** 任务...")
            if not progress_message: return
            client.pin_message(progress_message)
            final_text = f"✅ **[{command_name}]** 任务已成功执行完毕。"
            try:
                task_func = self.task_functions.get(task_key)
                if task_func:
                    result_text = await task_func(force_run=True)
                    if isinstance(result_text, str): final_text = result_text
                else: final_text = f"❌ 错误: 未找到与 `{task_key}` 关联的任务实现。"
            except Exception as e:
                final_text = f"❌ **[{command_name}]** 任务在执行过程中发生意外错误: `{e}`"
                format_and_log("SYSTEM", "任务执行失败", {'任务': command_name, '错误': str(e)}, level=logging.ERROR)
            finally:
                client.unpin_message(progress_message)
                try:
                    await client._cancel_message_deletion(progress_message)
                    edited_message = await progress_message.edit(final_text)
                    client._schedule_message_deletion(edited_message, settings.AUTO_DELETE.get('delay_admin_command'), "编辑后的助手回复")
                except MessageEditTimeExpiredError: await client.reply_to_admin(event, final_text)
        self.register_command(command_name, task_trigger_handler, help_text=help_text, category="游戏任务")
    async def reload_plugins_and_commands(self):
        format_and_log("SYSTEM", "热重载", {'阶段': '开始...'})
        try:
            reload(sys.modules['config.settings'])
            for module_name in list(sys.modules.keys()):
                if module_name.startswith('app.plugins.'):
                    reload(sys.modules[module_name])
        except Exception as e:
            await self.client.send_admin_notification(f"❌ **热重载失败**：无法重新加载配置文件或插件，请检查日志。")
            return
        self.load_plugins_and_commands(is_reload=True)
        asyncio.create_task(self._run_startup_checks())
        format_and_log("SYSTEM", "热重载", {'阶段': '完成'})
