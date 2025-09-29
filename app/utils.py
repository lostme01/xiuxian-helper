# -*- coding: utf-8 -*-
import re
import json
import logging
import os
from datetime import timedelta
from app.logger import format_and_log

LOG_TYPE_MAP_ZH_TO_EN = {
    "系统": "system_activity", "任务": "task_activity",
    "指令": "cmd_sent", "消息": "msg_recv", "回复": "reply_recv",
    "原始": "original_log_enabled", "调试": "debug_log",
    "编辑": "log_edits", "删除": "log_deletes"
}

def mask_string(text: str, head: int = 4, tail: int = 4) -> str:
    if not isinstance(text, str) or len(text) <= head + tail:
        return "******"
    return f"{text[:head]}...{text[-tail:]}"

def parse_cooldown_time(text: str) -> timedelta | None:
    try:
        pattern = r'\**(\d+)\**\s*(小时|时|分钟|分|秒)'
        matches = re.findall(pattern, text)
        if not matches:
            format_and_log("DEBUG", "时间解析", {'状态': '失败', '原始文本': text, '原因': '正则未匹配到任何时间单位'})
            return None
        total_seconds = 0
        for value_str, unit in matches:
            value = int(value_str)
            if unit in ['小时', '时']:
                total_seconds += value * 3600
            elif unit in ['分钟', '分']:
                total_seconds += value * 60
            elif unit == '秒':
                total_seconds += value
        result = timedelta(seconds=total_seconds)
        format_and_log("DEBUG", "时间解析", {'状态': '成功', '原始文本': text, '解析结果': str(result)})
        return result
    except Exception as e:
        format_and_log("DEBUG", "时间解析", {'状态': '异常', '原始文本': text, '错误': str(e)}, level=logging.ERROR)
        return None

def write_state(file_path: str, content: str):
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
    except Exception as e:
        format_and_log("SYSTEM", "状态写入失败", {'文件': file_path, '错误': str(e)}, level=logging.ERROR)

def read_state(file_path: str) -> str | None:
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read().strip()
    except FileNotFoundError:
        return None
    except Exception as e:
        format_and_log("SYSTEM", "状态读取失败", {'文件': file_path, '错误': str(e)}, level=logging.ERROR)
        return None

def write_json_state(file_path: str, data: dict):
    temp_file_path = file_path + ".tmp"
    try:
        with open(temp_file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(temp_file_path, file_path)
    except Exception as e:
        format_and_log("SYSTEM", "JSON状态写入失败", {'文件': file_path, '错误': str(e)}, level=logging.ERROR)
        if os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
            except OSError: pass

def read_json_state(file_path: str) -> dict | None:
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError: return None
    except json.JSONDecodeError: return None
    except Exception as e: return None

def parse_inventory_text(reply_text: str) -> dict:
    inventory = {}
    matches = re.findall(r'-\s*(.*?)\s*x\s*(\d+)', reply_text)
    for match in matches:
        inventory[match[0]] = int(match[1])
    return inventory

def get_qa_answer_from_redis(redis_db, db_name: str, question: str) -> str | None:
    if not redis_db: return None
    try: return redis_db.hget(db_name, question)
    except Exception as e: return None

def save_qa_answer_to_redis(redis_db, db_name: str, question: str, answer: str):
    if not redis_db: return
    try:
        redis_db.hset(db_name, question, answer)
    except Exception as e:
        # --- 核心修复：将 pass 修改为记录错误日志 ---
        format_and_log("SYSTEM", "Redis写入失败", {
            '数据库': db_name,
            '键': question,
            '错误': str(e)
        }, level=logging.ERROR)

