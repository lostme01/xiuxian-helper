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
from app.context import get_application
from config import settings

def create_error_reply(command_name: str, reason: str, details: str = None, usage_text: str = None) -> str:
    """
    [新增] 创建一个标准格式的错误回复消息。
    """
    command_prefix = settings.COMMAND_PREFIXES[0]
    
    lines = [f"❌ **指令 [{command_prefix}{command_name}] 执行失败**\n"]
    lines.append(f"**原因**: {reason}")

    if details:
        lines.append(f"**详情**: `{details}`")
    
    if usage_text:
        lines.append("\n" + "-"*15)
        lines.append(f"**用法参考**:\n{usage_text}")
        
    return "\n".join(lines)


def require_args(count: int, usage: str):
    """
    [优化版]
    一个装饰器，用于检查指令处理器接收到的参数列表长度是否足够。
    现在使用 create_error_reply 生成标准错误消息。
    """
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(event, parts: list):
            cmd_name = parts[0]
            if len(parts) < count:
                app = get_application()
                command_info = app.commands.get(cmd_name.lower(), {})
                usage_text = command_info.get('usage', '该指令没有提供详细的用法说明。')
                
                # 使用新的标准化错误回复
                error_msg = create_error_reply(
                    command_name=cmd_name,
                    reason="参数不足",
                    usage_text=usage_text
                )
                await app.client.reply_to_admin(event, error_msg)
                return

            try:
                return await func(event, parts)
            except ValueError:
                # 使用新的标准化错误回复
                error_msg = create_error_reply(
                    command_name=cmd_name,
                    reason="参数解析错误，请检查您的引号是否匹配",
                    usage_text=usage
                )
                await get_application().client.reply_to_admin(event, error_msg)
        return wrapper
    return decorator

async def send_paginated_message(event, text: str, max_length: int = 3500, prefix_message=None):
    """
    [修复版]
    发送长消息，自动分页。
    - text: 要发送的完整文本。
    - prefix_message: (可选) 如果提供，将编辑此消息作为第一页，而不是发送新消息。
    """
    client = get_application().client
    chunks = [text[i:i + max_length] for i in range(0, len(text), max_length)]
    
    if not chunks:
        if prefix_message:
            await prefix_message.edit("（无内容）")
        return

    last_message = None
    
    # 处理第一页
    if prefix_message:
        try:
            await prefix_message.edit(chunks[0])
            last_message = prefix_message
        except Exception: # 如果编辑失败（例如消息太旧），则改为直接回复
            last_message = await client.reply_to_admin(event, chunks[0])
    else:
        last_message = await client.reply_to_admin(event, chunks[0])

    # 处理后续页面
    if last_message:
        for chunk in chunks[1:]:
            new_message = await last_message.reply(chunk)
            client._schedule_message_deletion(new_message, settings.AUTO_DELETE.get('delay_admin_command'), "分页消息")
            last_message = new_message

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
