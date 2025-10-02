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
from datetime import datetime, timedelta
from telethon import TelegramClient as TelethonTgClient, events
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.tl.types import Message, UpdateDeleteChannelMessages, UpdateDeleteMessages, Channel
from telethon.errors.rpcerrorlist import MessageEditTimeExpiredError, SlowModeWaitError
from telethon.utils import get_display_name
from config import settings
from app.log_manager import log_event, LogType
from app.context import get_application

class CommandTimeoutError(asyncio.TimeoutError):
    pass

class TelegramClient:
    def __init__(self):
        self.api_id, self.api_hash, self.admin_id = settings.API_ID, settings.API_HASH, settings.ADMIN_USER_ID
        self.me = None
        self.is_admin_self = False
        self.last_update_timestamp = datetime.now(pytz.timezone(settings.TZ))
        self.client = TelethonTgClient(settings.SESSION_FILE_PATH, self.api_id, self.api_hash)
        
        self.group_name_cache = {}
        self.slowmode_cache = {} 
        self.last_message_timestamps = {} 
        
        self.message_queue = asyncio.Queue()
        self.pending_req_by_id = {}
        self.deletion_tasks = {}
        self._pinned_messages = set()

        all_groups = settings.GAME_GROUP_IDS + ([settings.CONTROL_GROUP_ID] if settings.CONTROL_GROUP_ID else [])
        if getattr(settings, 'TEST_GROUP_ID', None):
            all_groups.append(settings.TEST_GROUP_ID)
        
        self.client.on(events.NewMessage(chats=all_groups, incoming=True))(self._message_handler)
        self.client.on(events.MessageEdited(chats=all_groups, incoming=True))(self._message_edited_handler)
        self.client.add_event_handler(self._deleted_message_handler, events.Raw(types=[UpdateDeleteChannelMessages, UpdateDeleteMessages]))
        
    async def reply_to_admin(self, event, text: str, **kwargs):
        from app.logger import format_and_log
        try:
            reply_message = await event.reply(text, **kwargs)
            self._schedule_message_deletion(reply_message, settings.AUTO_DELETE.get('delay_admin_command'), "助手对管理员的回复")
            return reply_message
        except Exception as e:
            format_and_log("SYSTEM", "回复管理员失败", {'错误': str(e)}, level=logging.ERROR)
            try:
                await self.client.send_message(self.admin_id, f"⚠️ 在群组 {getattr(event, 'chat_id', 'N/A')} 中回复指令失败: {e}")
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

                sent_message = None
                for _ in range(2):
                    try:
                        sent_message = await self.client.send_message(target_group, command, reply_to=reply_to)
                        self.last_message_timestamps[target_group] = time.time()
                        break 
                    except SlowModeWaitError as e:
                        await asyncio.sleep(e.seconds + random.uniform(0.5, 1.5))
                
                if sent_message:
                    await log_event(LogType.CMD_SENT, sent_message, command=command, reply_to=reply_to)
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

    # --- 改造：将默认 timeout 与全局设置关联 ---
    async def send_game_command_request_response(self, command: str, reply_to: int = None, timeout: int = None, target_chat_id: int = None) -> tuple[Message, Message]:
        strategy = settings.AUTO_DELETE_STRATEGIES['request_response']
        # 如果调用时没有指定 timeout，则使用全局配置
        if timeout is None: 
            timeout = settings.COMMAND_TIMEOUT
        
        reply_future = asyncio.Future()
        sent_message = None
        try:
            sent_message = await self._send_command_and_get_message(command, reply_to=reply_to, target_chat_id=target_chat_id)
            self.pending_req_by_id[sent_message.id] = reply_future
            reply_message = await asyncio.wait_for(reply_future, timeout=timeout)
            
            self._schedule_message_deletion(sent_message, strategy['delay_self_on_reply'], "游戏指令(问答-成功)")
            return sent_message, reply_message
        except asyncio.TimeoutError:
            if sent_message:
                self._schedule_message_deletion(sent_message, strategy['delay_self_on_timeout'], "游戏指令(问答-超时)")
            raise CommandTimeoutError(f"等待指令 '{command}' 的回复超时 ({timeout}秒)。")
        finally:
            if sent_message:
                self.pending_req_by_id.pop(sent_message.id, None)

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

    async def send_and_wait_for_edit(self, command: str, initial_reply_pattern: str, timeout: int = 30) -> tuple[Message | None, Message | None]:
        edit_future = asyncio.Future()
        initial_reply = None
        async def edit_handler(event: events.MessageEdited.Event):
            if initial_reply and event.message.id == initial_reply.id:
                if not edit_future.done():
                    edit_future.set_result(event.message)
        self.client.add_event_handler(edit_handler, events.MessageEdited)
        try:
            # 这里的 timeout 仍然是总超时，但其内部的 send_game_command_request_response 会使用全局默认值
            _sent_message, initial_reply = await self.send_game_command_request_response(command, timeout=timeout)
            if not re.search(initial_reply_pattern, initial_reply.text):
                return initial_reply, None
            remaining_timeout = timeout - (datetime.now(pytz.utc) - _sent_message.date).total_seconds()
            if remaining_timeout <= 0: return initial_reply, None
            final_message = await asyncio.wait_for(edit_future, timeout=remaining_timeout)
            return initial_reply, final_message
        except (CommandTimeoutError, asyncio.TimeoutError):
            raise asyncio.TimeoutError(f"等待指令 '{command}' 的响应或编辑超时。")
        finally:
            self.client.remove_event_handler(edit_handler, events.MessageEdited)
    
    async def start(self):
        await self.client.start()
        self.me = await self.client.get_me()
        self.is_admin_self = self.me.id == self.admin_id
        my_name = get_display_name(self.me)
        identity = "主控账号 (Admin)" if self.is_admin_self else "辅助账号 (Helper)"
        from app.logger import format_and_log
        format_and_log("SYSTEM", "客户端状态", {'状态': '已成功连接', '当前用户': f"{my_name} (ID: {self.me.id})", '识别身份': identity})
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

    # ... (文件其余部分保持不变) ...
    def is_connected(self): return self.client.is_connected()
    async def disconnect(self): await self.client.disconnect()
    async def warm_up_entity_cache(self):
        try:
            async for _ in self.client.iter_dialogs(limit=15): pass
        except Exception: pass

    async def send_admin_notification(self, message: str):
        try: await self.client.send_message(self.admin_id, message, parse_mode='md')
        except Exception: pass

    async def _sleep_and_delete(self, delay: int, message: Message):
        await asyncio.sleep(delay)
        task_key = (message.chat_id, message.id)
        
        if task_key in self._pinned_messages:
            self.deletion_tasks.pop(task_key, None)
            return
            
        try:
            await self.client.delete_messages(entity=message.chat_id, message_ids=[message.id])
        except Exception as e:
            logging.warning(f"自动删除消息 {message.id} (位于对话 {message.chat_id}) 失败: {e}")
        finally:
            self.deletion_tasks.pop(task_key, None)

    def _schedule_message_deletion(self, message: Message, delay_seconds: int, reason: str = "未指定"):
        from app.logger import format_and_log
        if not settings.AUTO_DELETE.get('enabled', False) or not message or not delay_seconds or delay_seconds <= 0: 
            return
        
        task_key = (message.chat_id, message.id)
        if task_key in self.deletion_tasks:
            self.deletion_tasks[task_key].cancel()

        task = asyncio.create_task(self._sleep_and_delete(delay_seconds, message))
        self.deletion_tasks[task_key] = task
        
        format_and_log("DEBUG", "安排消息删除", {"消息ID": message.id, "对话ID": message.chat_id, "延迟(秒)": delay_seconds, "场景": reason})

    async def _cancel_message_deletion(self, message: Message):
        from app.logger import format_and_log
        if not message: return
        task_key = (message.chat_id, message.id)
        task = self.deletion_tasks.pop(task_key, None)
        if task:
            task.cancel()
            format_and_log("DEBUG", "取消消息删除", {"消息ID": message.id})

    def pin_message(self, message: Message):
        if not message: return
        task_key = (message.chat_id, message.id)
        self._pinned_messages.add(task_key)
        from app.logger import format_and_log
        format_and_log("DEBUG", "消息保护", {"操作": "钉住", "消息ID": message.id})

    def unpin_message(self, message: Message):
        if not message: return
        task_key = (message.chat_id, message.id)
        self._pinned_messages.discard(task_key)
        from app.logger import format_and_log
        format_and_log("DEBUG", "消息保护", {"操作": "解钉", "消息ID": message.id})

    async def run_until_disconnected(self): await self.client.run_until_disconnected()

    async def _message_handler(self, event: events.NewMessage.Event):
        from app.logger import format_and_log
        log_type = LogType.MSG_SENT_SELF if event.out else LogType.MSG_RECV
        await log_event(log_type, event)
        self.last_update_timestamp = datetime.now(pytz.timezone(settings.TZ))
        
        is_reply_to_us = not event.out and event.is_reply and event.message.reply_to_msg_id in self.pending_req_by_id
        if is_reply_to_us:
            format_and_log("DEBUG", "客户端流程 -> _message_handler", {'阶段': '检测到有效回复', '回复的消息ID': event.message.reply_to_msg_id})
            await log_event(LogType.REPLY_RECV, event)
            reply_to_id = event.message.reply_to_msg_id
            future = self.pending_req_by_id.get(reply_to_id)
            if future and not future.done():
                future.set_result(event.message)

    async def _message_edited_handler(self, event: events.MessageEdited.Event):
        await log_event(LogType.MSG_EDIT, event)
    
    async def _deleted_message_handler(self, update):
        chat_id = None
        if isinstance(update, UpdateDeleteChannelMessages):
            chat_id = int(f"-100{update.channel_id}")
        elif isinstance(update, UpdateDeleteMessages):
            return

        all_groups = settings.GAME_GROUP_IDS + ([settings.CONTROL_GROUP_ID] if settings.CONTROL_GROUP_ID else [])
        if getattr(settings, 'TEST_GROUP_ID', None):
            all_groups.append(settings.TEST_GROUP_ID)
            
        if chat_id and chat_id in all_groups:
            fake_event = type('FakeEvent', (object,), {'chat_id': chat_id})
            await log_event(LogType.MSG_DELETE, fake_event, deleted_ids=update.messages)
