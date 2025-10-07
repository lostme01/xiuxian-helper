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
from app.telegram_client import TelegramClient, CommandTimeoutError
from app.redis_client import initialize_redis
from app.data_manager import data_manager
from app import gemini_client
from app.plugins import load_all_plugins
from app.logger import format_and_log, TimezoneFormatter
from app.context import set_application, set_scheduler, get_application
from app.utils import create_error_reply
from app.inventory_manager import inventory_manager
from app.character_stats_manager import stats_manager

class Application:
    def __init__(self):
        self.client: TelegramClient = None
        self.redis_db = None
        self.data_manager = data_manager
        self.inventory_manager = inventory_manager
        self.stats_manager = stats_manager
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
        from app.plugins.trade_coordination import redis_message_handler
        from app.plugins.logic.trade_logic import TASK_CHANNEL
        from app.plugins.game_event_handler import GAME_EVENTS_CHANNEL
        
        if not self.redis_db: 
            format_and_log("WARNING", "Redis 监听器", {'状态': '未启动', '原因': 'Redis 未连接'})
            return

        while True: 
            try:
                async with self.redis_db.pubsub() as pubsub:
                    await pubsub.subscribe(TASK_CHANNEL, GAME_EVENTS_CHANNEL)
                    format_and_log("SYSTEM", "核心服务", {'服务': 'Redis 监听器', '状态': '已订阅', '频道': f"{TASK_CHANNEL}, {GAME_EVENTS_CHANNEL}"})
                    
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
        app_logger = logging.getLogger("app")
        if app_logger.hasHandlers(): app_logger.handlers.clear()
        
        log_level = logging.DEBUG if settings.LOGGING_SWITCHES.get('debug_log') else logging.INFO
        app_logger.setLevel(log_level)
        
        app_logger.propagate = False
        
        # [核心修复] 同时配置控制台输出和文件输出
        
        # 1. 控制台处理器 (用于 docker logs)
        console_formatter = logging.Formatter(fmt='%(message)s')
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(console_formatter)
        app_logger.addHandler(stream_handler)
        
        # 2. app.log 文件处理器 (用于持久化)
        os.makedirs('logs', exist_ok=True)
        file_formatter = TimezoneFormatter(
            fmt='%(asctime)s - %(levelname)s - %(message)s', 
            datefmt='%Y-%m-%d %H:%M:%S %Z', 
            tz_name=settings.TZ
        )
        file_handler = logging.handlers.RotatingFileHandler(
            settings.LOG_FILE, 
            maxBytes=settings.LOG_ROTATION_CONFIG['max_bytes'], 
            backupCount=settings.LOG_ROTATION_CONFIG['backup_count'], 
            encoding='utf-8'
        )
        file_handler.setFormatter(file_formatter)
        # 重写 format_and_log 生成的 box 格式，使其在文件中更易读
        original_emit = file_handler.emit
        def plain_emit(record):
            if '\n' in record.getMessage(): # 检查是否是我们的 box 格式
                # 提取标题和数据
                lines = record.getMessage().strip().split('\n')
                title = lines[1].strip('│ []')
                data_lines = lines[3:-1]
                data_dict = {}
                for line in data_lines:
                    parts = line.split(':', 1)
                    if len(parts) == 2:
                        key = parts[0].strip('│ ').strip()
                        value = parts[1].strip()
                        data_dict[key] = value
                record.msg = f"[{title.strip()}] - {json.dumps(data_dict, ensure_ascii=False)}"
            original_emit(record)
        
        # (暂不启用 plain_emit, 以保留 box 格式)
        # file_handler.emit = plain_emit

        app_logger.addHandler(file_handler)
        
        # 3. raw_messages.log 文件处理器 (保持不变)
        raw_logger = logging.getLogger('raw_messages')
        if raw_logger.hasHandlers(): raw_logger.handlers.clear()
        raw_logger.propagate = False
        
        if settings.LOGGING_SWITCHES.get('original_log_enabled'):
            raw_logger.setLevel(logging.INFO)
            raw_log_formatter = TimezoneFormatter(
                fmt='%(asctime)s - %(message)s\n--------------------\n', datefmt='%Y-%m-%d %H:%M:%S %Z', tz_name=settings.TZ
            )
            raw_log_handler = logging.handlers.RotatingFileHandler(
                settings.RAW_LOG_FILE, maxBytes=settings.LOG_ROTATION_CONFIG['max_bytes'], 
                backupCount=settings.LOG_ROTATION_CONFIG['backup_count'], encoding='utf-8')
            raw_log_handler.setFormatter(raw_log_formatter)
            raw_logger.addHandler(raw_log_handler)
        else:
            raw_logger.setLevel(logging.CRITICAL + 1)
        
        logging.getLogger('apscheduler').setLevel(logging.ERROR)
        logging.getLogger('telethon').setLevel(logging.WARNING)
        logging.getLogger('asyncio').setLevel(logging.WARNING)

        print(f"日志系统配置完成。现在将同时输出到控制台和 app.log 文件。")

    def load_plugins_and_commands(self, is_reload=False):
        if is_reload:
            self.commands.clear()
            self.task_functions.clear()
            self.startup_checks.clear()
            for handler, callback in list(self.client.client.list_event_handlers()):
                if callback not in [self.client._message_handler, self.client._message_edited_handler, self.client._deleted_message_handler]:
                    self.client.client.remove_event_handler(callback, handler)
        load_all_plugins(self)

    async def _run_startup_checks(self):
        format_and_log("SYSTEM", "核心服务", {'阶段': '开始执行启动检查任务...'})
        if self.startup_checks:
            await asyncio.gather(*(check() for check in self.startup_checks if check), return_exceptions=True)
        format_and_log("SYSTEM", "核心服务", {'阶段': '启动检查任务执行完毕。'})

    async def run(self):
        background_tasks = set()
        try:
            self.redis_db = await initialize_redis()
            
            self.data_manager.initialize(self.redis_db)
            self.inventory_manager.initialize(self.data_manager)
            self.stats_manager.initialize(self.data_manager)

            if settings.REDIS_CONFIG.get('enabled') and not self.redis_db:
                format_and_log("CRITICAL", "启动失败", {'原因': 'Redis配置为启用，但连接失败，程序退出。'})
                sys.exit(1)
            
            scheduler.start()
            await self.client.start()
            
            settings.ACCOUNT_ID = str(self.client.me.id)
            format_and_log("SYSTEM", "账户初始化", {'账户ID': settings.ACCOUNT_ID, '状态': '已设置为全局标识'})

            if self.data_manager.db:
                try:
                    profile = await self.data_manager.get_value("character_profile", is_json=True, default={})
                    profile.update({ "用户": self.client.me.username, "ID": self.client.me.id })
                    await self.data_manager.save_value("character_profile", profile)
                    format_and_log("SYSTEM", "身份注册", {'状态': '成功', '用户名': self.client.me.username, 'ID': self.client.me.id})
                except Exception as e:
                    format_and_log("ERROR", "身份注册失败", {'错误': str(e)})

            self.load_plugins_and_commands()
            
            if self.redis_db:
                redis_task = asyncio.create_task(self._redis_listener_loop())
                background_tasks.add(redis_task)
            
            await asyncio.sleep(2) 

            await self.client._cache_chat_info()
            await self.client.warm_up_entity_cache()
            
            startup_task = asyncio.create_task(self._run_startup_checks())
            background_tasks.add(startup_task)

            await self.client.send_admin_notification("✅ **助手已成功启动并在线**")
            format_and_log("SYSTEM", "核心服务", {'阶段': '所有服务已启动，进入主循环...'})
            
            await self.client.client.disconnected

        except Exception as e:
            logging.critical(f"应用主流程发生严重错误: {e}", exc_info=True)
        finally:
            for task in background_tasks:
                task.cancel()
            await asyncio.gather(*background_tasks, return_exceptions=True)

            if self.client and self.client.is_connected():
                await self.client.disconnect()
            shutdown()
            format_and_log("SYSTEM", "核心服务", {'阶段': '应用已关闭'})

    def register_command(self, name, handler, help_text="", category="默认", aliases=None, usage=None):
        if aliases is None: aliases = []
        usage = usage or help_text
        command_data = { "name": name, "handler": handler, "help": help_text, "category": category, "aliases": aliases, "usage": usage }
        for cmd_name in [name] + aliases:
            self.commands[cmd_name.lower()] = command_data

    def register_task(self, task_key, function, command_name, help_text):
        self.task_functions[task_key] = function
        
        async def task_trigger_handler(event, parts):
            app = get_application()
            client = app.client
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
                format_and_log("SYSTEM", "手动任务执行失败", {'任务': command_name, '错误': str(e)}, level=logging.ERROR)
            finally:
                client.unpin_message(progress_message)
                try:
                    await client._cancel_message_deletion(progress_message)
                    await progress_message.edit(final_text)
                except MessageEditTimeExpiredError:
                    await client.reply_to_admin(event, final_text)

        self.register_command(command_name, task_trigger_handler, help_text=help_text, category="动作")

    async def reload_plugins_and_commands(self):
        format_and_log("SYSTEM", "热重载", {'阶段': '开始...'})
        try:
            reload(sys.modules['config.settings'])
            for module_name in list(sys.modules.keys()):
                if module_name.startswith('app.plugins.'):
                    reload(sys.modules[module_name])
        except Exception as e:
            await self.client.send_admin_notification(f"❌ **热重载失败**：无法重新加载配置文件或插件，请检查日志。错误: {e}")
            return
        
        self.load_plugins_and_commands(is_reload=True)
        asyncio.create_task(self._run_startup_checks())
        format_and_log("SYSTEM", "热重载", {'阶段': '完成'})
