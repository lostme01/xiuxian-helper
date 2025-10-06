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
from telethon.tl.functions.account import UpdateStatusRequest
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
        self.last_update_timestamp = datetime.now(pytz.timezone(settings.TZ))
        self.client = TelethonTgClient(settings.SESSION_FILE_PATH, self.api_id, self.api_hash)
        
        self.group_name_cache = {}
        self.slowmode_cache = {} 
        self.last_message_timestamps = {} 
        
        self.message_queue = asyncio.Queue()
        self.pending_req_by_id = {}
        self.pending_edit_waits = {}
        self.deletion_tasks = {}
        self._pinned_messages = set()

        all_configured_groups = settings.GAME_GROUP_IDS + ([settings.CONTROL_GROUP_ID] if settings.CONTROL_GROUP_ID else [])
        if getattr(settings, 'TEST_GROUP_ID', None):
            all_configured_groups.append(settings.TEST_GROUP_ID)
        
        listen_mode = None if settings.LOGGING_SWITCHES.get('original_log_enabled', False) else True
        
        self.client.on(events.NewMessage(chats=all_configured_groups, incoming=listen_mode))(self._message_handler)
        self.client.on(events.MessageEdited(chats=all_configured_groups, incoming=listen_mode))(self._message_edited_handler)
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
        from app.logger import format_and_log
        strategy = settings.AUTO_DELETE_STRATEGIES['request_response']
        if timeout is None: 
            timeout = settings.COMMAND_TIMEOUT
        
        reply_future = asyncio.Future()
        sent_message = None
        try:
            format_and_log("DEBUG", "send_game_command_request_response", {'阶段': '开始发送指令', '指令': command})
            sent_message = await self._send_command_and_get_message(command, reply_to=reply_to, target_chat_id=target_chat_id)
            format_and_log("DEBUG", "send_game_command_request_response", {'阶段': '指令已发送，开始等待回复', '消息ID': sent_message.id})
            
            self.pending_req_by_id[sent_message.id] = (reply_future, sent_message.chat_id)
            
            reply_message = await asyncio.wait_for(reply_future, timeout=timeout)
            format_and_log("DEBUG", "send_game_command_request_response", {'阶段': '已收到回复', '回复消息ID': reply_message.id})
            
            self._schedule_message_deletion(sent_message, strategy['delay_self_on_reply'], "游戏指令(问答-成功)")
            
            return sent_message, reply_message
        except asyncio.TimeoutError:
            format_and_log("DEBUG", "send_game_command_request_response", {'阶段': '等待回复超时', '指令': command})
            if sent_message:
                self._schedule_message_deletion(sent_message, strategy['delay_self_on_timeout'], "游戏指令(问答-超时)")
            raise CommandTimeoutError(f"等待指令 '{command}' 的回复超时 ({timeout}秒)。")
        finally:
            if sent_message:
                self.pending_req_by_id.pop(sent_message.id, None)
            format_and_log("DEBUG", "send_game_command_request_response", {'阶段': '清理请求监听器', '消息ID': getattr(sent_message, 'id', 'N/A')})


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

    async def send_and_wait_for_edit(self, command: str, initial_reply_pattern: str, timeout: int = None) -> tuple[Message, Message]:
        from app.logger import format_and_log
        if timeout is None:
            timeout = settings.COMMAND_TIMEOUT
        
        sent_message = None
        try:
            format_and_log("DEBUG", "send_and_wait_for_edit", {'阶段': '开始', '指令': command})
            sent_message = await self._send_command_and_get_message(command)
            
            edit_future = asyncio.Future()
            self.pending_edit_waits[sent_message.id] = {
                "future": edit_future,
                "pattern": initial_reply_pattern,
                "initial_reply_id": None
            }

            format_and_log("DEBUG", "send_and_wait_for_edit", {'阶段': '进入等待状态', '总超时': f"{timeout}s"})
            final_message = await asyncio.wait_for(edit_future, timeout=timeout)
            format_and_log("DEBUG", "send_and_wait_for_edit", {'阶段': '成功捕获到最终事件', '消息ID': final_message.id})
            
            return sent_message, final_message

        except asyncio.TimeoutError as e:
            format_and_log("DEBUG", "send_and_wait_for_edit", {'阶段': '等待超时或失败', '错误': str(e)})
            raise CommandTimeoutError(f"等待指令 '{command}' 的响应或编辑超时 (总时长 {timeout} 秒)。") from e
        finally:
            if sent_message:
                self.pending_edit_waits.pop(sent_message.id, None)
            format_and_log("DEBUG", "send_and_wait_for_edit", {'阶段': '清理编辑监听器', '消息ID': getattr(sent_message, 'id', 'N/A')})


    async def start(self):
        # [重构] 启动流程简化，只负责登录和报告状态
        await self.client.start()
        self.me = await self.client.get_me()
        my_name = get_display_name(self.me)
        identity = "主控账号 (Admin)" if str(self.me.id) == str(self.admin_id) else "辅助账号 (Helper)"
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
        await asyncio.sleep(delay)
        task_key = (message.chat_id, message.id)
        
        if task_key in self._pinned_messages:
            self.deletion_tasks.pop(task_key, None)
            return
            
        try:
            await self.client.delete_messages(entity=message.chat_id, message_ids=[message.id])
        except Exception:
            pass
        finally:
            self.deletion_tasks.pop(task_key, None)

    def _schedule_message_deletion(self, message: Message, delay_seconds: int, reason: str = "未指定"):
        from app.logger import format_and_log
        if not settings.AUTO_DELETE.get('enabled', False) or not message or not delay_seconds or delay_seconds <= 0: 
            return
        
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

    async def _message_handler(self, event: events.NewMessage.Event):
        log_type = LogType.MSG_SENT_SELF if event.out else LogType.MSG_RECV
        await log_event(self, log_type, event)
        self.last_update_timestamp = datetime.now(pytz.timezone(settings.TZ))
        
        if not event.out:
            if self.pending_req_by_id and event.is_reply and event.message.reply_to_msg_id in self.pending_req_by_id:
                future, _ = self.pending_req_by_id.pop(event.message.reply_to_msg_id)
                if future and not future.done():
                    await log_event(self, LogType.REPLY_RECV, event)
                    future.set_result(event.message)
                return

            if self.pending_edit_waits and event.is_reply and event.message.reply_to_msg_id in self.pending_edit_waits:
                wait_obj = self.pending_edit_waits[event.message.reply_to_msg_id]
                if re.search(wait_obj['pattern'], event.text, re.DOTALL):
                    wait_obj['initial_reply_id'] = event.id
                    format_and_log("DEBUG", "智能等待", {'状态': '已捕获初始回复', '消息ID': event.id})
                return

            if self.pending_req_by_id and event.sender_id in settings.GAME_BOT_IDS:
                pending_in_chat = sorted([
                    (msg_id, future) for msg_id, (future, chat_id) in self.pending_req_by_id.items()
                    if chat_id == event.chat_id and not future.done()
                ], key=lambda x: x[0], reverse=True)
                
                if pending_in_chat:
                    latest_msg_id, future_to_resolve = pending_in_chat[0]
                    await log_event(self, LogType.REPLY_RECV, event, note="智能关联")
                    future_to_resolve.set_result(event.message)
                    self.pending_req_by_id.pop(latest_msg_id)

    async def _message_edited_handler(self, event: events.MessageEdited.Event):
        await log_event(self, LogType.MSG_EDIT, event)
        self.last_update_timestamp = datetime.now(pytz.timezone(settings.TZ))
        
        if self.pending_edit_waits:
            for sent_msg_id, wait_obj in list(self.pending_edit_waits.items()):
                if wait_obj['initial_reply_id'] == event.id:
                    future = wait_obj['future']
                    if future and not future.done():
                        future.set_result(event.message)
                    self.pending_edit_waits.pop(sent_msg_id, None)
                    return
    
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
            self.last_update_timestamp = datetime.now(pytz.timezone(settings.TZ))
            fake_event = type('FakeEvent', (object,), {'chat_id': chat_id})
            await log_event(self, LogType.MSG_DELETE, fake_event, deleted_ids=update.messages)
