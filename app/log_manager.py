# -*- coding: utf-8 -*-
import logging
import pytz
from datetime import datetime
from enum import Enum
from telethon import events
from telethon.tl.types import Message
from telethon.utils import get_display_name
from config import settings
from app.logger import format_and_log

class LogType(Enum):
    CMD_SENT = 1
    MSG_RECV = 2
    REPLY_RECV = 3
    MSG_EDIT = 4
    MSG_DELETE = 5
    MSG_SENT_SELF = 6

async def log_event(client, log_type: LogType, event, **kwargs):
    """
    [最终修复版]
    统一的事件日志记录器，现在直接接收客户端实例作为参数。
    """
    log_switches = settings.LOGGING_SWITCHES
    
    if log_type == LogType.CMD_SENT and log_switches.get('cmd_sent'):
        command, reply_to = kwargs.get('command'), kwargs.get('reply_to')
        log_data = {'指令': command, '回复至': reply_to, '消息ID': event.id}
        format_and_log("INFO", "指令已发送", log_data)

    elif log_type in [LogType.MSG_RECV, LogType.REPLY_RECV] and log_switches.get('msg_recv'):
        if log_type == LogType.REPLY_RECV and not log_switches.get('reply_recv'): return
        
        sender = await event.get_sender()
        sender_name = get_display_name(sender) if sender else "未知"
        sender_id = event.sender_id
        
        log_data = {
            '发送者': f"{sender_name} (ID: {sender_id})",
            '消息ID': event.id,
            '内容': event.text or "(无文本内容)"
        }

        if event.is_group and hasattr(event.message, 'reply_to') and event.message.reply_to and event.message.reply_to.reply_to_top_id:
            log_data['话题ID'] = event.message.reply_to.reply_to_top_id

        if event.is_group:
            chat_title = client.group_name_cache.get(event.chat_id, f"ID:{event.chat_id}")
            log_data = {'群组': f"{chat_title} [ID: {event.chat_id}]", **log_data}
        elif event.is_private:
            log_data = {'来源': "私聊", **log_data}

        log_title = "收到回复" if log_type == LogType.REPLY_RECV else "收到消息"
        format_and_log("INFO", log_title, log_data)
        
    elif log_type == LogType.MSG_EDIT and log_switches.get('log_edits'):
        sender = await event.get_sender()
        sender_name = get_display_name(sender) if sender else "未知"
        log_data = {
            '发送者': f"{sender_name} (ID: {event.sender_id})",
            '消息ID': event.id,
            '新内容': event.text or "(无文本内容)"
        }
        if event.is_group:
            chat_title = client.group_name_cache.get(event.chat_id, f"ID:{event.chat_id}")
            log_data = {'群组': f"{chat_title} [ID: {event.chat_id}]", **log_data}
        
        format_and_log("INFO", "消息已编辑", log_data)

    elif log_type == LogType.MSG_DELETE and log_switches.get('log_deletes'):
        chat_title = client.group_name_cache.get(event.chat_id, f"ID:{event.chat_id}")
        log_data = {
            '群组': f"{chat_title} [ID: {event.chat_id}]",
            '被删除消息ID': str(kwargs.get('deleted_ids', []))
        }
        format_and_log("INFO", "消息已删除", log_data)

    elif log_type == LogType.MSG_SENT_SELF and log_switches.get('original_log_enabled'):
        log_data = {
            '消息ID': event.id,
            '内容': event.text or "(无文本内容)"
        }
        if event.is_group:
            chat_title = client.group_name_cache.get(event.chat_id, f"ID:{event.chat_id}")
            log_data = {'群组': f"{chat_title} [ID: {event.chat_id}]", **log_data}
        elif event.is_private:
            log_data = {'目标': f"私聊 (ID: {event.chat_id})", **log_data}
        
        format_and_log("INFO", "发出消息", log_data)
