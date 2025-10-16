# -*- coding: utf-8 -*-
import logging
import re

from telethon import events
from telethon.utils import get_display_name

from app.constants import GAME_EVENTS_CHANNEL
from app.context import get_application
from app.logging_service import LogType, format_and_log
from app import event_parsers
from app.plugins.logic.trade_logic import publish_task
from config import settings


async def _handle_parsing_error(client, event_name: str, raw_text: str):
    """
    统一的解析失败处理器。
    """
    log_data = {'事件': event_name, '原始文本': raw_text}
    format_and_log(LogType.ERROR, "游戏事件解析失败", log_data, level=logging.ERROR)
    await client.send_admin_notification(
        f"⚠️ **警报：游戏事件解析失败**\n\n"
        f"**事件类型**: `{event_name}`\n"
        f"请根据以下原文修正解析逻辑：\n`{raw_text}`"
    )

async def handle_game_report(event):
    app = get_application()
    client = app.client
    
    if not hasattr(event, 'text') or not event.text:
        return

    # [核心修复] 首先，判断这个事件是否由一个正在等待的任务（如闯塔）主动上报的。
    # 我们通过检查 event 对象是否有一个特殊的 `is_awaited_by_task` 标志来判断。
    is_awaited_by_task = getattr(event, 'is_awaited_by_task', False)

    # 检查消息是否@我
    my_display_name = get_display_name(client.me)
    is_mentioning_me = (client.me.username and f"@{client.me.username}" in event.text) or \
                       (my_display_name and my_display_name in event.text)

    # 检查消息是否直接回复我
    original_message = None
    is_reply_to_me = False
    if hasattr(event, 'is_reply') and event.is_reply:
        try:
            reply_to_msg = await event.get_reply_message()
            if reply_to_msg and reply_to_msg.sender_id == client.me.id:
                is_reply_to_me = True
                original_message = reply_to_msg
        except Exception:
            pass
    
    # 只有当事件与我明确相关时，才继续处理
    if not is_awaited_by_task and not is_mentioning_me and not is_reply_to_me:
        return

    text = event.text
    event_payload = None

    try:
        original_message_text = original_message.text if original_message else None
        event_payload = event_parsers.dispatch_and_parse(text, original_message_text=original_message_text)
        
        if not event_payload and is_reply_to_me:
            if original_message_text and ".下架" in original_message_text and "从万宝楼下架" in text:
                event_payload = event_parsers.parse_delist_completed(text)

        if event_payload:
            # 归属判断已经前置，这里可以安全地认为是自己的事件
            event_payload.update({"account_id": str(client.me.id), "raw_text": text})
            format_and_log(LogType.SYSTEM, "事件总线", {'监听到': event_payload.get("event_type", "未知类型"), '归属于': f'...{client.me.id % 10000}'})
            await publish_task(event_payload, channel=GAME_EVENTS_CHANNEL)
        
    except Exception as e:
        await _handle_parsing_error(client, f"调度器异常: {e}", text)


def initialize(app):
    app.client.client.on(events.NewMessage(incoming=True, chats=settings.GAME_GROUP_IDS))(handle_game_report)
    app.client.client.on(events.MessageEdited(incoming=True, chats=settings.GAME_GROUP_IDS))(handle_game_report)
