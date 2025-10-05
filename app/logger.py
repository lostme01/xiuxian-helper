# -*- coding: utf-8 -*-
import logging
import pytz
from collections import namedtuple
from datetime import datetime
from config import settings

# [核心修复] 将 get_display_width 函数直接放在 logger 内部，因为它主要用于日志格式化
# 这样可以彻底断开与 utils.py 的循环依赖
def get_display_width(text: str) -> int:
    width = 0
    for char in text:
        if '\u4e00' <= char <= '\u9fff' or char in '，。？！；：《》【】':
            width += 2
        else:
            width += 1
    return width

# --- 日志分类的“真理之源” ---
LogCategory = namedtuple('LogCategory', ['key', 'switch_name', 'description'])

LOG_CATEGORIES = [
    LogCategory("SYSTEM",       "system_activity",      "系统活动"),
    LogCategory("TASK",         "task_activity",        "任务活动"),
    LogCategory("CMD_SENT",     "cmd_sent",             "指令发送"),
    LogCategory("MSG_RECV",     "msg_recv",             "消息接收"),
    LogCategory("REPLY_RECV",   "reply_recv",           "回复接收"),
    LogCategory("DEBUG",        "debug_log",            "调试日志"),
    LogCategory("MSG_EDIT",     "log_edits",            "消息编辑"),
    LogCategory("MSG_DELETE",   "log_deletes",          "消息删除"),
    # [需求修改] 将描述名称更改为“原始日志”
    LogCategory("MSG_SENT_SELF","original_log_enabled", "原始日志"),
]

LOG_TYPES = {cat.key: cat.switch_name for cat in LOG_CATEGORIES}
LOG_SWITCH_TO_DESC = {cat.switch_name: cat.description for cat in LOG_CATEGORIES}
LOG_DESC_TO_SWITCH = {cat.description: cat.switch_name for cat in LOG_CATEGORIES}


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

def format_and_log(log_type_key: str, title: str, data: dict, level=logging.INFO):
    log_switch_name = LOG_TYPES.get(log_type_key)
    if not (log_switch_name and settings.LOGGING_SWITCHES.get(log_switch_name, True)): 
        return
    
    logger = logging.getLogger()
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
            max_key_width = max(get_display_width(str(key)) for key in filtered_data.keys())
            for key, value in filtered_data.items():
                current_key_width = get_display_width(key)
                padding_count = max_key_width - current_key_width
                padding = " " * padding_count
                value_str = str(value)
                value_lines = value_str.split('\n')
                body_lines.append(f"│ {key}{padding} : {value_lines[0]}")
                indent_width = max_key_width + 4
                indent = " " * indent_width
                for line in value_lines[1:]: 
                    body_lines.append(f"│ {indent}{line}")

    full_log_message = f"\n{top_border}\n{title_line}"
    if body_lines:
        full_log_message += f"\n{middle_border}\n" + "\n".join(body_lines)
    full_log_message += f"\n{bottom_border}"
    
    logger.log(level, full_log_message)
