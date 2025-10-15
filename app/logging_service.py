# -*- coding: utf-8 -*-
import logging
import pytz
from collections import namedtuple
from datetime import datetime
from enum import Enum

from telethon.utils import get_display_name
from telethon.tl.types import Channel, Message, MessageService
from telethon import events

from config import settings

# --- Log Type Definition ---
class LogType(Enum):
    CMD_SENT = "cmd_sent"
    MSG_RECV = "msg_recv"
    REPLY_RECV = "reply_recv"
    MSG_EDIT = "log_edits"
    MSG_DELETE = "log_deletes"
    MSG_SENT_SELF = "msg_sent_self" # Not in settings, but useful
    SYSTEM = "system_activity"
    TASK = "task_activity"
    DEBUG = "debug_log"
    WARNING = "warning" # Generic warning
    ERROR = "error"     # Generic error


# --- Formatter ---
class TimezoneFormatter(logging.Formatter):
    def __init__(self, fmt, datefmt=None, tz_name='UTC'):
        super().__init__(fmt, datefmt)
        self.tz = pytz.timezone(tz_name)

    def formatTime(self, record, datefmt=None):
        dt = datetime.fromtimestamp(record.created, self.tz)
        if datefmt:
            return dt.strftime(datefmt)
        return dt.isoformat()


LINE_WIDTH = 50

def get_display_width(text: str) -> int:
    width = 0
    for char in text:
        if '\u4e00' <= char <= '\u9fff' or char in '，。？！；：《》【】':
            width += 2
        else:
            width += 1
    return width

def format_and_log(log_type: LogType, title: str, data: dict, level=logging.INFO):
    """
    统一的日志格式化与输出函数。
    它会检查配置中的开关，决定是否记录该类型的日志。
    """
    log_switch_name = log_type.value
    if not settings.LOGGING_SWITCHES.get(log_switch_name, True):
        return

    logger = logging.getLogger("app")
    top_border = "┌" + "─" * LINE_WIDTH
    middle_border = "├" + "─" * LINE_WIDTH
    bottom_border = "└" + "─" * LINE_WIDTH
    title_line = f"│ [ {title} ]"
    body_lines = []
    if data:
        filtered_data = {k: v for k, v in data.items() if v is not None}
        if not filtered_data:
            body_lines = []
        else:
            max_key_width = max(get_display_width(str(key)) for key in filtered_data.keys()) if filtered_data else 0
            for key, value in filtered_data.items():
                current_key_width = get_display_width(key)
                padding = " " * (max_key_width - current_key_width)
                value_str = str(value)
                value_lines = value_str.split('\n')
                body_lines.append(f"│ {key}{padding} : {value_lines[0]}")
                indent = " " * (max_key_width + 4)
                for line in value_lines[1:]:
                    body_lines.append(f"│ {indent}{line}")

    full_log_message = f"\n{top_border}\n{title_line}"
    if body_lines:
        full_log_message += f"\n{middle_border}\n" + "\n".join(body_lines)
    full_log_message += f"\n{bottom_border}"

    logger.log(level, full_log_message)


