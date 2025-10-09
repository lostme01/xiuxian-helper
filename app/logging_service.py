# -*- coding: utf-8 -*-
import logging
import pytz
from collections import namedtuple
from datetime import datetime
from enum import Enum

from telethon.utils import get_display_name

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
    # Check if this log type is enabled in settings
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
    处理来自 Telegram 的事件，并将其格式化后记录。
    """
    # Raw logging (optional)
    raw_logger = logging.getLogger('raw_messages')
    if settings.LOGGING_SWITCHES.get('original_log_enabled'):
        chat_title = client.group_name_cache.get(event.chat_id, f"ID:{event.chat_id}")
        log_lines = [f"群组: {chat_title} ({event.chat_id})"]
        if log_type == LogType.MSG_DELETE:
            log_lines.insert(0, "[消息删除]")
            log_lines.append(f"被删除消息ID: {kwargs.get('deleted_ids', [])}")
        else:
            sender = await event.get_sender()
            sender_name = get_display_name(sender) if sender else "未知"
            log_lines.append(f"发送者: {sender_name} (ID: {event.sender_id})")
            if log_type == LogType.CMD_SENT:
                log_lines.insert(0, "[指令发送]")
                log_lines.append(f"内容: {kwargs.get('command')}")
            else:
                log_lines.insert(0, f"[{log_type.name}]")
                log_lines.append(f"内容:\n{event.text}")
        raw_logger.info("\n".join(log_lines))

    # Formatted logging
    log_data = {}
    chat_info = client.group_name_cache.get(event.chat_id, f"ID:{event.chat_id}")
    event_time = getattr(event, 'date', datetime.now(pytz.timezone(settings.TZ)))
    log_data['时间'] = event_time.astimezone(pytz.timezone(settings.TZ)).strftime('%Y-%m-%d %H:%M:%S')
    log_data['来源群组'] = chat_info

    if log_type == LogType.MSG_DELETE:
        log_data['被删除消息ID'] = str(kwargs.get('deleted_ids', []))
        format_and_log(log_type, "消息已删除", log_data)
        return

    sender = await event.get_sender()
    log_data['发送者'] = f"{get_display_name(sender)} (ID: {event.sender_id})" if sender else "未知"
    log_data['消息ID'] = event.id
    content = event.text or "(无文本内容)"

    if log_type == LogType.CMD_SENT:
        log_data['指令'] = kwargs.get('command')
        log_data['回复至'] = kwargs.get('reply_to')
        format_and_log(log_type, "指令已发送", log_data)
    elif log_type in [LogType.MSG_RECV, LogType.REPLY_RECV, LogType.MSG_SENT_SELF]:
        log_data['内容'] = content
        title = "收到回复" if log_type == LogType.REPLY_RECV else "收到消息"
        format_and_log(log_type, title, log_data)
    elif log_type == LogType.MSG_EDIT:
        log_data['新内容'] = content
        format_and_log(log_type, "消息已编辑", log_data)
