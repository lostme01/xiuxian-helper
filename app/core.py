# -*- coding: utf-8 -*-
import asyncio
import logging
import logging.handlers
import os
import sys
import time
from importlib import reload

import redis.asyncio as redis
from telethon.errors.rpcerrorlist import MessageEditTimeExpiredError

from app import gemini_client
from app.character_stats_manager import stats_manager
from app.constants import GAME_EVENTS_CHANNEL, TASK_CHANNEL, STATE_KEY_PROFILE
from app.context import get_application, set_application, set_scheduler
from app.logging_service import LogType, TimezoneFormatter, format_and_log
from app.plugins import load_all_plugins
from app.redis_client import initialize_redis
from app.task_scheduler import scheduler, shutdown
from app.telegram_client import CommandTimeoutError, TelegramClient
from app.utils import create_error_reply
from config import settings


class Application:
    def __init__(self):
        from app.data_manager import data_manager
        from app.inventory_manager import inventory_manager
        
        self.client: TelegramClient = None
        self.redis_db = None
        self.data_manager = data_manager
        self.inventory_manager = inventory_manager
        self.stats_manager = stats_manager
        self.startup_checks = []
        self.commands = {}
        self.task_functions = {}
        self.last_redis_error_notice_time = 0

        set_application(self)
        set_scheduler(scheduler)

        self.setup_logging()
        format_and_log(LogType.SYSTEM, "应用初始化", {'阶段': '开始...'})
        gemini_client.initialize_gemini()
        self.client = TelegramClient()
        format_and_log(LogType.SYSTEM, "组件初始化", {'组件': 'Telegram 客户端', '状态': '实例化完成'})

    async def _redis_listener_loop(self):
        from app.plugins.trade_coordination import redis_message_handler
        while True:
            if not self.redis_db or not self.redis_db.is_connected:
                if settings.REDIS_CONFIG.get('enabled'):
                    format_and_log(LogType.WARNING, "Redis 监听器", {'状态': '暂停', '原因': 'Redis 未连接'})
                    await asyncio.sleep(15)
                else:
                    return
            try:
                async with self.redis_db.pubsub() as pubsub:
                    await pubsub.subscribe(TASK_CHANNEL, GAME_EVENTS_CHANNEL)
                    format_and_log(LogType.SYSTEM, "核心服务",
                                   {'服务': 'Redis 监听器', '状态': '已订阅', '频道': f"{TASK_CHANNEL}, {GAME_EVENTS_CHANNEL}"})
                    async for message in pubsub.listen():
                        if not self.redis_db.is_connected:
                            format_and_log(LogType.WARNING, "Redis 监听器", {'状态': '中断', '原因': '连接在监听时丢失'})
                            break
                        if message and message.get('type') == 'message':
                            format_and_log(LogType.DEBUG, "Redis 监听器", {'阶段': '收到消息', '原始返回': str(message)})
                            asyncio.create_task(redis_message_handler(message))
            except Exception as e:
                format_and_log(LogType.ERROR, "Redis 监听循环异常", {'错误': str(e)}, level=logging.CRITICAL)
                await asyncio.sleep(15)

    # [重构] 实现错误日志分离
    def setup_logging(self):
        print("开始配置日志系统...")
        app_logger = logging.getLogger("app")
        if app_logger.hasHandlers(): app_logger.handlers.clear()
        
        log_level = logging.DEBUG if settings.LOGGING_SWITCHES.get('debug_log') else logging.INFO
        app_logger.setLevel(log_level)
        app_logger.propagate = False

        # --- 通用格式化器 ---
        console_formatter = logging.Formatter(fmt='%(message)s')
        file_formatter = TimezoneFormatter(
            fmt='%(asctime)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S %Z',
            tz_name=settings.TZ
        )

        # --- 控制台处理器 (所有级别) ---
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(console_formatter)
        app_logger.addHandler(stream_handler)
        
        os.makedirs('logs', exist_ok=True)

        # --- 主日志文件处理器 (INFO, WARNING) ---
        class InfoFilter(logging.Filter):
            def filter(self, record):
                return record.levelno <= logging.WARNING

        main_log_handler = logging.handlers.RotatingFileHandler(
            settings.LOG_FILE,
            maxBytes=settings.LOG_ROTATION_CONFIG['max_bytes'],
            backupCount=settings.LOG_ROTATION_CONFIG['backup_count'],
            encoding='utf-8'
        )
        main_log_handler.setFormatter(file_formatter)
        main_log_handler.addFilter(InfoFilter())
        app_logger.addHandler(main_log_handler)

        # --- 错误日志文件处理器 (ERROR, CRITICAL) ---
        error_log_handler = logging.handlers.RotatingFileHandler(
            settings.ERROR_LOG_FILE, # 使用新的文件名
            maxBytes=settings.LOG_ROTATION_CONFIG['max_bytes'],
            backupCount=settings.LOG_ROTATION_CONFIG['backup_count'],
            encoding='utf-8'
        )
        error_log_handler.setFormatter(file_formatter)
        error_log_handler.setLevel(logging.ERROR) # 只处理 ERROR 及以上级别
        app_logger.addHandler(error_log_handler)

        # --- 原始消息日志处理器 (可选) ---
        raw_logger = logging.getLogger('raw_messages')
        if raw_logger.hasHandlers(): raw_logger.handlers.clear()
        raw_logger.propagate = False
        if settings.LOGGING_SWITCHES.get('original_log_enabled'):
            raw_logger.setLevel(logging.INFO)
            raw_log_formatter = TimezoneFormatter(fmt='%(asctime)s - %(message)s\n--------------------\n', datefmt='%Y-%m-%d %H:%M:%S %Z', tz_name=settings.TZ)
            raw_log_handler = logging.handlers.RotatingFileHandler(settings.RAW_LOG_FILE, maxBytes=settings.LOG_ROTATION_CONFIG['max_bytes'], backupCount=settings.LOG_ROTATION_CONFIG['backup_count'], encoding='utf-8')
            raw_log_handler.setFormatter(raw_log_formatter)
            raw_logger.addHandler(raw_log_handler)
        else:
            raw_logger.setLevel(logging.CRITICAL + 1)

        # --- 屏蔽第三方库的冗余日志 ---
        logging.getLogger('apscheduler').setLevel(logging.ERROR)
        logging.getLogger('telethon').setLevel(logging.WARNING)
        logging.getLogger('asyncio').setLevel(logging.WARNING)
        
        print(f"日志系统配置完成。常规日志输出到 {settings.LOG_FILE}，错误日志输出到 {settings.ERROR_LOG_FILE}。")

    def load_plugins_and_commands(self, is_reload=False):
        if is_reload:
            self.commands.clear(); self.task_functions.clear(); self.startup_checks.clear()
            core_handlers = {self.client._unified_event_handler, self.client._deleted_message_handler}
            if hasattr(self.client, 'client'):
                for handler, callback in list(self.client.client.list_event_handlers()):
                    if callback not in core_handlers: self.client.client.remove_event_handler(callback, handler)
        load_all_plugins(self)

    async def _run_startup_checks(self):
        format_and_log(LogType.SYSTEM, "核心服务", {'阶段': '开始执行启动检查任务...'})
        if self.startup_checks:
            await asyncio.gather(*(check() for check in self.startup_checks if check), return_exceptions=True)
        format_and_log(LogType.SYSTEM, "核心服务", {'阶段': '启动检查任务执行完毕。'})

    async def run(self):
        background_tasks = set()
        try:
            self.redis_db = await initialize_redis()
            self.data_manager.initialize(self.redis_db)
            self.inventory_manager.initialize(self.data_manager)
            self.stats_manager.initialize(self.data_manager)
            if settings.REDIS_CONFIG.get('enabled') and not self.redis_db.is_connected:
                format_and_log(LogType.SYSTEM, "启动失败", {'原因': 'Redis配置为启用，但连接失败，程序退出。'}, level=logging.CRITICAL)
                sys.exit(1)
            scheduler.start()
            await self.client.start()
            settings.ACCOUNT_ID = str(self.client.me.id)
            format_and_log(LogType.SYSTEM, "账户初始化", {'账户ID': settings.ACCOUNT_ID, '状态': '已设置为全局标识'})
            if self.redis_db.is_connected:
                try:
                    profile = await self.data_manager.get_value(STATE_KEY_PROFILE, is_json=True, default={})
                    profile.update({"用户": self.client.me.username, "ID": self.client.me.id})
                    await self.data_manager.save_value(STATE_KEY_PROFILE, profile)
                    format_and_log(LogType.SYSTEM, "身份注册", {'状态': '成功', '用户名': self.client.me.username, 'ID': self.client.me.id})
                except Exception as e:
                    format_and_log(LogType.ERROR, "身份注册失败", {'错误': str(e)})
            self.load_plugins_and_commands()
            if self.redis_db.is_connected:
                redis_task = asyncio.create_task(self._redis_listener_loop())
                background_tasks.add(redis_task)
            await asyncio.sleep(2)
            await self.client._cache_chat_info()
            await self.client.warm_up_entity_cache()
            startup_task = asyncio.create_task(self._run_startup_checks())
            background_tasks.add(startup_task)
            await self.client.send_admin_notification("✅ **助手已成功启动并在线**")
            format_and_log(LogType.SYSTEM, "核心服务", {'阶段': '所有服务已启动，进入主循环...'})
            await self.client.client.disconnected
        except Exception as e:
            logging.critical(f"应用主流程发生严重错误: {e}", exc_info=True)
        finally:
            for task in background_tasks: task.cancel()
            await asyncio.gather(*background_tasks, return_exceptions=True)
            if self.client and self.client.is_connected(): await self.client.disconnect()
            shutdown()
            format_and_log(LogType.SYSTEM, "核心服务", {'阶段': '应用已关闭'})

    def register_command(self, name, handler, help_text="", category="默认", aliases=None, usage=None):
        if aliases is None: aliases = []
        usage = usage or help_text
        command_data = {"name": name, "handler": handler, "help": help_text, "category": category, "aliases": aliases, "usage": usage}
        for cmd_name in [name] + aliases: self.commands[cmd_name.lower()] = command_data

    def register_task(self, task_key, function, command_name, help_text):
        self.task_functions[task_key] = function
        async def task_trigger_handler(event, parts):
            app = get_application(); client = app.client
            progress_message = await client.reply_to_admin(event, f"⏳ 正在手动执行 **[{command_name}]** 任务...")
            if not progress_message: return
            client.pin_message(progress_message)
            final_text = ""
            try:
                task_func = self.task_functions.get(task_key)
                if task_func:
                    result = await task_func(force_run=True)
                    final_text = result if isinstance(result, str) else f"✅ **[{command_name}]** 任务已成功触发。"
                else:
                    raise ValueError(f"未找到与 `{task_key}` 关联的任务实现。")
            except CommandTimeoutError as e:
                final_text = create_error_reply(command_name, "游戏指令超时", details=str(e))
            except Exception as e:
                final_text = create_error_reply(command_name, "任务执行期间发生意外错误", details=str(e))
                format_and_log(LogType.ERROR, "手动任务执行失败", {'任务': command_name, '错误': str(e)}, level=logging.ERROR)
            finally:
                client.unpin_message(progress_message)
                try:
                    await client._cancel_message_deletion(progress_message)
                    await progress_message.edit(final_text)
                except MessageEditTimeExpiredError:
                    await client.reply_to_admin(event, final_text)
        self.register_command(command_name, task_trigger_handler, help_text=help_text, category="动作")

    async def reload_plugins_and_commands(self):
        format_and_log(LogType.SYSTEM, "热重载", {'阶段': '开始...'})
        try:
            reload(sys.modules['config.settings'])
            for module_name in list(sys.modules.keys()):
                if module_name.startswith('app.plugins.'): reload(sys.modules[module_name])
        except Exception as e:
            await self.client.send_admin_notification(f"❌ **热重载失败**：无法重新加载配置文件或插件，请检查日志。错误: {e}")
            return
        self.load_plugins_and_commands(is_reload=True)
        asyncio.create_task(self._run_startup_checks())
        format_and_log(LogType.SYSTEM, "热重载", {'阶段': '完成'})
