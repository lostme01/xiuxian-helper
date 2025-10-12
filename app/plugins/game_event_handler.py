# -*- coding: utf-8 -*-
import logging

from telethon import events
from telethon.utils import get_display_name

from app.constants import GAME_EVENTS_CHANNEL
from app.context import get_application
from app.logging_service import LogType, format_and_log
# [重构] 导入新的解析器模块
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

    # 检查消息是否与本机相关
    my_display_name = get_display_name(client.me)
    is_mentioning_me = (client.me.username and f"@{client.me.username}" in event.text) or \
                       (my_display_name and my_display_name in event.text)

    original_message = None
    is_reply_to_me = False
    if event.is_reply:
        try:
            reply_to_msg = await event.get_reply_message()
            if reply_to_msg and reply_to_msg.sender_id == client.me.id:
                is_reply_to_me = True
                original_message = reply_to_msg
        except Exception:
            pass # 忽略获取被回复消息的错误
    
    # 编辑事件也视为一种回复
    elif hasattr(event, 'message') and event.message.edit_date:
        is_reply_to_me = True

    if not is_reply_to_me and not is_mentioning_me:
        return

    text = event.text
    event_payload = None
    event_name = "未知"

    try:
        # --- [重构] 统一调用解析调度器 ---
        original_message_text = original_message.text if original_message else None
        event_payload = event_parsers.dispatch_and_parse(text, original_message_text=original_message_text)
        
        # --- 特殊事件处理：需要结合原始消息进行“指纹识别” ---
        if not event_payload:
            # “下架”事件的指纹是：回复了.下架指令 + 包含“从万宝楼下架”
            if original_message_text and ".下架" in original_message_text and "从万宝楼下架" in text:
                event_name = "下架成功"
                event_payload = event_parsers.parse_delist_completed(text)
            # “点卯/传功”事件的指纹是：回复了.宗门点卯或.宗门传功 + 包含“点宗门贡献”
            elif original_message_text and (".宗门点卯" in original_message_text or ".宗门传功" in original_message_text) and "点宗门贡献" in text:
                 # 这个事件只是贡献值变化，由其他更通用的解析器处理，此处忽略
                 pass

        if event_payload:
            format_and_log(LogType.SYSTEM, "事件总线", {'监听到': event_payload.get("event_type", "未知类型")})
            event_payload.update({"account_id": str(client.me.id), "raw_text": text})
            await publish_task(event_payload, channel=GAME_EVENTS_CHANNEL)
        
    except Exception as e:
        # 全局捕获，以防调度器本身出错
        await _handle_parsing_error(client, f"调度器异常: {e}", text)


def initialize(app):
    app.client.client.on(events.NewMessage(incoming=True, chats=settings.GAME_GROUP_IDS))(handle_game_report)
    app.client.client.on(events.MessageEdited(incoming=True, chats=settings.GAME_GROUP_IDS))(handle_game_report)
