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

async def _log_raw_event(client, log_type: LogType, event, **kwargs):
    """[重构] 独立处理原始日志记录 (只写入文件)"""
    raw_logger = logging.getLogger('raw_messages')
    log_lines = []

    chat_title = client.group_name_cache.get(event.chat_id, f"ID:{event.chat_id}")
    log_lines.append(f"群组: {chat_title} ({event.chat_id})")
    
    topic_id = None
    if hasattr(event, 'message') and hasattr(event.message, 'reply_to') and event.message.reply_to and event.message.reply_to.reply_to_top_id:
        topic_id = event.message.reply_to.reply_to_top_id
    if topic_id:
        log_lines.append(f"话题ID: {topic_id}")

    if log_type == LogType.MSG_DELETE:
        log_lines.insert(0, "[消息删除]")
        deleted_ids = kwargs.get('deleted_ids', [])
        log_lines.append(f"被删除消息ID: {', '.join(map(str, deleted_ids))}")
        raw_logger.info("\n".join(log_lines))
        return

    sender = await event.get_sender()
    sender_name = get_display_name(sender) if sender else "未知"
    log_lines.append(f"发送者: {sender_name} (ID: {event.sender_id})")

    if log_type == LogType.CMD_SENT:
        log_lines.insert(0, "[指令发送]")
        log_lines.append(f"内容: {kwargs.get('command')}")
    elif log_type in [LogType.MSG_RECV, LogType.REPLY_RECV, LogType.MSG_SENT_SELF]:
        log_lines.insert(0, f"[{log_type.name}]") # 使用枚举名称
        log_lines.append(f"内容:\n{event.text}")
    elif log_type == LogType.MSG_EDIT:
        log_lines.insert(0, "[消息编辑]")
        log_lines.append(f"新内容:\n{event.text}")

    raw_logger.info("\n".join(log_lines))


async def log_event(client, log_type: LogType, event, **kwargs):
    """[重构版] 分离原始日志和实时日志"""
    # 步骤1: 如果开启，无条件记录原始日志到文件
    if settings.LOGGING_SWITCHES.get('original_log_enabled'):
        await _log_raw_event(client, log_type, event, **kwargs)

    # 步骤2: 根据各自开关，输出实时日志到控制台
    log_switches = settings.LOGGING_SWITCHES
    
    if log_type == LogType.CMD_SENT and log_switches.get('cmd_sent'):
        command, reply_to = kwargs.get('command'), kwargs.get('reply_to')
        log_data = {'指令': command, '回复至': reply_to, '消息ID': event.id}
        format_and_log("CMD_SENT", "指令已发送", log_data)

    elif log_type in [LogType.MSG_RECV, LogType.REPLY_RECV] and log_switches.get('msg_recv'):
        if log_type == LogType.REPLY_RECV and not log_switches.get('reply_recv'): return
        
        sender = await event.get_sender()
        sender_name = get_display_name(sender) if sender else "未知"
        log_data = {
            '发送者': f"{sender_name} (ID: {event.sender_id})",
            '消息ID': event.id,
            '内容': event.text or "(无文本内容)"
        }
        log_title = "收到回复" if log_type == LogType.REPLY_RECV else "收到消息"
        log_key = "REPLY_RECV" if log_type == LogType.REPLY_RECV else "MSG_RECV"
        format_and_log(log_key, log_title, log_data)
        
    elif log_type == LogType.MSG_EDIT and log_switches.get('log_edits'):
        sender = await event.get_sender()
        sender_name = get_display_name(sender) if sender else "未知"
        log_data = { '发送者': f"{sender_name} (ID: {event.sender_id})", '消息ID': event.id, '新内容': event.text or "(无文本内容)" }
        format_and_log("MSG_EDIT", "消息已编辑", log_data)

    elif log_type == LogType.MSG_DELETE and log_switches.get('log_deletes'):
        log_data = { '被删除消息ID': str(kwargs.get('deleted_ids', [])) }
        format_and_log("MSG_DELETE", "消息已删除", log_data)

    elif log_type == LogType.MSG_SENT_SELF and log_switches.get('msg_sent_self'):
        log_data = { '消息ID': event.id, '内容': event.text or "(无文本内容)" }
        format_and_log("MSG_SENT_SELF", "发出消息 (来自其他设备)", log_data)
