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
    """[新功能] 独立处理原始日志记录"""
    raw_logger = logging.getLogger('raw_messages')
    log_lines = []

    # 统一获取基础信息
    chat_title = client.group_name_cache.get(event.chat_id, f"ID:{event.chat_id}")
    log_lines.append(f"群组: {chat_title} ({event.chat_id})")
    
    # [BUG修复] 专门为删除事件创建一个分支，因为它使用 FakeEvent
    if log_type == LogType.MSG_DELETE:
        log_lines.insert(0, "[消息删除]")
        deleted_ids = kwargs.get('deleted_ids', [])
        log_lines.append(f"被删除消息ID: {', '.join(map(str, deleted_ids))}")
        raw_logger.info("\n".join(log_lines))
        return

    # 话题ID
    topic_id = None
    if event.is_group and hasattr(event, 'message') and hasattr(event.message, 'reply_to') and event.message.reply_to and event.message.reply_to.reply_to_top_id:
        topic_id = event.message.reply_to.reply_to_top_id
    if topic_id:
        log_lines.append(f"话题ID: {topic_id}")

    if log_type in [LogType.MSG_RECV, LogType.REPLY_RECV, LogType.MSG_EDIT, LogType.MSG_SENT_SELF]:
        sender = await event.get_sender()
        sender_name = get_display_name(sender) if sender else "未知"
        log_lines.append(f"发送者: {sender_name} (ID: {event.sender_id})")

    # 根据事件类型构建日志
    if log_type == LogType.CMD_SENT:
        log_lines.insert(0, "[指令发送]")
        log_lines.append(f"内容: {kwargs.get('command')}")
    elif log_type == LogType.MSG_RECV:
        log_lines.insert(0, "[收到消息]")
        log_lines.append(f"内容:\n{event.text}")
    elif log_type == LogType.REPLY_RECV:
        log_lines.insert(0, "[收到回复]")
        log_lines.append(f"内容:\n{event.text}")
    elif log_type == LogType.MSG_EDIT:
        log_lines.insert(0, "[消息编辑]")
        log_lines.append(f"新内容:\n{event.text}")
    elif log_type == LogType.MSG_SENT_SELF:
        log_lines.insert(0, "[发出消息]")
        log_lines.append(f"内容:\n{event.text}")

    raw_logger.info("\n".join(log_lines))


async def log_event(client, log_type: LogType, event, **kwargs):
    """
    [重构版]
    统一的事件日志记录器。
    - 如果原始日志开启，则优先记录详细的原始日志。
    - 之后再根据各自信道开关，决定是否输出到控制台/app.log。
    """
    # [需求实现] 步骤1: 检查并执行原始日志记录
    if settings.LOGGING_SWITCHES.get('original_log_enabled'):
        await _log_raw_event(client, log_type, event, **kwargs)

    # 步骤2: 根据各自开关，执行标准的控制台/文件日志记录
    log_switches = settings.LOGGING_SWITCHES
    
    if log_type == LogType.CMD_SENT and log_switches.get('cmd_sent'):
        command, reply_to = kwargs.get('command'), kwargs.get('reply_to')
        log_data = {'指令': command, '回复至': reply_to, '消息ID': event.id}
        format_and_log("CMD_SENT", "指令已发送", log_data)

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
        log_key = "REPLY_RECV" if log_type == LogType.REPLY_RECV else "MSG_RECV"
        format_and_log(log_key, log_title, log_data)
        
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
        
        format_and_log("MSG_EDIT", "消息已编辑", log_data)

    elif log_type == LogType.MSG_DELETE and log_switches.get('log_deletes'):
        chat_title = client.group_name_cache.get(event.chat_id, f"ID:{event.chat_id}")
        log_data = {
            '群组': f"{chat_title} [ID: {event.chat_id}]",
            '被删除消息ID': str(kwargs.get('deleted_ids', []))
        }
        format_and_log("MSG_DELETE", "消息已删除", log_data)

    # 注意：原始日志功能现在独立了，MSG_SENT_SELF 不再在这里产生控制台输出
    # 这是为了避免重复记录自己发送的消息
    # （因为 CMD_SENT 已经记录了所有主动发送的指令）
