# -*- coding: utf-8 -*-
import asyncio
import logging
import random
import re
import time
from datetime import datetime, timezone, timedelta

import pytz
from telethon import TelegramClient as TelethonTgClient, events
from telethon.errors.rpcerrorlist import (MessageDeleteForbiddenError,
                                          MessageEditTimeExpiredError,
                                          SlowModeWaitError)
from telethon.tl.functions.channels import (GetFullChannelRequest,
                                          GetParticipantRequest)
from telethon.tl.types import (Channel, Message, UpdateDeleteChannelMessages,
                               UpdateDeleteMessages)
from telethon.utils import get_display_name

from app.constants import STATE_KEY_LAST_TIMESTAMPS
from app.data_manager import data_manager
from app.logging_service import LogType, format_and_log, log_telegram_event
from config import settings


class CommandTimeoutError(asyncio.TimeoutError):
    def __init__(self, message, sent_message=None):
        super().__init__(message)
        self.sent_message = sent_message


class TelegramClient:
    def __init__(self):
        self.api_id = settings.API_ID
        self.api_hash = settings.API_HASH
        self.admin_id = settings.ADMIN_USER_ID
        self.me = None
        self.last_update_timestamp = datetime.now(pytz.timezone(settings.TZ))
        self.client = TelethonTgClient(settings.SESSION_FILE_PATH, self.api_id, self.api_hash)

        self.group_name_cache = {}
        self.slowmode_cache = {}
        self.last_message_timestamps = {}

        # --- [核心修改 v1.0] 使用优先级队列 ---
        self.message_queue = asyncio.PriorityQueue()
        self.deletion_tasks = {}
        self._pinned_messages = set()

        self.pending_replies = {}
        # [新增] 用于新的、更健壮的等待机制
        self.pending_mention_replies = {}
        
        self.fire_and_forget_tasks = set()

        all_configured_groups = settings.GAME_GROUP_IDS + ([settings.CONTROL_GROUP_ID] if settings.CONTROL_GROUP_ID else [])
        if getattr(settings, 'TEST_GROUP_ID', None):
            all_configured_groups.append(settings.TEST_GROUP_ID)

        self.client.on(events.NewMessage(chats=all_configured_groups))(self._unified_event_handler)
        self.client.on(events.MessageEdited(chats=all_configured_groups))(self._unified_event_handler)
        self.client.add_event_handler(self._deleted_message_handler,
                                      events.Raw(types=[UpdateDeleteChannelMessages, UpdateDeleteMessages]))

    async def _persist_timestamps(self):
        if data_manager and data_manager.db and data_manager.db.is_connected:
            await data_manager.save_value(STATE_KEY_LAST_TIMESTAMPS, self.last_message_timestamps)

    async def _load_timestamps(self):
        if data_manager and data_manager.db and data_manager.db.is_connected:
            loaded_timestamps = await data_manager.get_value(STATE_KEY_LAST_TIMESTAMPS, is_json=True, default={})
            self.last_message_timestamps = {int(k): v for k, v in loaded_timestamps.items()}
            format_and_log(LogType.SYSTEM, "状态加载", {'模块': '发言时间戳', '状态': '加载成功'})

    async def get_participant_info(self, chat_id, user_id):
        try:
            chat_entity = await self.client.get_entity(chat_id)
            user_entity = await self.client.get_entity(int(user_id))
            participant = await self.client(GetParticipantRequest(chat_entity, user_entity))
            if participant and hasattr(participant, 'participant'):
                 return getattr(participant.participant, 'until_date', None)
            return None
        except Exception as e:
            format_and_log(LogType.ERROR, "查询参与者信息失败", {'Chat': chat_id, 'User': user_id, '错误': str(e)})
            return None

    async def get_next_sendable_time(self, chat_id: int) -> datetime:
        now_utc = datetime.now(timezone.utc)
        my_id = self.me.id
        slow_mode_until = await self.get_participant_info(chat_id, my_id)
        last_sent_timestamp = self.last_message_timestamps.get(chat_id, 0)
        send_delay = random.uniform(settings.SEND_DELAY['min'], settings.SEND_DELAY['max'])
        internal_cooldown_until = datetime.fromtimestamp(last_sent_timestamp + send_delay, tz=timezone.utc)
        earliest_time = max(now_utc, internal_cooldown_until)
        if slow_mode_until and slow_mode_until > earliest_time:
            earliest_time = slow_mode_until
        return earliest_time

    async def reply_to_admin(self, event, text: str, schedule_deletion=True, **kwargs):
        try:
            reply_message = await event.reply(text, **kwargs)
            # [BUG 修正] 仅在调用者允许时才调度删除
            if schedule_deletion:
                self._schedule_message_deletion(reply_message, settings.AUTO_DELETE.get('delay_admin_command'), "助手对管理员的回复")
            return reply_message
        except Exception as e:
            format_and_log(LogType.ERROR, "回复管理员失败", {'错误': str(e)}, level=logging.ERROR)
            return None

    async def _message_sender_loop(self):
        while True:
            # --- [核心修改 v1.1] 从优先级队列中解包 ---
            # 优先级数字越小，越先被执行
            priority, (command, reply_to, future, target_chat_id, post_send_callback) = await self.message_queue.get()
            sent_message = None
            try:
                target_group = target_chat_id or (settings.GAME_GROUP_IDS[0] if settings.GAME_GROUP_IDS else 0)
                if not target_group:
                    raise Exception("No target group specified.")

                earliest_send_time = await self.get_next_sendable_time(target_group)
                now_utc = datetime.now(timezone.utc)
                wait_seconds = (earliest_send_time - now_utc).total_seconds()
                if wait_seconds > 0:
                    await asyncio.sleep(wait_seconds)

                final_reply_to = reply_to
                if target_group in settings.GAME_GROUP_IDS and settings.GAME_TOPIC_ID and not reply_to:
                    final_reply_to = settings.GAME_TOPIC_ID

                sent_message = await self.client.send_message(target_group, command, reply_to=final_reply_to)
                
                if sent_message:
                    self.last_message_timestamps[target_group] = time.time()
                    await self._persist_timestamps()
                    await log_telegram_event(self, LogType.CMD_SENT, sent_message, command=command, reply_to=final_reply_to)
                    if future: future.set_result(sent_message)
                else:
                    raise Exception("Failed to send message.")

            except Exception as e:
                if future: future.set_exception(e)
            
            finally:
                if post_send_callback and sent_message:
                    try:
                        post_send_callback(sent_message)
                    except Exception as cb_e:
                        format_and_log(LogType.ERROR, "发送后回调执行失败", {'错误': str(cb_e)}, level=logging.ERROR)
                
                self.message_queue.task_done()

    async def _send_command_and_get_message(self, command: str, reply_to: int = None,
                                           target_chat_id: int = None, post_send_callback=None, priority: int = 1):
        """
        [核心修改 v1.2] 内部发送接口增加 priority 参数
        - priority: 0=紧急, 1=普通, 2=后台
        """
        future = asyncio.Future()
        # 封装成 (priority, item) 元组放入队列
        item = (command, reply_to, future, target_chat_id, post_send_callback)
        task = asyncio.create_task(self.message_queue.put((priority, item)))

        if post_send_callback is None:
            await future
            return future.result()
        else:
            return task

    async def send_game_command_fire_and_forget(self, command: str, reply_to: int = None, target_chat_id: int = None, priority: int = 1):
        """[核心修改 v1.3] 对外接口透出 priority 参数"""
        strategy = settings.AUTO_DELETE_STRATEGIES['fire_and_forget']
        
        def schedule_deletion_callback(message: Message):
            self._schedule_message_deletion(message, strategy['delay_self'], "游戏指令(发后不理)")

        put_task = await self._send_command_and_get_message(
            command, reply_to, target_chat_id, 
            post_send_callback=schedule_deletion_callback,
            priority=priority
        )
        self.fire_and_forget_tasks.add(put_task)
        put_task.add_done_callback(self.fire_and_forget_tasks.discard)


    async def send_game_command_request_response(self, command: str, reply_to: int = None, timeout: int = None, target_chat_id: int = None, priority: int = 1) -> tuple[Message, Message]:
        """[核心修改 v1.3] 对外接口透出 priority 参数"""
        strategy = settings.AUTO_DELETE_STRATEGIES['request_response']
        sent_message = None
        try:
            sent_message, reply_message = await self._send_and_wait_for_response(command, reply_to=reply_to, timeout=timeout, target_chat_id=target_chat_id, priority=priority)
            self._schedule_message_deletion(sent_message, strategy['delay_self_on_reply'], "游戏指令(问答-成功)")
            return sent_message, reply_message
        except CommandTimeoutError as e:
            if e.sent_message: self._schedule_message_deletion(e.sent_message, strategy['delay_self_on_timeout'], "游戏指令(问答-超时)")
            raise e

    async def send_and_wait_for_mention_reply(self, command: str, final_pattern: str, timeout: int = None, target_chat_id: int = None, priority: int = 1) -> tuple[Message, Message]:
        """
        [新增] 健壮的等待函数，用于替代 send_and_wait_for_edit。
        它只关心最终结果，能抵抗事件乱序。
        """
        strategy = settings.AUTO_DELETE_STRATEGIES['request_response']
        sent_message = None
        waiter_id = None
        try:
            sent_message = await self._send_command_and_get_message(command, target_chat_id=target_chat_id, priority=priority)
            
            future = asyncio.Future()
            # 使用时间戳和随机数创建唯一ID
            waiter_id = f"{time.time()}-{random.randint(1000, 9999)}"

            my_display_name = get_display_name(self.me)
            # 构造一个能匹配 @username 或显示名称的正则表达式
            mention_pattern = f"@{self.me.username}" if self.me.username else re.escape(my_display_name)

            self.pending_mention_replies[waiter_id] = {
                'future': future,
                'mention_pattern': mention_pattern,
                'final_pattern': final_pattern
            }
            
            final_message = await asyncio.wait_for(future, timeout=timeout or settings.COMMAND_TIMEOUT)
            
            self._schedule_message_deletion(sent_message, strategy['delay_self_on_reply'], "游戏指令(提及-成功)")
            return sent_message, final_message
            
        except (asyncio.TimeoutError, CommandTimeoutError) as e:
            if sent_message:
                self._schedule_message_deletion(sent_message, strategy['delay_self_on_timeout'], "游戏指令(提及-超时)")
            raise CommandTimeoutError(f"等待指令 '{command}' 的最终@提及回复超时。", sent_message) from e
        finally:
            if waiter_id:
                self.pending_mention_replies.pop(waiter_id, None)

    async def _send_and_wait_for_response(self, command: str, final_pattern: str = ".*", timeout: int = None, reply_to: int = None, target_chat_id: int = None, priority: int = 1) -> tuple[Message, Message]:
        """[核心修改 v1.3] 对外接口透出 priority 参数"""
        timeout = timeout or settings.COMMAND_TIMEOUT; sent_message = None
        try:
            sent_message = await self._send_command_and_get_message(command, reply_to, target_chat_id, post_send_callback=None, priority=priority)
            future = asyncio.Future()
            self.pending_replies[sent_message.id] = {'future': future, 'pattern': final_pattern}
            reply_message = await asyncio.wait_for(future, timeout=timeout)
            return sent_message, reply_message
        except asyncio.TimeoutError as e:
            raise CommandTimeoutError(f"等待指令 '{command}' 的回复超时。", sent_message) from e
        finally:
            if sent_message: self.pending_replies.pop(sent_message.id, None)

    async def start(self):
        await self.client.start()
        self.me = await self.client.get_me()
        my_name = get_display_name(self.me)
        identity = "主控账号 (Admin)" if str(self.me.id) == str(self.admin_id) else "辅助账号 (Helper)"
        format_and_log(LogType.SYSTEM, "客户端状态", {'状态': '已成功连接', '当前用户': f"{my_name} (ID: {self.me.id})", '识别身份': identity})
        await self._load_timestamps()
        asyncio.create_task(self._message_sender_loop())

    async def _cache_chat_info(self):
        all_groups = set(settings.GAME_GROUP_IDS + ([settings.CONTROL_GROUP_ID] if settings.CONTROL_GROUP_ID else []))
        for group_id in all_groups:
            if not group_id: continue
            try:
                entity = await self.client.get_entity(group_id)
                self.group_name_cache[int(group_id)] = getattr(entity, 'title', f"ID:{group_id}")
                if isinstance(entity, Channel):
                    full_channel = await self.client(GetFullChannelRequest(channel=entity))
                    self.slowmode_cache[int(group_id)] = getattr(full_channel.full_chat, 'slowmode_seconds', 0) or 0
                else: self.slowmode_cache[int(group_id)] = 0
            except Exception as e:
                self.group_name_cache[int(group_id)] = f"ID:{group_id} (获取名称失败)"; self.slowmode_cache[int(group_id)] = 0
                logging.warning(f"获取群组 {group_id} 的完整信息失败: {e}")
        format_and_log(LogType.SYSTEM, "缓存初始化", {'模块': '群组信息', '缓存数量': len(self.group_name_cache), '慢速模式': self.slowmode_cache})

    def is_connected(self): return self.client.is_connected()
    async def disconnect(self): await self.client.disconnect()
    async def warm_up_entity_cache(self):
        try:
            async for _ in self.client.iter_dialogs(limit=20): pass
        except Exception: pass

    async def send_admin_notification(self, message: str, target_id: int = None):
        target = target_id or settings.CONTROL_GROUP_ID or self.admin_id
        try:
            await self.client.send_message(target, message, parse_mode='md')
        except Exception as e:
            format_and_log(LogType.ERROR, "发送管理员通知失败", {'目标ID': target, '错误': str(e)}, level=logging.ERROR)

    async def _sleep_and_delete(self, delay: int, message: Message):
        await asyncio.sleep(delay)
        task_key = (message.chat_id, message.id)
        if task_key in self._pinned_messages or task_key not in self.deletion_tasks:
            self.deletion_tasks.pop(task_key, None)
            return
        try:
            await self.client.delete_messages(entity=message.chat_id, message_ids=[message.id])
        except MessageDeleteForbiddenError:
            format_and_log(LogType.ERROR, "删除失败 (权限不足)", {'消息ID': message.id}, level=logging.ERROR)
        except Exception as e:
            format_and_log(LogType.ERROR, "删除失败 (异常)", {'消息ID': message.id, '错误': str(e)}, level=logging.ERROR)
        finally:
            self.deletion_tasks.pop(task_key, None)

    def _schedule_message_deletion(self, message: Message, delay_seconds: int, reason: str = "未指定"):
        if not settings.AUTO_DELETE.get('enabled', False) or not message or delay_seconds <= 0: return
        task_key = (message.chat_id, message.id)
        if task_key in self._pinned_messages: return
        if task_key in self.deletion_tasks: self.deletion_tasks[task_key].cancel()
        task = asyncio.create_task(self._sleep_and_delete(delay_seconds, message))
        self.deletion_tasks[task_key] = task

    async def _cancel_message_deletion(self, message: Message):
        if not message: return
        if task := self.deletion_tasks.pop((message.chat_id, message.id), None): task.cancel()

    def pin_message(self, message: Message, permanent: bool = False):
        if not message: return
        task_key = (message.chat_id, message.id)
        self._pinned_messages.add(task_key)
        if task := self.deletion_tasks.pop(task_key, None):
            task.cancel()
            if not permanent:
                self.unpin_message(message)

    def unpin_message(self, message: Message):
        if not message: return
        task_key = (message.chat_id, message.id)
        self._pinned_messages.discard(task_key)
        self._schedule_message_deletion(message, settings.AUTO_DELETE.get('delay_admin_command'), "解钉后自动清理")

    async def cancel_message_deletion_permanently(self, message: Message):
        if not message: return
        self.pin_message(message, permanent=True)

    async def _unified_event_handler(self, event):
        if not hasattr(event, 'message') or not hasattr(event.message, 'text') or not event.message.text: return
        log_type = LogType.MSG_SENT_SELF if event.out else LogType.MSG_RECV
        if isinstance(event, events.MessageEdited.Event): log_type = LogType.MSG_EDIT
        await log_telegram_event(self, log_type, event); self.last_update_timestamp = datetime.now(pytz.timezone(settings.TZ))
        
        # --- 统一的等待任务处理器 ---
        
        # 1. 处理旧的、基于 reply_to_msg_id 的等待
        if isinstance(event, events.NewMessage.Event) and event.is_reply:
            if wait_obj := self.pending_replies.get(event.reply_to_msg_id):
                if not wait_obj['future'].done() and re.search(wait_obj['pattern'], event.text, re.DOTALL):
                    wait_obj['future'].set_result(event.message)
        
        # 2. 处理新的、基于 @提及 的等待（对新消息和编辑事件都有效）
        waiters_to_remove = []
        for waiter_id, wait_obj in self.pending_mention_replies.items():
            if not wait_obj['future'].done():
                # 检查是否 @自己 并且内容匹配最终模式
                if re.search(wait_obj['mention_pattern'], event.text) and re.search(wait_obj['final_pattern'], event.text, re.DOTALL):
                    wait_obj['future'].set_result(event.message)
                    waiters_to_remove.append(waiter_id)
        
        # 清理已完成的等待任务
        for waiter_id in waiters_to_remove:
            self.pending_mention_replies.pop(waiter_id, None)


    async def _deleted_message_handler(self, update):
        chat_id = None
        if isinstance(update, UpdateDeleteChannelMessages): chat_id = int(f"-100{update.channel_id}")
        elif isinstance(update, UpdateDeleteMessages): return
        all_groups = settings.GAME_GROUP_IDS + ([settings.CONTROL_GROUP_ID] if settings.CONTROL_GROUP_ID else [])
        if chat_id and chat_id in all_groups:
            self.last_update_timestamp = datetime.now(pytz.timezone(settings.TZ))
            fake_event = type('FakeEvent', (object,), {'chat_id': chat_id})
            await log_telegram_event(self, LogType.MSG_DELETE, fake_event, deleted_ids=update.messages)
