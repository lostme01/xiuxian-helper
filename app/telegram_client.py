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

        self.message_queue = asyncio.Queue()
        self.deletion_tasks = {}
        self._pinned_messages = set()

        self.pending_replies = {}
        self.pending_edits = {}

        all_configured_groups = settings.GAME_GROUP_IDS + ([settings.CONTROL_GROUP_ID] if settings.CONTROL_GROUP_ID else [])
        if getattr(settings, 'TEST_GROUP_ID', None):
            all_configured_groups.append(settings.TEST_GROUP_ID)

        self.client.on(events.NewMessage(chats=all_configured_groups))(self._unified_event_handler)
        self.client.on(events.MessageEdited(chats=all_configured_groups))(self._unified_event_handler)
        self.client.add_event_handler(self._deleted_message_handler,
                                      events.Raw(types=[UpdateDeleteChannelMessages, UpdateDeleteMessages]))

    async def _persist_timestamps(self):
        if data_manager and data_manager.db:
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
            # participant.participant can be None if user is not in channel
            if participant and hasattr(participant, 'participant'):
                 return getattr(participant.participant, 'until_date', None)
            return None
        except Exception as e:
            format_and_log(LogType.ERROR, "查询参与者信息失败", {'Chat': chat_id, 'User': user_id, '错误': str(e)})
            return None

    # [新增] 核心方法：计算最早可发送时间
    async def get_next_sendable_time(self, chat_id: int) -> datetime:
        """
        计算并返回在指定聊天中，当前客户端最早可以发送消息的UTC时间。
        会综合考虑慢速模式和内部发送延迟。
        """
        now_utc = datetime.now(timezone.utc)
        
        # 1. 检查慢速模式 (来自Telethon的GetParticipant)
        my_id = self.me.id
        slow_mode_until = await self.get_participant_info(chat_id, my_id)
        
        # 2. 检查内部发送冷却 (send_delay)
        last_sent_timestamp = self.last_message_timestamps.get(chat_id, 0)
        send_delay = random.uniform(settings.SEND_DELAY['min'], settings.SEND_DELAY['max'])
        internal_cooldown_until = datetime.fromtimestamp(last_sent_timestamp + send_delay, tz=timezone.utc)

        # 取两者中更晚的时间点
        earliest_time = max(now_utc, internal_cooldown_until)
        if slow_mode_until and slow_mode_until > earliest_time:
            earliest_time = slow_mode_until

        return earliest_time


    async def reply_to_admin(self, event, text: str, **kwargs):
        try:
            reply_message = await event.reply(text, **kwargs)
            self._schedule_message_deletion(reply_message, settings.AUTO_DELETE.get('delay_admin_command'),
                                            "助手对管理员的回复")
            return reply_message
        except Exception as e:
            format_and_log(LogType.ERROR, "回复管理员失败", {'错误': str(e)}, level=logging.ERROR)
            return None

    async def _message_sender_loop(self):
        while True:
            command, reply_to, future, target_chat_id = await self.message_queue.get()
            try:
                target_group = target_chat_id or (settings.GAME_GROUP_IDS[0] if settings.GAME_GROUP_IDS else 0)
                if not target_group:
                    if future and not future.done(): future.set_exception(Exception("No target group specified."))
                    continue

                # 在发送前再次计算实际需要等待的时间
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
                    if future and not future.done(): future.set_result(sent_message)
                else:
                    raise Exception("Failed to send message.")

            except Exception as e:
                if future and not future.done(): future.set_exception(e)

    async def _send_command_and_get_message(self, command: str, reply_to: int = None,
                                           target_chat_id: int = None) -> Message:
        future = asyncio.Future()
        await self.message_queue.put((command, reply_to, future, target_chat_id))
        return await future

    async def send_game_command_request_response(self, command: str, reply_to: int = None, timeout: int = None,
                                                 target_chat_id: int = None) -> tuple[Message, Message]:
        strategy = settings.AUTO_DELETE_STRATEGIES['request_response']
        sent_message = None
        try:
            sent_message, reply_message = await self._send_and_wait_for_response(
                command, reply_to=reply_to, timeout=timeout, target_chat_id=target_chat_id
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

    async def send_and_wait_for_edit(self, command: str, initial_pattern: str, final_pattern: str,
                                     timeout: int = None, target_chat_id: int = None) -> tuple[Message, Message]:
        strategy = settings.AUTO_DELETE_STRATEGIES['request_response']
        sent_message = None; initial_reply_id = None
        try:
            sent_message, initial_reply = await self._send_and_wait_for_response(
                command, final_pattern=initial_pattern, target_chat_id=target_chat_id
            )
            initial_reply_id = initial_reply.id
            future = asyncio.Future()
            self.pending_edits[initial_reply_id] = {'future': future, 'pattern': final_pattern}
            final_message = await asyncio.wait_for(future, timeout=timeout or settings.COMMAND_TIMEOUT)
            self._schedule_message_deletion(sent_message, strategy['delay_self_on_reply'], "游戏指令(编辑-成功)")
            return sent_message, final_message
        except (asyncio.TimeoutError, CommandTimeoutError) as e:
            if sent_message:
                self._schedule_message_deletion(sent_message, strategy['delay_self_on_timeout'], "游戏指令(编辑-超时)")
            raise CommandTimeoutError(f"等待指令 '{command}' 的编辑回复超时。", sent_message) from e
        finally:
            if initial_reply_id: self.pending_edits.pop(initial_reply_id, None)

    async def _send_and_wait_for_response(self, command: str, final_pattern: str = ".*", timeout: int = None,
                                          reply_to: int = None, target_chat_id: int = None) -> tuple[Message, Message]:
        timeout = timeout or settings.COMMAND_TIMEOUT; sent_message = None
        try:
            future = asyncio.Future()
            sent_message = await self._send_command_and_get_message(command, reply_to, target_chat_id)
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
        format_and_log(LogType.SYSTEM, "客户端状态",
                       {'状态': '已成功连接', '当前用户': f"{my_name} (ID: {self.me.id})", '识别身份': identity})
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
                else:
                    self.slowmode_cache[int(group_id)] = 0
            except Exception as e:
                self.group_name_cache[int(group_id)] = f"ID:{group_id} (获取名称失败)"
                self.slowmode_cache[int(group_id)] = 0
                logging.warning(f"获取群组 {group_id} 的完整信息失败: {e}")
        format_and_log(LogType.SYSTEM, "缓存初始化",
                       {'模块': '群组信息', '缓存数量': len(self.group_name_cache), '慢速模式': self.slowmode_cache})

    def is_connected(self): return self.client.is_connected()
    async def disconnect(self): await self.client.disconnect()
    async def warm_up_entity_cache(self):
        try:
            async for _ in self.client.iter_dialogs(limit=20): pass
        except Exception: pass

    async def send_admin_notification(self, message: str, target_id: int = None):
        try:
            target = target_id or settings.CONTROL_GROUP_ID or self.admin_id
            await self.client.send_message(target, message, parse_mode='md')
        except Exception: pass

    async def _sleep_and_delete(self, delay: int, message: Message):
        await asyncio.sleep(delay)
        task_key = (message.chat_id, message.id)
        if task_key in self._pinned_messages: self.deletion_tasks.pop(task_key, None); return
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

    def pin_message(self, message: Message):
        if not message: return
        task_key = (message.chat_id, message.id); self._pinned_messages.add(task_key)
        if task := self.deletion_tasks.pop(task_key, None): task.cancel()

    def unpin_message(self, message: Message):
        if not message: return
        task_key = (message.chat_id, message.id); self._pinned_messages.discard(task_key)
        self._schedule_message_deletion(message, settings.AUTO_DELETE.get('delay_admin_command'), "解钉后自动清理")

    async def _unified_event_handler(self, event):
        if not hasattr(event, 'message') or not hasattr(event.message, 'text') or not event.message.text: return
        log_type = LogType.MSG_SENT_SELF if event.out else LogType.MSG_RECV
        if isinstance(event, events.MessageEdited.Event): log_type = LogType.MSG_EDIT
        await log_telegram_event(self, log_type, event); self.last_update_timestamp = datetime.now(pytz.timezone(settings.TZ))
        if isinstance(event, events.NewMessage.Event) and event.is_reply:
            if wait_obj := self.pending_replies.get(event.reply_to_msg_id):
                if not wait_obj['future'].done() and re.search(wait_obj['pattern'], event.text, re.DOTALL):
                    wait_obj['future'].set_result(event.message)
        if isinstance(event, events.MessageEdited.Event):
            if wait_obj := self.pending_edits.get(event.id):
                if not wait_obj['future'].done() and re.search(wait_obj['pattern'], event.text, re.DOTALL):
                    wait_obj['future'].set_result(event.message)

    async def _deleted_message_handler(self, update):
        chat_id = None
        if isinstance(update, UpdateDeleteChannelMessages): chat_id = int(f"-100{update.channel_id}")
        elif isinstance(update, UpdateDeleteMessages): return
        all_groups = settings.GAME_GROUP_IDS + ([settings.CONTROL_GROUP_ID] if settings.CONTROL_GROUP_ID else [])
        if chat_id and chat_id in all_groups:
            self.last_update_timestamp = datetime.now(pytz.timezone(settings.TZ))
            fake_event = type('FakeEvent', (object,), {'chat_id': chat_id})
            await log_telegram_event(self, LogType.MSG_DELETE, fake_event, deleted_ids=update.messages)
