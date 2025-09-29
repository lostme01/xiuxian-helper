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
from thefuzz import process
raw_logger = logging.getLogger('raw_messages')
class TelegramClient:
    def __init__(self):
        self.api_id, self.api_hash, self.admin_id = settings.API_ID, settings.API_HASH, settings.ADMIN_USER_ID
        self.me = None
        self.task_plugins = {}
        self.last_update_timestamp = datetime.now(pytz.timezone(settings.TZ))
        self.client = TelethonTgClient(settings.SESSION_FILE_PATH, self.api_id, self.api_hash)
        self.message_queue = asyncio.Queue()
        
        # --- 核心修改：使用两个字典来分别通过ID和Future快速查找 ---
        self.pending_req_by_id = {}
        self.pending_req_by_future = {}

        self.sent_messages_log_tracking = collections.deque(maxlen=100)
        self.admin_commands, self.command_aliases = {}, {}
        self.client.on(events.NewMessage(chats=settings.GAME_GROUP_IDS))(self._message_handler)
        self.client.on(events.MessageEdited(chats=settings.GAME_GROUP_IDS))(self._message_edited_handler)
        self.client.on(events.MessageDeleted(chats=settings.GAME_GROUP_IDS))(self._message_deleted_handler)
        if settings.IS_MAIN_ADMIN_ACCOUNT: self.client.on(events.NewMessage(outgoing=True, func=lambda e: e.is_private and e.chat_id == e.sender_id))(self._admin_command_handler)
        else: self.client.on(events.NewMessage(incoming=True, from_users=self.admin_id, func=lambda e: e.is_private))(self._admin_command_handler)

    def register_admin_command(self, name, handler, help_text, category="默认", aliases=None):
        if aliases is None: aliases = []
        self.admin_commands[name] = {"handler": handler, "help": help_text, "category": category}
        for alias in aliases: self.command_aliases[alias] = name

    async def _admin_command_handler(self, event: events.NewMessage.Event):
        if settings.LOGGING_SWITCHES.get('original_log_enabled', False) and event.text:
            raw_logger.info(f"来自管理员 (ID: {event.sender_id}):\n{event.text}")
        format_and_log("SYSTEM", "收到管理员指令", {'来源': f"Admin (ID: {event.sender_id})", '指令': event.text})
        command_text = event.text.strip()
        used_prefix = next((p for p in settings.COMMAND_PREFIXES if command_text.startswith(p)), None)
        if not used_prefix: return
        command_body = command_text[len(used_prefix):].strip()
        parts = ["帮助"] if not command_body else command_body.split()
        cmd_name = self.command_aliases.get(parts[0], parts[0])
        if cmd_name == "帮助": await self._handle_help_command(event, parts); return
        if cmd_name in self.admin_commands:
            handler_func = self.admin_commands[cmd_name]["handler"]
            if handler_func: await handler_func(self, event, parts)
        else:
            all_cmd_names = list(self.admin_commands.keys()) + list(self.command_aliases.keys())
            best_match, score = process.extractOne(cmd_name, all_cmd_names)
            if score > 70: await event.reply(f"❌ 找不到指令 `{used_prefix}{cmd_name}`\n\n🤔 您是不是想输入: `{used_prefix}{best_match}`？", parse_mode='md')
            else: await event.reply(f"❌ 找不到指令 `{used_prefix}{cmd_name}`", parse_mode='md')

    async def _handle_help_command(self, event, parts):
        prefix = settings.COMMAND_PREFIXES[0]
        if len(parts) > 1:
            target_cmd = self.command_aliases.get(parts[1], parts[1])
            if target_cmd in self.admin_commands:
                detail = self.admin_commands[target_cmd]['help']
                await event.reply(f"**指令详情: `{prefix}{target_cmd}`**\n\n{detail}", parse_mode='md')
            else: await event.reply(f"找不到指令 `{prefix}{parts[1]}` 的详细帮助。", parse_mode='md')
            return
        categorized_cmds = {}
        for name, data in self.admin_commands.items():
            if data['handler'] is None: continue
            category = data["category"]
            if category not in categorized_cmds: categorized_cmds[category] = []
            categorized_cmds[category].append(f"`{prefix}{name}`")
        sorted_categories, help_text = sorted(categorized_cmds.keys()), "🤖 **TG 游戏助手指令菜单**"
        for category in sorted_categories: help_text += f"\n\n**{category}**\n{' '.join(sorted(categorized_cmds[category]))}"
        help_text += f"\n\n使用 `{prefix}帮助 <指令名>` 查看具体用法。"
        await event.reply(help_text, parse_mode='md')
    
    async def _message_sender_loop(self):
        while True:
            self.last_update_timestamp = datetime.now(pytz.timezone(settings.TZ))
            command, reply_to, future, target_chat_id = await self.message_queue.get()
            try:
                target_group = target_chat_id if target_chat_id else (settings.GAME_GROUP_IDS[0] if settings.GAME_GROUP_IDS else 0)
                if not target_group: continue
                sent_message = await self.client.send_message(target_group, command, reply_to=reply_to)
                my_display_name = get_display_name(self.me) if self.me else "自己"
                log_data = {'发自': f"{my_display_name} (ID: {self.me.id if self.me else 'N/A'})", '指令': command}
                format_and_log("CMD_SENT", "指令发送", log_data)
                self.sent_messages_log_tracking.append(sent_message.id)
                if future:
                    # --- 核心修改：同时在两个字典中注册 ---
                    self.pending_req_by_id[sent_message.id] = future
                    self.pending_req_by_future[future] = sent_message
                else: self._schedule_message_deletion(sent_message, settings.AUTO_DELETE.get('delay_fire_and_forget', 120))
            except Exception as e:
                if future and not future.done(): future.set_exception(e)
            await asyncio.sleep(random.uniform(settings.SEND_DELAY_MIN, settings.SEND_DELAY_MAX))

    async def start(self):
        await self.client.start()
        self.me = await self.client.get_me()
        my_name = get_display_name(self.me)
        format_and_log("SYSTEM", "客户端状态", {'状态': '已成功连接 Telegram', '当前用户': f"{my_name} (ID: {self.me.id})"})
        asyncio.create_task(self._message_sender_loop())

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
        try: await self.client.delete_messages(entity=message.chat_id, message_ids=[message.id])
        except Exception: pass

    def _schedule_message_deletion(self, message: Message, delay_seconds: int):
        if not settings.AUTO_DELETE.get('enabled', False) or not message: return
        asyncio.create_task(self._sleep_and_delete(delay_seconds, message))

    async def run_until_disconnected(self): await self.client.run_until_disconnected()
    async def send_command(self, command: str, reply_to: int = None, target_chat_id: int = None): await self.message_queue.put((command, reply_to, None, target_chat_id))
    
    async def send_and_wait(self, command: str, reply_to: int = None, timeout: int = 60, target_chat_id: int = None) -> tuple[Message | None, Message | None]:
        future = asyncio.Future()
        await self.message_queue.put((command, reply_to, future, target_chat_id))
        sent_message, reply_message = None, None
        try:
            sent_message, reply_message = await asyncio.wait_for(future, timeout=timeout)
            return sent_message, reply_message
        except asyncio.TimeoutError:
            # --- 核心修改：通过 future 直接查找并清理，无需循环 ---
            if future in self.pending_req_by_future:
                sent_message = self.pending_req_by_future.pop(future)
                # 别忘了也从另一个字典中清理
                self.pending_req_by_id.pop(sent_message.id, None)
            return sent_message, None
        finally:
            if sent_message: self._schedule_message_deletion(sent_message, settings.AUTO_DELETE.get('delay_after_reply', 60))

    async def send_command_chain(self, commands: list[str], initial_reply_to_message: Message = None):
        last_message = initial_reply_to_message
        chat_id = initial_reply_to_message.chat_id if initial_reply_to_message else None
        for command in commands:
            reply_to_id = last_message.id if last_message else None
            sent_message, _ = await self.send_and_wait(command, reply_to=reply_to_id, timeout=5, target_chat_id=chat_id)
            if not sent_message: break
            last_message = sent_message

    def register_task(self, name, function): self.task_plugins[name] = function
    
    async def _message_handler(self, event: events.NewMessage.Event):
        self.last_update_timestamp = datetime.now(pytz.timezone(settings.TZ))
        if settings.LOGGING_SWITCHES.get('original_log_enabled', False) and event.message.text:
            sender = await event.message.get_sender()
            sender_name = get_display_name(sender) if sender else f"未知 (ID: {event.message.sender_id})"
            raw_logger.info(f"来自 {sender_name}:\n{event.message.text}")
        message = event.message
        
        # --- 核心修改：使用新的字典来处理 ---
        is_reply_to_us = event.is_reply and message.reply_to_msg_id in self.pending_req_by_id

        sender = await message.get_sender()
        sender_name = get_display_name(sender) if sender else "未知来源"
        log_data = {'时间': self.last_update_timestamp.strftime('%Y-%m-%d %H:%M:%S'),'来自': f"{sender_name} (ID: {message.sender_id})",'内容': message.text}
        
        if is_reply_to_us:
            reply_to_id = message.reply_to_msg_id
            if reply_to_id in self.pending_req_by_id:
                future = self.pending_req_by_id.pop(reply_to_id)
                sent_message = self.pending_req_by_future.pop(future, None)
                if future and not future.done(): future.set_result((sent_message, message))
            format_and_log("REPLY_RECV", "收到回复", log_data)
        else: format_and_log("MSG_RECV", "收到消息", log_data)

    async def _message_edited_handler(self, event: events.MessageEdited.Event):
        self.last_update_timestamp = datetime.now(pytz.timezone(settings.TZ))
        if settings.LOGGING_SWITCHES.get('original_log_enabled', False) and event.message.message:
            sender = await event.get_sender()
            sender_name = get_display_name(sender) if sender else f"未知 (ID: {event.sender_id})"
            raw_logger.info(f"来自 {sender_name} (消息被编辑):\n{event.message.message}")
        format_and_log("MSG_EDIT", "消息被编辑", {'消息ID': event.id, '新内容': event.message.message})

    async def _message_deleted_handler(self, event: events.MessageDeleted.Event):
        self.last_update_timestamp = datetime.now(pytz.timezone(settings.TZ))
        format_and_log("DELETE", "消息被删除", {'被删消息ID': ', '.join(map(str, event.deleted_ids))})
