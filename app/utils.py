# -*- coding: utf-8 -*-
import re
import json
import logging
import os
import shlex
import functools
from datetime import timedelta
from telethon.tl.types import Message
from app.logger import format_and_log
from app.context import get_application # 引入 get_application

def require_args(count: int, usage: str):
    """
    一个装饰器，用于检查指令处理器接收到的参数列表长度是否足够。
    """
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(event, parts: list):
            if len(parts) < count:
                # --- 优化：使用动态传入的 usage 文本 ---
                # 同时也获取命令本身，以便在帮助信息中显示
                app = get_application()
                cmd_name = parts[0]
                command_info = app.commands.get(cmd_name, {})
                usage_text = command_info.get('usage', '该指令没有提供详细的用法说明。')
                
                await event.reply(f"❌ **参数不足！**\n\n{usage_text}", parse_mode='md')
                return
            try:
                return await func(event, parts)
            except ValueError:
                 await event.reply(f"❌ **参数解析错误**\n请检查您的引号是否匹配。\n\n{usage}", parse_mode='md')
        return wrapper
    return decorator

async def send_paginated_message(event, text: str, max_length: int = 4000):
    if len(text) <= max_length:
        await event.reply(text, parse_mode='md')
        return

    await event.reply(f"ℹ️ 查询结果过长，将分多条发送...")
    for i in range(0, len(text), max_length):
        chunk = text[i:i+max_length]
        await event.reply(chunk, parse_mode='md')

def mask_string(text: str, head: int = 4, tail: int = 4) -> str:
    if not isinstance(text, str) or len(text) <= head + tail:
        return "******"
    return f"{text[:head]}...{text[-tail:]}"

def parse_cooldown_time(message: Message) -> timedelta | None:
    try:
        text = message.text
        pattern = r'\**(\d+)\**\s*(小时|时|分钟|分|秒)'
        matches = re.findall(pattern, text)
        if not matches:
            return None
        total_seconds = 0
        for value_str, unit in matches:
            value = int(value_str)
            if unit in ['小时', '时']: total_seconds += value * 3600
            elif unit in ['分钟', '分']: total_seconds += value * 60
            elif unit == '秒': total_seconds += value
        return timedelta(seconds=total_seconds)
    except Exception as e:
        format_and_log("DEBUG", "时间解析", {'状态': '异常', '原始文本': getattr(message, 'text', ''), '错误': str(e)}, level=logging.ERROR)
        return None

def write_state(file_path: str, content: str):
    try:
        with open(file_path, 'w', encoding='utf-8') as f: f.write(content)
    except Exception as e:
        format_and_log("SYSTEM", "状态写入失败", {'文件': file_path, '错误': str(e)}, level=logging.ERROR)

def read_state(file_path: str) -> str | None:
    try:
        with open(file_path, 'r', encoding='utf-8') as f: return f.read().strip()
    except FileNotFoundError: return None
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
            try: os.remove(temp_file_path)
            except OSError: pass

def read_json_state(file_path: str) -> dict | None:
    try:
        with open(file_path, 'r', encoding='utf-8') as f: return json.load(f)
    except FileNotFoundError: return None
    except json.JSONDecodeError: return None
    except Exception as e: return None

def parse_inventory_text(message: Message) -> dict:
    inventory = {}
    matches = re.findall(r'-\s*(.*?)\s*x\s*(\d+)', message.text)
    for match in matches: inventory[match[0]] = int(match[1])
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
        format_and_log("SYSTEM", "Redis写入失败", {'数据库': db_name, '键': question, '错误': str(e)}, level=logging.ERROR)