async def log_telegram_event(client, log_type: LogType, event, **kwargs):
    """
    [日志增强] 重构日志记录器，增加回复和编辑的上下文ID。
    """
    # --- 原始日志 (raw_logger) ---
    raw_logger = logging.getLogger('raw_messages')
    if not settings.LOGGING_SWITCHES.get('original_log_enabled'):
        return

    log_lines = []
    event_time = getattr(event, 'date', datetime.now(pytz.timezone(settings.TZ)))
    log_lines.append(f"时间: {event_time.astimezone(pytz.timezone(settings.TZ)).strftime('%Y-%m-%d %H:%M:%S CST')}")

    # 1. 确定事件类型和标题
    title = f"事件类型: {log_type.name}"
    if log_type == LogType.MSG_DELETE:
        title = "消息删除"
    elif isinstance(event, events.MessageEdited.Event):
        title = f"消息编辑 (ID: {event.id})" # 直接在标题中标注ID
    elif isinstance(event, events.NewMessage.Event):
        title = f"新消息 (ID: {event.id})" # 为新消息也加上ID
    
    log_lines.append(title)
    
    # 2. 获取群组和话题信息
    chat_title = client.group_name_cache.get(event.chat_id)
    if not chat_title:
        try:
            entity = await client.client.get_entity(event.chat_id)
            chat_title = getattr(entity, 'title', f"ID:{event.chat_id}")
            client.group_name_cache[int(event.chat_id)] = chat_title
        except Exception:
            chat_title = f"ID:{event.chat_id}"
    
    source_line = f"来源: {chat_title} ({event.chat_id})"
    
    topic_title = ""
    try:
        if hasattr(event, 'message') and hasattr(event.message, 'reply_to') and event.message.reply_to and hasattr(event.message.reply_to, 'forum_topic') and event.message.reply_to.forum_topic:
            reply_to_msg = await event.get_reply_message()
            if hasattr(reply_to_msg, 'reply_to') and reply_to_msg.reply_to and hasattr(reply_to_msg.reply_to, 'topic_title'):
                 topic_title = reply_to_msg.reply_to.topic_title
    except Exception:
        pass 
        
    if topic_title:
        source_line += f" (话题: {topic_title})"
        
    log_lines.append(source_line)

    # 3. 处理删除事件
    if log_type == LogType.MSG_DELETE:
        log_lines.append(f"被删除消息ID: {kwargs.get('deleted_ids', [])}")
    
    # 4. 处理新消息和编辑事件
    else:
        sender = None
        if hasattr(event, 'get_sender'):
             sender = await event.get_sender()
        if sender is None and hasattr(event, 'sender_id') and event.sender_id:
            try: 
                sender = await client.client.get_entity(event.sender_id)
            except Exception:
                sender = None
        
        sender_name = get_display_name(sender) if sender else "未知来源"
        if isinstance(sender, (MessageService, Channel)) and hasattr(sender, 'title'):
             sender_name = f"频道/群组事件 ({sender.title})"

        log_lines.append(f"用户: {sender_name} ({getattr(event, 'sender_id', 'N/A')})")
        
        # [新增] 标记回复上下文
        if hasattr(event, 'is_reply') and event.is_reply and hasattr(event, 'reply_to_msg_id'):
            log_lines.append(f"回复至消息ID: {event.reply_to_msg_id}")
            
        content = kwargs.get('command', getattr(event, 'text', '(无文本内容)'))
        log_lines.append(f"内容:\n{content}")

    raw_logger.info("\n".join(log_lines) + "\n" + "─" * 50)
    
    # --- 格式化日志 (format_and_log) ---
    log_switch_name = log_type.value
    if not settings.LOGGING_SWITCHES.get(log_switch_name, True):
        return

    log_data = {}
    log_data['时间'] = event_time.astimezone(pytz.timezone(settings.TZ)).strftime('%Y-%m-%d %H:%M:%S')
    log_data['来源群组'] = chat_title

    if log_type == LogType.MSG_DELETE:
        log_data['被删除消息ID'] = str(kwargs.get('deleted_ids', []))
        format_and_log(log_type, "消息已删除", log_data)
        return
    
    sender_display = f"{sender_name} ({getattr(event, 'sender_id', 'N/A')})"
    log_data['发送者'] = sender_display
    log_data['消息ID'] = event.id
    
    if hasattr(event, 'is_reply') and event.is_reply and hasattr(event, 'reply_to_msg_id'):
        log_data['回复至'] = event.reply_to_msg_id

    content = kwargs.get('command', getattr(event, 'text', '(无文本内容)'))

    if log_type == LogType.CMD_SENT:
        log_data['指令'] = content
        format_and_log(log_type, "指令已发送", log_data)
    elif log_type in [LogType.MSG_RECV, LogType.REPLY_RECV, LogType.MSG_SENT_SELF]:
        log_data['内容'] = content
        title = "收到回复" if log_type == LogType.REPLY_RECV else "收到消息"
        format_and_log(log_type, title, log_data)
    elif log_type == LogType.MSG_EDIT:
        log_data['新内容'] = content
        format_and_log(log_type, "消息已编辑", log_data)
