# -*- coding: utf-8 -*-
import asyncio
import logging
import random
import pytz
import collections
import functools
import shlex
import re
import time
import json
from datetime import datetime, timedelta, timezone
from telethon import TelegramClient as TelethonTgClient, events
from telethon.tl.functions.channels import GetFullChannelRequest, GetParticipantRequest
from telethon.tl.functions.account import UpdateStatusRequest
from telethon.tl.types import Message, UpdateDeleteChannelMessages, UpdateDeleteMessages, Channel
from telethon.errors.rpcerrorlist import MessageEditTimeExpiredError, SlowModeWaitError, MessageDeleteForbiddenError
from telethon.utils import get_display_name
from config import settings
from app.log_manager import log_event, LogType
from app.context import get_application
from app.data_manager import data_manager

class CommandTimeoutError(asyncio.TimeoutError):
    def __init__(self, message, sent_message=None):
        super().__init__(message)
        self.sent_message = sent_message

class TelegramClient:
    def __init__(self):
        self.api_id, self.api_hash, self.admin_id = settings.API_ID, settings.API_HASH, settings.ADMIN_USER_ID
        self.me = None
        self.last_update_timestamp = datetime.now(pytz.timezone(settings.TZ))
        self.client = TelethonTgClient(settings.SESSION_FILE_PATH, self.api_id, self.api_hash)
        
        self.group_name_cache = {}
        self.slowmode_cache = {} 
        self.last_message_timestamps = {} 
        
        self.message_queue = asyncio.Queue()
        # [REFACTOR] 移除 pending_waits，新的等待逻辑将不再依赖它
        # self.pending_waits = {}
        self.deletion_tasks = {}
        self._pinned_messages = set()

        all_configured_groups = settings.GAME_GROUP_IDS + ([settings.CONTROL_GROUP_ID] if settings.CONTROL_GROUP_ID else [])
        if getattr(settings, 'TEST_GROUP_ID', None):
            all_configured_groups.append(settings.TEST_GROUP_ID)
        
        listen_mode = None if settings.LOGGING_SWITCHES.get('original_log_enabled', False) else True
        
        # [REFACTOR] 全局消息处理器现在只负责日志记录，不再处理等待逻辑
        self.client.on(events.NewMessage(chats=all_configured_groups, incoming=listen_mode))(self._logging_handler)
        self.client.on(events.MessageEdited(chats=all_configured_groups, incoming=listen_mode))(self._logging_handler)
        self.client.add_event_handler(self._deleted_message_handler, events.Raw(types=[UpdateDeleteChannelMessages, UpdateDeleteMessages]))

    async def _persist_timestamps(self):
        if data_manager and data_manager.db:
            await data_manager.save_value("last_message_timestamps", self.last_message_timestamps)

    async def _load_timestamps(self):
        if data_manager and data_manager.db:
            loaded_timestamps = await data_manager.get_value("last_message_timestamps", is_json=True, default={})
            self.last_message_timestamps = {int(k): v for k, v in loaded_timestamps.items()}
            from app.logger import format_and_log
            format_and_log("SYSTEM", "状态加载", {'模块': '发言时间戳', '状态': '加载成功'})
        
    async def get_participant_info(self, chat_id, user_id):
        try:
            chat_entity = await self.client.get_entity(chat_id)
            user_entity = await self.client.get_entity(int(user_id))
            participant = await self.client(GetParticipantRequest(chat_entity, user_entity))
            return getattr(participant.participant, 'until_date', None)
        except Exception as e:
            from app.logger import format_and_log
            format_and_log("ERROR", "查询参与者信息失败", {'Chat': chat_id, 'User': user_id, '错误': str(e)})
            return None

    async def reply_to_admin(self, event, text: str, **kwargs):
        from app.logger import format_and_log
        try:
            reply_message = await event.reply(text, **kwargs)
            self._schedule_message_deletion(reply_message, settings.AUTO_DELETE.get('delay_admin_command'), "助手对管理员的回复")
            return reply_message
        except Exception as e:
            format_and_log("SYSTEM", "回复管理员失败", {'错误': str(e)}, level=logging.ERROR)
            try:
                if settings.CONTROL_GROUP_ID:
                    chat_type = "群组" if event.is_group else "私聊"
                    chat_id = getattr(event, 'chat_id', 'N/A')
                    await self.client.send_message(settings.CONTROL_GROUP_ID, f"⚠️ 在 {chat_type} (`{chat_id}`) 中回复指令时失败: `{e}`")
            except Exception: pass
            return None

    async def _message_sender_loop(self):
        while True:
            command, reply_to, future, target_chat_id = await self.message_queue.get()
            try:
                target_group = target_chat_id if target_chat_id else (settings.GAME_GROUP_IDS[0] if settings.GAME_GROUP_IDS else 0)
                if not target_group: continue

                slowmode_seconds = self.slowmode_cache.get(target_group, 0)
                last_sent_time = self.last_message_timestamps.get(target_group, 0)
                
                if slowmode_seconds > 0:
                    time_since_last_sent = time.time() - last_sent_time
                    if time_since_last_sent < slowmode_seconds:
                        wait_time = slowmode_seconds - time_since_last_sent + random.uniform(0.5, 1.5)
                        await asyncio.sleep(wait_time)

                final_reply_to = reply_to
                if target_group in settings.GAME_GROUP_IDS and settings.GAME_TOPIC_ID and not reply_to:
                    final_reply_to = settings.GAME_TOPIC_ID

                sent_message = None
                for _ in range(2):
                    try:
                        sent_message = await self.client.send_message(target_group, command, reply_to=final_reply_to)
                        self.last_message_timestamps[target_group] = time.time()
                        await self._persist_timestamps()
                        break 
                    except SlowModeWaitError as e:
                        await asyncio.sleep(e.seconds + random.uniform(0.5, 1.5))
                
                if sent_message:
                    await log_event(self, LogType.CMD_SENT, sent_message, command=command, reply_to=final_reply_to)
                    if future and not future.done():
                        future.set_result(sent_message)
                else:
                    raise Exception("Failed to send message after retrying for slow mode.")

            except Exception as e:
                if future and not future.done():
                    future.set_exception(e)
            
            delay = random.uniform(settings.SEND_DELAY['min'], settings.SEND_DELAY['max'])
            await asyncio.sleep(delay)

    async def _send_command_and_get_message(self, command: str, reply_to: int = None, target_chat_id: int = None) -> Message:
        future = asyncio.Future()
        await self.message_queue.put((command, reply_to, future, target_chat_id))
        return await future

    async def send_game_command_request_response(self, command: str, reply_to: int = None, timeout: int = None, target_chat_id: int = None) -> tuple[Message, Message]:
        strategy = settings.AUTO_DELETE_STRATEGIES['request_response']
        sent_message = None
        try:
            # [REFACTOR] 调用新的核心等待函数
            sent_message, reply_message = await self._send_and_wait_for_response(
                command, 
                final_pattern=".*",
                reply_to=reply_to, 
                timeout=timeout, 
                target_chat_id=target_chat_id
            )
            self._schedule_message_deletion(sent_message, strategy['delay_self_on_reply'], "游戏指令(问答-成功)")
            return sent_message, reply_message
        except CommandTimeoutError as e:
            if e.sent_message:
                self._schedule_message_deletion(e.sent_message, strategy['delay_self_on_timeout'], "游戏指令(问答-超时)")
            raise e

    async def send_game_command_fire_and_forget(self, command: str, reply_to: int = None, target_chat_id: int = None):
        strategy = settings.AUTO_DELETE_STRATEGIES['fire_and_forget']
        sent_message = await self._send_command_and_get_message(command, reply_to, target_chat_id)
        self._schedule_message_deletion(sent_message, strategy['delay_self'], "游戏指令(发后不理)")

    async def send_game_command_long_task(self, command: str, reply_to: int = None, target_chat_id: int = None) -> tuple[Message, Message]:
        strategy = settings.AUTO_DELETE_STRATEGIES['long_task']
        sent_message, reply_message = await self.send_game_command_request_response(command, reply_to, target_chat_id=target_chat_id)
        if strategy.get('delay_self', 0) == 0:
            await self._cancel_message_deletion(sent_message)
        return sent_message, reply_message

    async def send_and_wait_for_edit(self, command: str, initial_pattern: str, final_pattern: str, timeout: int = None) -> tuple[Message, Message]:
        strategy = settings.AUTO_DELETE_STRATEGIES['request_response']
        sent_message = None
        try:
            # [REFACTOR] 调用新的核心等待函数
            sent_message, final_message = await self._send_and_wait_for_response(
                command,
                initial_pattern=initial_pattern,
                final_pattern=final_pattern,
                timeout=timeout
            )
            self._schedule_message_deletion(sent_message, strategy['delay_self_on_reply'], "游戏指令(编辑-成功)")
            return sent_message, final_message
        except CommandTimeoutError as e:
            if e.sent_message:
                self._schedule_message_deletion(e.sent_message, strategy['delay_self_on_timeout'], "游戏指令(编辑-超时)")
            raise e

    # [NEW] 统一的、健壮的核心等待函数
    async def _send_and_wait_for_response(self, command: str, final_pattern: str, initial_pattern: str = None, timeout: int = None, reply_to: int = None, target_chat_id: int = None) -> tuple[Message, Message]:
        from app.logger import format_and_log
        if timeout is None:
            timeout = settings.COMMAND_TIMEOUT
        
        sent_message = None
        q = asyncio.Queue()

        async def handler(event):
            # 这是一个临时的事件处理器，只处理与本次指令相关的消息
            if hasattr(event, 'reply_to_msg_id') and event.reply_to_msg_id == sent_message.id:
                await q.put(event.message)
            # 处理针对初始回复的编辑事件
            elif isinstance(event, events.MessageEdited.Event):
                # 检查队列中是否有已收到的初始消息
                if not q.empty():
                    initial_msg = q.get_nowait()
                    # 如果编辑的是初始消息，则放入队列；否则，放回队列
                    if initial_msg.id == event.id:
                        await q.put(event.message)
                    else:
                        await q.put(initial_msg)

        self.client.add_event_handler(handler, events.NewMessage)
        self.client.add_event_handler(handler, events.MessageEdited)

        try:
            sent_message = await self._send_command_and_get_message(command, reply_to, target_chat_id)
            format_and_log("DEBUG", "统一等待: 已发送指令", {'ID': sent_message.id, '指令': command})
            
            initial_reply = None
            start_time = time.monotonic()

            while True:
                remaining_time = timeout - (time.monotonic() - start_time)
                if remaining_time <= 0:
                    raise asyncio.TimeoutError()

                message = await asyncio.wait_for(q.get(), timeout=remaining_time)
                
                # 检查是否是最终消息
                if re.search(final_pattern, message.text, re.DOTALL):
                    format_and_log("DEBUG", "统一等待: 捕获到最终消息", {'ID': message.id})
                    return sent_message, message
                
                # 如果不是最终消息，但匹配初始模式，则记录下来
                elif initial_pattern and re.search(initial_pattern, message.text, re.DOTALL):
                    format_and_log("DEBUG", "统一等待: 捕获到初始消息", {'ID': message.id})
                    # 将初始消息放回队列，以便后续的编辑事件可以找到它
                    await q.put(message)
                    initial_reply = message

        except asyncio.TimeoutError as e:
            format_and_log("WARNING", "统一等待: 超时", {'指令': command, '总时长': f"{timeout}s"})
            raise CommandTimeoutError(f"等待指令 '{command}' 的回复超时。", sent_message) from e
        finally:
            self.client.remove_event_handler(handler, events.NewMessage)
            self.client.remove_event_handler(handler, events.MessageEdited)
            format_and_log("DEBUG", "统一等待: 清理临时监听器", {'指令': command})

    async def start(self):
        await self.client.start()
        self.me = await self.client.get_me()
        my_name = get_display_name(self.me)
        identity = "主控账号 (Admin)" if str(self.me.id) == str(self.admin_id) else "辅助账号 (Helper)"
        from app.logger import format_and_log
        format_and_log("SYSTEM", "客户端状态", {'状态': '已成功连接', '当前用户': f"{my_name} (ID: {self.me.id})", '识别身份': identity})
        await self._load_timestamps()
        asyncio.create_task(self._message_sender_loop())

    async def _cache_chat_info(self):
        all_groups = set(settings.GAME_GROUP_IDS + ([settings.CONTROL_GROUP_ID] if settings.CONTROL_GROUP_ID else []) + ([getattr(settings, 'TEST_GROUP_ID', None)] if getattr(settings, 'TEST_GROUP_ID', None) else []))
        for group_id in all_groups:
            if not group_id: continue
            try:
                entity = await self.client.get_entity(group_id)
                self.group_name_cache[int(group_id)] = getattr(entity, 'title', f"ID:{group_id}")
                
                if isinstance(entity, Channel):
                    full_channel = await self.client(GetFullChannelRequest(channel=entity))
                    self.slowmode_cache[int(group_id)] = getattr(full_channel.full_chat, 'slowmode_seconds', 0) or 0
                else:
                    self.slowmode_cache[int(group_id)] = 0

            except Exception as e:
                self.group_name_cache[int(group_id)] = f"ID:{group_id} (获取名称失败)"
                self.slowmode_cache[int(group_id)] = 0
                logging.warning(f"获取群组 {group_id} 的完整信息失败: {e}")
        from app.logger import format_and_log
        format_and_log("SYSTEM", "缓存初始化", {'模块': '群组信息', '缓存数量': len(self.group_name_cache), '慢速模式': self.slowmode_cache})

    def is_connected(self): return self.client.is_connected()
    async def disconnect(self): await self.client.disconnect()
    async def warm_up_entity_cache(self):
        try:
            async for _ in self.client.iter_dialogs(limit=20): pass
        except Exception: pass

    async def send_admin_notification(self, message: str):
        try:
            target = settings.CONTROL_GROUP_ID if settings.CONTROL_GROUP_ID else self.admin_id
            await self.client.send_message(target, message, parse_mode='md')
        except Exception: 
            pass

    async def _sleep_and_delete(self, delay: int, message: Message):
        from app.logger import format_and_log
        log_data = {"消息ID": message.id, "Chat ID": message.chat_id, "延迟": delay}
        format_and_log("DEBUG", "删除任务: 启动", log_data)
        
        await asyncio.sleep(delay)
        
        log_data.pop("延迟")
        format_and_log("DEBUG", "删除任务: 延时结束", log_data)

        task_key = (message.chat_id, message.id)
        if task_key in self._pinned_messages:
            self.deletion_tasks.pop(task_key, None)
            format_and_log("DEBUG", "删除任务: 已钉住, 放弃删除", log_data)
            return
            
        try:
            format_and_log("DEBUG", "删除任务: 正在调用 delete_messages", log_data)
            await self.client.delete_messages(entity=message.chat_id, message_ids=[message.id])
            format_and_log("DEBUG", "删除任务: delete_messages 调用完成", log_data)
            
            await asyncio.sleep(2) 
            
            format_and_log("DEBUG", "删除任务: 开始自检", log_data)
            check_msg = await self.client.get_messages(message.chat_id, ids=message.id)
            
            if check_msg is None:
                format_and_log("DEBUG", "删除任务: 自检成功, 消息已删除", log_data)
            else:
                format_and_log("WARNING", "删除任务: 自检失败, 消息仍存在 (静默失败)", {
                    **log_data,
                    "可能原因": "助手在该聊天中可能缺少'删除消息'的管理员权限。"
                }, level=logging.WARNING)

        except MessageDeleteForbiddenError:
            format_and_log("ERROR", "删除任务: 失败 (权限不足)", {
                **log_data,
                "错误": "MessageDeleteForbiddenError: 请为此助手在目标群组添加'删除消息'的管理员权限。"
            }, level=logging.ERROR)
        except Exception as e:
            format_and_log("ERROR", "删除任务: 失败 (发生异常)", {
                **log_data,
                "错误类型": type(e).__name__,
                "错误信息": str(e)
            }, level=logging.ERROR)
        finally:
            self.deletion_tasks.pop(task_key, None)

    def _schedule_message_deletion(self, message: Message, delay_seconds: int, reason: str = "未指定"):
        from app.logger import format_and_log
        if not settings.AUTO_DELETE.get('enabled', False) or not message or not delay_seconds or delay_seconds <= 0: return
        task_key = (message.chat_id, message.id)
        if task_key in self._pinned_messages:
            format_and_log("DEBUG", "消息删除-跳过", {"原因": "消息已被钉住", "消息ID": message.id})
            return
        if task_key in self.deletion_tasks:
            self.deletion_tasks[task_key].cancel()
        task = asyncio.create_task(self._sleep_and_delete(delay_seconds, message))
        self.deletion_tasks[task_key] = task
        format_and_log("DEBUG", "安排消息删除", {"消息ID": message.id, "延迟(秒)": delay_seconds, "场景": reason})

    async def _cancel_message_deletion(self, message: Message):
        from app.logger import format_and_log
        if not message: return
        task = self.deletion_tasks.pop((message.chat_id, message.id), None)
        if task:
            task.cancel()
            format_and_log("DEBUG", "取消消息删除", {"消息ID": message.id})

    def pin_message(self, message: Message):
        if not message: return
        from app.logger import format_and_log
        task_key = (message.chat_id, message.id)
        self._pinned_messages.add(task_key)
        task = self.deletion_tasks.pop(task_key, None)
        if task:
            task.cancel()
            format_and_log("DEBUG", "消息保护", {"操作": "钉住并取消删除", "消息ID": message.id})
        else:
            format_and_log("DEBUG", "消息保护", {"操作": "钉住", "消息ID": message.id})

    def unpin_message(self, message: Message):
        if not message: return
        from app.logger import format_and_log
        task_key = (message.chat_id, message.id)
        self._pinned_messages.discard(task_key)
        format_and_log("DEBUG", "消息保护", {"操作": "解钉", "消息ID": message.id})
        self._schedule_message_deletion(message, settings.AUTO_DELETE.get('delay_admin_command'), "解钉后自动清理")
    
    # [REFACTOR] 全局处理器现在只负责记录日志
    async def _logging_handler(self, event):
        log_type = LogType.MSG_SENT_SELF if event.out else LogType.MSG_RECV
        if isinstance(event, events.MessageEdited.Event):
            log_type = LogType.MSG_EDIT
        
        await log_event(self, log_type, event)
        self.last_update_timestamp = datetime.now(pytz.timezone(settings.TZ))
    
    async def _deleted_message_handler(self, update):
        chat_id = None
        if isinstance(update, UpdateDeleteChannelMessages):
            chat_id = int(f"-100{update.channel_id}")
        elif isinstance(update, UpdateDeleteMessages):
            return
        all_groups = settings.GAME_GROUP_IDS + ([settings.CONTROL_GROUP_ID] if settings.CONTROL_GROUP_ID else [])
        if getattr(settings, 'TEST_GROUP_ID', None):
            all_configured_groups.append(settings.TEST_GROUP_ID)
        if chat_id and chat_id in all_groups:
            self.last_update_timestamp = datetime.now(pytz.timezone(settings.TZ))
            fake_event = type('FakeEvent', (object,), {'chat_id': chat_id})
            await log_event(self, LogType.MSG_DELETE, fake_event, deleted_ids=update.messages)
