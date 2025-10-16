# -*- coding: utf-8 -*-
import logging

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

    # [核心修复] 检查事件是否由正在等待的特定任务触发。
    # 这是最精确的归属判断，能确保只有发起者才能处理其等待的事件。
    is_awaited_by_task = False
    if isinstance(event, events.MessageEdited.Event):
        for waiter in client.pending_edits.values():
            # 检查这个编辑事件是否是某个等待器正在寻找的“最终候选”
            if re.search(waiter['final_pattern'], event.text, re.DOTALL):
                 is_awaited_by_task = True
                 break
    elif isinstance(event, events.NewMessage.Event):
         for waiter in client.pending_edits.values():
            # 检查这个新消息事件是否是某个等待器正在寻找的“初始候选”
            if event.sender_id in waiter['from_user_ids'] and re.search(waiter['initial_pattern'], event.text, re.DOTALL):
                is_awaited_by_task = True
                break

    # 检查消息是否@我
    my_display_name = get_display_name(client.me)
    is_mentioning_me = (client.me.username and f"@{client.me.username}" in event.text) or \
                       (my_display_name and my_display_name in event.text)

    # 检查消息是否直接回复我
    original_message = None
    is_reply_to_me = False
    if event.is_reply:
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
