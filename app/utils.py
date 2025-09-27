# -*- coding: utf-8 -*-
import re
import json
import logging
from datetime import timedelta
from app.logger import format_and_log

def mask_string(text: str, head: int = 4, tail: int = 4) -> str:
    """将字符串脱敏，只显示头尾。例如: 'your_api_key_here' -> 'your...here'"""
    if not isinstance(text, str) or len(text) <= head + tail:
        return "******" # 如果太短或不是字符串，则完全屏蔽
    return f"{text[:head]}...{text[-tail:]}"

def parse_cooldown_time(text: str) -> timedelta | None:
    """
    重构：使用单条正则表达式智能解析包含“时”、“分”、“秒”的任意组合。
    """
    cleaned_text = text.replace('**', '')
    pattern = r'(?:(\d+)\s*小时)?\s*(?:(\d+)\s*分钟)?\s*(?:(\d+)\s*秒)?'
    if match := re.search(pattern, cleaned_text):
        h, m, s = match.groups()
        if any((h, m, s)):
            hours = int(h or 0)
            minutes = int(m or 0)
            seconds = int(s or 0)
            return timedelta(hours=hours, minutes=minutes, seconds=seconds)
    return None

def write_state(file_path: str, content: str):
    """通用状态文件写入函数 (文本)"""
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
    except Exception as e:
        format_and_log("SYSTEM", "状态写入失败", {'文件': file_path, '错误': str(e)}, level=logging.ERROR)

def read_state(file_path: str) -> str | None:
    """通用状态文件读取函数 (文本)"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read().strip()
    except FileNotFoundError:
        return None
    except Exception as e:
        format_and_log("SYSTEM", "状态读取失败", {'文件': file_path, '错误': str(e)}, level=logging.ERROR)
        return None

def write_json_state(file_path: str, data: dict):
    """通用状态文件写入函数 (JSON)"""
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        format_and_log("SYSTEM", "JSON状态写入失败", {'文件': file_path, '错误': str(e)}, level=logging.ERROR)

def read_json_state(file_path: str) -> dict | None:
    """通用状态文件读取函数 (JSON)"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except json.JSONDecodeError:
        format_and_log("SYSTEM", "JSON状态读取失败", {'文件': file_path, '错误': '文件内容损坏'}, level=logging.ERROR)
        return None
    except Exception as e:
        format_and_log("SYSTEM", "JSON状态读取失败", {'文件': file_path, '错误': str(e)}, level=logging.ERROR)
        return None

def parse_inventory_text(reply_text: str) -> dict:
    """从储物袋回复文本中解析物品"""
    inventory = {}
    matches = re.findall(r'-\s*(.*?)\s*x\s*(\d+)', reply_text)
    for match in matches:
        inventory[match[0]] = int(match[1])
    return inventory

# --- Redis 知识库读写函数 ---
def get_qa_answer_from_redis(redis_db, db_name: str, question: str) -> str | None:
    """从 Redis 的哈希表中获取答案"""
    if not redis_db: return None
    try:
        return redis_db.hget(db_name, question)
    except Exception as e:
        format_and_log("SYSTEM", "Redis读取失败", {'错误': str(e)}, level=logging.ERROR)
        return None

def save_qa_answer_to_redis(redis_db, db_name: str, question: str, answer: str):
    """将问答对保存到 Redis 的哈希表中"""
    if not redis_db: return
    try:
        redis_db.hset(db_name, question, answer)
    except Exception as e:
        format_and_log("SYSTEM", "Redis写入失败", {'错误': str(e)}, level=logging.ERROR)
