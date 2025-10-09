# -*- coding: utf-8 -*-
import asyncio
import functools
import json
import logging
import re
from datetime import timedelta

from telethon.tl.types import Message

from app.context import get_application
from app.logging_service import LogType, format_and_log
from config import settings


def get_display_width(text: str) -> int:
    """
    计算字符串在终端中的显示宽度。
    一个中文字符宽度为2，一个英文字符宽度为1。
    """
    width = 0
    for char in text:
        if '\u4e00' <= char <= '\u9fff' or char in '，。？！；：《》【】':
            width += 2
        else:
            width += 1
    return width

def create_error_reply(command_name: str, reason: str, details: str = None, usage_text: str = None) -> str:
    command_prefix = settings.COMMAND_PREFIXES[0]
    
    lines = [f"❌ **指令 [{command_prefix}{command_name}] 执行失败**\n"]
    lines.append(f"**原因**: {reason}")

    if details:
        lines.append(f"**详情**: `{details}`")
    
    if usage_text:
        lines.append("\n" + "-"*15)
        lines.append(f"**用法参考**:\n{usage_text}")
        
    return "\n".join(lines)

def parse_item_and_quantity(parts: list, default_quantity: int = 1) -> tuple[str | None, int | None, str | None]:
    """
    一个通用的基础函数，用于从指令参数中解析物品名称和数量。
    """
    if len(parts) < 2:
        return None, None, "参数不足"

    item_name = ""
    quantity = default_quantity

    try:
        if len(parts) > 2 and parts[-1].isdigit():
            quantity = int(parts[-1])
            if quantity <= 0:
                raise ValueError("数量必须为正整数")
            item_name = " ".join(parts[1:-1])
        else:
            item_name = " ".join(parts[1:])
        
        if not item_name:
            return None, None, "物品名称不能为空"
            
        return item_name.strip(), quantity, None
    except ValueError as e:
        return None, None, str(e) or "数量参数无效"


def require_args(count: int, usage: str):
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(event, parts: list):
            cmd_name = parts[0]
            if len(parts) < count:
                app = get_application()
                command_info = app.commands.get(cmd_name.lower(), {})
                usage_text = command_info.get('usage', '该指令没有提供详细的用法说明。')
                
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
                error_msg = create_error_reply(
                    command_name=cmd_name,
                    reason="参数解析错误，请检查您的引号是否匹配",
                    usage_text=usage
                )
                await get_application().client.reply_to_admin(event, error_msg)
        return wrapper
    return decorator

def resilient_task(retry_delay_minutes: int = 15):
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            from app.telegram_client import CommandTimeoutError
            is_forced = kwargs.get('force_run', False)
            task_name = func.__name__
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                if is_forced:
                    raise e
                
                log_level = logging.WARNING if isinstance(e, CommandTimeoutError) else logging.ERROR
                format_and_log(LogType.TASK, f"后台任务异常: {task_name}", {'错误': str(e)}, level=log_level)

        return wrapper
    return decorator

async def send_paginated_message(event, text: str, max_length: int = 3500, prefix_message=None):
    client = get_application().client
    chunks = [text[i:i + max_length] for i in range(0, len(text), max_length)]
    
    if not chunks:
        if prefix_message:
            await prefix_message.edit("（无内容）")
        return

    last_message = None
    
    if prefix_message:
        try:
            await prefix_message.edit(chunks[0])
            last_message = prefix_message
        except Exception:
            last_message = await client.reply_to_admin(event, chunks[0])
    else:
        last_message = await client.reply_to_admin(event, chunks[0])

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
        format_and_log(LogType.DEBUG, "时间解析", {'状态': '异常', '原始文本': getattr(message, 'text', ''), '错误': str(e)}, level=logging.ERROR)
        return None

def parse_inventory_text(message: Message) -> dict:
    inventory = {}
    matches = re.findall(r'-\s*(.*?)\s*x\s*(\d+)', message.text)
    for match in matches: inventory[match[0].strip()] = int(match[1])
    return inventory

async def get_qa_answer_from_redis(redis_db, db_name: str, question: str) -> str | None:
    if not redis_db: return None
    try: 
        return await redis_db.hget(db_name, question)
    except Exception: 
        return None

async def save_qa_answer_to_redis(redis_db, db_name: str, question: str, answer: str):
    if not redis_db: return
    try:
        await redis_db.hset(db_name, question, answer)
    except Exception as e:
        format_and_log(LogType.ERROR, "Redis写入失败", {'数据库': db_name, '键': question, '错误': str(e)}, level=logging.ERROR)
