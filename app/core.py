# -*- coding: utf-8 -*-
import asyncio
import logging
import logging.handlers
import pytz
import os
import sys
from importlib import reload, import_module
from telethon.errors.rpcerrorlist import MessageEditTimeExpiredError

from config import settings
from app.task_scheduler import scheduler, shutdown
from app.telegram_client import TelegramClient
from app.redis_client import initialize_redis, pubsub_client
from app import gemini_client
from app.plugins import load_all_plugins
from app.logger import format_and_log, TimezoneFormatter
from app.context import set_application, set_scheduler, get_application
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
        format_and_log("SYSTEM", "组件初始化", {'组件': 'Redis', '状态': '开始连接...'})
        self.redis_db = initialize_redis()
        
        if settings.REDIS_CONFIG.get('enabled') and not self.redis_db:
            format_and_log("SYSTEM", "应用中止", {'原因': 'Redis 配置为启用但连接失败。'}, level=logging.CRITICAL)
            sys.exit(1)

        gemini_client.initialize_gemini()
        
        format_and_log("SYSTEM", "组件初始化", {'组件': 'Telegram 客户端', '状态': '开始实例化...'})
        self.client = TelegramClient()
        format_and_log("SYSTEM", "组件初始化", {'组件': 'Telegram 客户端', '状态': '实例化完成'})

    # --- 改造：为 Redis 监听器添加详细日志 ---
    async def _redis_listener_loop(self):
        if not pubsub_client: return
        
        p = pubsub_client.pubsub()
        p.subscribe(TASK_CHANNEL)
        format_and_log("SYSTEM", "核心服务", {'服务': 'Redis 任务监听器', '状态': '已启动', '频道': TASK_CHANNEL})
        
        while True:
            try:
                # 使用异步方式获取消息，避免长时间阻塞
                message = await p.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message:
                    format_and_log("DEBUG", "Redis 监听器", {'阶段': '收到原始消息', '消息': str(message)})
                    await redis_message_handler(message)
                
                # 短暂休眠，让出CPU
                await asyncio.sleep(0.1)
            except Exception as e:
                format_and_log("ERROR", "Redis 监听循环异常", {'错误': str(e)}, level=logging.CRITICAL)
                await asyncio.sleep(5)
        
    def setup_logging(self):
        # ... (此函数内容不变)
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

    def register_command(self, name, handler, help_text="", category="默认", aliases=None, usage=None):
        # ... (此函数内容不变)
        if aliases is None: aliases = []
        usage = usage or help_text
        
        command_data = {
            "handler": handler, 
            "help": help_text, 
            "category": category, 
            "aliases": aliases,
            "usage": usage
        }

        for cmd_name in [name] + aliases:
            if cmd_name in self.commands:
                logging.warning(f"指令冲突: 指令 '{cmd_name}' 已被注册，将被覆盖。")
            self.commands[cmd_name] = command_data

    def register_task(self, task_key, function, command_name, help_text):
        # ... (此函数内容不变)
        self.task_functions[task_key] = function
        
        async def task_trigger_handler(event, parts):
            client = get_application().client 
            progress_message = await client.reply_to_admin(event, f"⏳ 好的，正在手动执行 **[{command_name}]** 任务...")
            
            if not progress_message: return

            client.pin_message(progress_message)
            
            final_text = f"✅ **[{command_name}]** 任务已成功执行完毕。"
            try:
                task_func = self.task_functions.get(task_key)
                if task_func:
                    result_text = await task_func(force_run=True)
                    if isinstance(result_text, str):
                        final_text = result_text
                else:
                    final_text = f"❌ 错误: 未找到与 `{task_key}` 关联的任务实现。"
            except Exception as e:
                final_text = f"❌ **[{command_name}]** 任务在执行过程中发生意外错误: `{e}`"
                format_and_log("SYSTEM", "任务执行失败", {'任务': command_name, '错误': str(e)}, level=logging.ERROR)
            finally:
                client.unpin_message(progress_message)

                try:
                    await client._cancel_message_deletion(progress_message)
                    edited_message = await progress_message.edit(final_text)
                    client._schedule_message_deletion(edited_message, settings.AUTO_DELETE.get('delay_admin_command'), "编辑后的助手回复")
                except MessageEditTimeExpiredError:
                    await client.reply_to_admin(event, final_text)

        self.register_command(command_name, task_trigger_handler, help_text=help_text, category="游戏任务")
        
    def load_plugins_and_commands(self, is_reload=False):
        # ... (此函数内容不变)
        if is_reload:
            self.commands.clear()
            self.task_functions.clear()
            self.startup_checks.clear()
            for handler, callback in list(self.client.client.list_event_handlers()):
                 if callback not in [self.client._message_handler, self.client._message_edited_handler, self.client._deleted_message_handler]:
                    self.client.client.remove_event_handler(callback, handler)

        format_and_log("SYSTEM", "插件加载", {'阶段': '开始动态扫描并加载...', '模式': '热重载' if is_reload else '首次加载'})
        load_all_plugins(self)
        format_and_log("SYSTEM", "插件加载", {'阶段': '所有插件加载完毕'})

    async def reload_plugins_and_commands(self):
        # ... (此函数内容不变)
        format_and_log("SYSTEM", "热重载", {'阶段': '开始...'})
        try:
            reload(sys.modules['config.settings'])
            format_and_log("SYSTEM", "热重载", {'模块': 'config.settings', '状态': '已重新加载'})
            
            for module_name in list(sys.modules.keys()):
                if module_name.startswith('app.plugins.'):
                    reload(sys.modules[module_name])
        except Exception as e:
            format_and_log("SYSTEM", "热重载失败", {'模块': '配置或插件模块', '错误': str(e)}, level=logging.ERROR)
            await self.client.send_admin_notification(f"❌ **热重载失败**：无法重新加载配置文件或插件，请检查日志。")
            return
            
        self.load_plugins_and_commands(is_reload=True)
        
        format_and_log("SYSTEM", "热重载", {'阶段': '重新执行启动后任务检查...'})
        if self.startup_checks:
            await asyncio.gather(*(check() for check in self.startup_checks if check))
        format_and_log("SYSTEM", "热重载", {'阶段': '启动后任务检查完毕'})
        format_and_log("SYSTEM", "热重载", {'阶段': '完成'})

    async def run(self):
        try:
            scheduler.start()
            
            await self.client.start()

            settings.ACCOUNT_ID = str(self.client.me.id)
            format_and_log("SYSTEM", "账户初始化", {'账户ID': settings.ACCOUNT_ID, '状态': '已设置为全局标识'})
            
            asyncio.create_task(self._redis_listener_loop())

            await self.client._cache_chat_info()

            self.load_plugins_and_commands()
            
            await self.client.warm_up_entity_cache()
            
            if self.startup_checks:
                await asyncio.gather(*(check() for check in self.startup_checks if check))
            
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
