# -*- coding: utf-8 -*-
import asyncio
import logging
import random
import pytz
import collections
from datetime import datetime, timedelta
from telethon import TelegramClient as TelethonTgClient, events
from telethon.tl.types import Message
from telethon.utils import get_display_name
from config import settings
from app.logger import format_and_log

LOG_TYPE_MAP_ZH_TO_EN = {
    "系统": "system_activity", "任务": "task_activity",
    "指令": "cmd_sent", "消息": "msg_recv", "回复": "reply_recv",
    "原始": "original_log_enabled", "调试": "debug_log",
    "编辑": "log_edits", "删除": "log_deletes"
}

class TelegramClient:
    def __init__(self):
        self.api_id = settings.API_ID
        self.api_hash = settings.API_HASH
        self.admin_id = settings.ADMIN_USER_ID
        self.me = None
        self.raw_logger = logging.getLogger('raw_messages')
        format_and_log("SYSTEM", "客户端初始化", {'会话文件': settings.SESSION_FILE_PATH})
        self.client = TelethonTgClient(settings.SESSION_FILE_PATH, self.api_id, self.api_hash)
        self.message_queue = asyncio.Queue()
        self.pending_requests = {}
        self.sent_messages_log_tracking = collections.deque(maxlen=100)
        self.admin_commands = {}
        self.task_plugins = {}
        
        self.client.on(events.NewMessage(chats=settings.GAME_GROUP_ID))(self._message_handler)
        self.client.on(events.MessageEdited(chats=settings.GAME_GROUP_ID))(self._message_edited_handler)
        self.client.on(events.MessageDeleted(chats=settings.GAME_GROUP_ID))(self._message_deleted_handler)
        
        # *** 优化：根据账号角色，设置不同的指令监听器 ***
        if settings.IS_MAIN_ADMIN_ACCOUNT:
            # 如果是主管理账号，只监听自己发到“收藏夹”的指令
            format_and_log("SYSTEM", "指令监听", {'模式': '主管理账号 (收藏夹)'})
            self.client.on(events.NewMessage(
                outgoing=True,
                func=lambda e: e.is_private and e.chat_id == e.sender_id
            ))(self._admin_command_handler)
        else:
            # 如果是玩家账号，只监听来自指定管理员ID的“传入”私聊指令
            format_and_log("SYSTEM", "指令监听", {'模式': f'玩家账号 (管理员ID: {self.admin_id})'})
            self.client.on(events.NewMessage(
                incoming=True,
                from_users=self.admin_id,
                func=lambda e: e.is_private
            ))(self._admin_command_handler)

    async def _sleep_and_delete(self, delay: int, message_id: int):
        await asyncio.sleep(delay)
        try:
            await self.client.delete_messages(entity=settings.GAME_GROUP_ID, message_ids=[message_id])
        except Exception:
            pass # 忽略删除失败，例如消息已被手动删除

    def _schedule_message_deletion(self, message: Message, delay_seconds: int):
        if not settings.AUTO_DELETE.get('enabled', False) or not message:
            return
        asyncio.create_task(self._sleep_and_delete(delay_seconds, message.id))

    async def start(self):
        await self.client.start()
        self.me = await self.client.get_me()
        my_name = get_display_name(self.me)
        format_and_log("SYSTEM", "客户端状态", {'状态': '已成功连接 Telegram', '当前用户': f"{my_name} (ID: {self.me.id})"})
        asyncio.create_task(self._message_sender_loop())

    async def run_until_disconnected(self):
        await self.client.run_until_disconnected()

    async def _message_sender_loop(self):
        while True:
            command, reply_to, future = await self.message_queue.get()
            try:
                sent_message = await self.client.send_message(settings.GAME_GROUP_ID, command, reply_to=reply_to)
                self.sent_messages_log_tracking.append(sent_message.id)
                if settings.LOGGING_SWITCHES.get('original_log_enabled') and settings.LOGGING_SWITCHES.get('cmd_sent'):
                    self.raw_logger.info(f"[指令发送]\n{command}")
                if future:
                    self.pending_requests[sent_message.id] = (sent_message, future)
                else:
                    self._schedule_message_deletion(sent_message, settings.AUTO_DELETE.get('delay_fire_and_forget', 120))
                my_display_name = get_display_name(self.me) if self.me else "自己"
                log_data = {'发自': f"{my_display_name} (ID: {self.me.id if self.me else 'N/A'})", '指令': command, '回复给': reply_to if reply_to else "无"}
                format_and_log("CMD_SENT", "指令发送", log_data)
            except Exception as e:
                format_and_log("CMD_SENT", "指令发送", {'错误': f"发送 '{command}' 时失败: {e}"}, level=logging.ERROR)
                if future and not future.done(): future.set_exception(e)
            delay = random.uniform(settings.SEND_DELAY_MIN, settings.SEND_DELAY_MAX)
            await asyncio.sleep(delay)

    async def send_command(self, command: str, reply_to: int = None):
        await self.message_queue.put((command, reply_to, None))

    async def send_and_wait(self, command: str, reply_to: int = None, timeout: int = 30) -> tuple[Message, Message] | tuple[None, None]:
        future = asyncio.Future()
        await self.message_queue.put((command, reply_to, future))
        sent_message, reply_message = None, None
        try:
            sent_message, reply_message = await asyncio.wait_for(future, timeout=timeout)
            return sent_message, reply_message
        except asyncio.TimeoutError:
            for msg_id, (sent_msg, f) in list(self.pending_requests.items()):
                if f == future:
                    sent_message = sent_msg
                    del self.pending_requests[msg_id]
                    break
            return None, None
        finally:
            if sent_message:
                self._schedule_message_deletion(sent_message, settings.AUTO_DELETE.get('delay_after_reply', 60))

    async def _message_handler(self, event: events.NewMessage.Event):
        message = event.message
        is_reply_to_us = event.is_reply and message.reply_to_msg_id in self.pending_requests
        sender = await message.get_sender()
        beijing_tz = pytz.timezone(settings.TZ)
        sender_name = get_display_name(sender) if sender else "未知来源"
        from_str = f"{sender_name} (ID: {message.sender_id})"
        log_data = {'时间': message.date.astimezone(beijing_tz).strftime('%Y-%m-%d %H:%M:%S'),'来自': from_str,'内容': message.text}
        
        if is_reply_to_us:
            reply_to_id = message.reply_to_msg_id
            if reply_to_id in self.pending_requests:
                sent_message, future = self.pending_requests.pop(reply_to_id)
                if future and not future.done():
                    future.set_result((sent_message, message))
            log_data['回复给'] = f"消息ID: {reply_to_id}"
            format_and_log("REPLY_RECV", "收到回复", log_data)
            if settings.LOGGING_SWITCHES.get('original_log_enabled') and settings.LOGGING_SWITCHES.get('reply_recv'):
                self.raw_logger.info(f"[收到回复 from {from_str}]\n{message.text}")
        else:
            format_and_log("MSG_RECV", "收到消息", log_data)
            if settings.LOGGING_SWITCHES.get('original_log_enabled') and settings.LOGGING_SWITCHES.get('msg_recv'):
                self.raw_logger.info(f"[收到消息 from {from_str}]\n{message.text}")
                
    async def _message_edited_handler(self, event: events.MessageEdited.Event):
        beijing_tz = pytz.timezone(settings.TZ)
        log_data = {'时间': datetime.now(beijing_tz).strftime('%Y-%m-%d %H:%M:%S'), '消息ID': event.id, '原内容': event.original_update.message.message if hasattr(event.original_update, 'message') and event.original_update.message else "[无法获取]", '新内容': event.message.message}
        format_and_log("MSG_EDIT", "消息被编辑", log_data)
        if settings.LOGGING_SWITCHES.get('original_log_enabled') and settings.LOGGING_SWITCHES.get('log_edits'):
            raw_text = f"[消息编辑]\n- 消息ID: {event.id}\n- 原内容: {log_data['原内容']}\n- 新内容: {log_data['新内容']}"
            self.raw_logger.info(raw_text)

    async def _message_deleted_handler(self, event: events.MessageDeleted.Event):
        beijing_tz = pytz.timezone(settings.TZ)
        log_data = {'时间': datetime.now(beijing_tz).strftime('%Y-%m-%d %H:%M:%S'), '被删消息ID': ', '.join(map(str, event.deleted_ids))}
        format_and_log("MSG_DELETE", "消息被删除", log_data)

    def register_task(self, name, function):
        self.task_plugins[name] = function

    def register_admin_command(self, name, handler, help_text):
        self.admin_commands[name] = {'handler': handler, 'help': help_text}

    async def _admin_command_handler(self, event: events.NewMessage.Event):
        command_text = event.text.strip()
        used_prefix = None
        for prefix in settings.COMMAND_PREFIXES:
            if command_text.startswith(prefix):
                used_prefix = prefix
                break
        if not used_prefix: return
        command_with_args = command_text[len(used_prefix):]
        parts = command_with_args.split()
        if not parts: return
        user_command = parts[0]
        
        if user_command in self.admin_commands:
            matched_command = user_command
        else:
            matches = [cmd for cmd in self.admin_commands if cmd.startswith(user_command)]
            if len(matches) == 0:
                await event.reply(f"未知指令 `{user_command}`。\n请发送 `{used_prefix}帮助` 查看可用指令。", parse_mode='md')
                return
            if len(matches) > 1:
                await event.reply(f"指令 `{user_command}` 不明确，匹配到多个可能指令: `{'`, `'.join(matches)}`", parse_mode='md')
                return
            matched_command = matches[0]

        format_and_log("SYSTEM", "管理员指令", {'指令': matched_command, '参数': ' '.join(parts[1:])})
        handler_func = self.admin_commands[matched_command]['handler']
        await handler_func(self, event, parts)
