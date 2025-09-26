# -*- coding: utf-8 -*-
import logging
import pytz
from datetime import datetime
from config import settings
LOG_TYPES = {"SYSTEM": "system_activity","TASK": "task_activity","CMD_SENT": "cmd_sent","MSG_RECV": "msg_recv","REPLY_RECV": "reply_recv","DEBUG": "debug_log","MSG_EDIT": "log_edits","MSG_DELETE": "log_deletes",}
PREFIXES = {LOG_TYPES["SYSTEM"]: "【系统活动】",LOG_TYPES["TASK"]: "【任务活动】",LOG_TYPES["CMD_SENT"]: "【指令发送】",LOG_TYPES["MSG_RECV"]: "【收到消息】",LOG_TYPES["REPLY_RECV"]: "【收到回复】",LOG_TYPES["DEBUG"]: "【调试日志】",LOG_TYPES["MSG_EDIT"]: "【消息编辑】",LOG_TYPES["MSG_DELETE"]: "【消息删除】",}
LINE_WIDTH = 50
def get_display_width(text: str) -> int:
    width = 0
    for char in text:
        if '\u4e00' <= char <= '\u9fff' or char in '，。？！；：《》【】': width += 2
        else: width += 1
    return width
def format_and_log(log_type_key: str, title: str, data: dict, level=logging.INFO):
    log_type = LOG_TYPES.get(log_type_key)
    if not (log_type and settings.LOGGING_SWITCHES.get(log_type, True)): return
    top_border = "┌" + "─" * LINE_WIDTH
    middle_border = "├" + "─" * LINE_WIDTH
    bottom_border = "└" + "─" * LINE_WIDTH
    title_line = f"│ [ {title} ]"
    body_lines = []
    if data:
        max_key_width = max(get_display_width(str(key)) for key in data.keys()) if data else 0
        for key, value in data.items():
            current_key_width = get_display_width(key)
            padding_count = max_key_width - current_key_width
            padding = " " * padding_count
            value_str = str(value)
            value_lines = value_str.split('\n')
            body_lines.append(f"│ {key}{padding} : {value_lines[0]}")
            indent_width = max_key_width + 4
            indent = " " * indent_width
            for line in value_lines[1:]: body_lines.append(f"│ {indent}{line}")
    full_log_message = f"\n{top_border}\n{title_line}"
    if body_lines:
        full_log_message += f"\n{middle_border}\n" + "\n".join(body_lines)
    full_log_message += f"\n{bottom_border}"
    logging.log(level, full_log_message)
