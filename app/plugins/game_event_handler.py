# -*- coding: utf-8 -*-
import json
import logging
import re

from telethon import events
from telethon.utils import get_display_name

from app import game_adaptor
from app.constants import GAME_EVENTS_CHANNEL
from app.context import get_application
from app.logging_service import LogType, format_and_log
from app.plugins.logic.trade_logic import publish_task
from config import settings


async def _handle_parsing_error(client, event_name: str, error: Exception, raw_text: str):
    """
    统一的解析失败处理器。
    """
    log_data = {'事件': event_name, '错误': str(error), '原始文本': raw_text}
    format_and_log(LogType.ERROR, "游戏事件解析失败", log_data, level=logging.ERROR)
    await client.send_admin_notification(
        f"⚠️ **严重警报：游戏事件解析失败**\n\n"
        f"**事件类型**: `{event_name}`\n"
        f"**失败原因**: `{str(error)}`\n\n"
        f"请根据以下原文修正解析逻辑：\n`{raw_text}`"
    )

async def handle_game_report(event):
    app = get_application()
    client = app.client
    my_id = str(client.me.id)
    my_username = client.me.username if client.me else None
    
    if not hasattr(event, 'text') or not event.text:
        return

    my_display_name = get_display_name(client.me)
    is_mentioning_me = (my_username and f"@{my_username}" in event.text) or \
                       (my_display_name and my_display_name in event.text)

    is_reply_to_me = False
    original_message = None

    if event.is_reply:
        try:
            reply_to_msg = await event.get_reply_message()
            if reply_to_msg and reply_to_msg.sender_id == client.me.id:
                is_reply_to_me = True
                original_message = reply_to_msg
        except Exception:
            pass
    elif hasattr(event, 'message') and event.message.edit_date:
        is_reply_to_me = True

    if not is_reply_to_me and not is_mentioning_me:
        return

    text = event.text
    event_payload = None
    event_name_for_error = "未知"

    try:
        # [核心修复] 采用“指令-回复”匹配模式来精确识别下架事件
        if original_message and ".下架" in original_message.text and "从万宝楼下架" in text:
            event_name_for_error = "下架成功"
            match = re.search(r"你已成功将 \*\*【(.+?)】\*\*x([\d,]+)", text)
            if match:
                item_name = match.group(1)
                quantity = int(match.group(2).replace(',', ''))
                event_payload = {
                    "event_type": "DELIST_COMPLETED",
                    "gained_items": {item_name: quantity}
                }
        
        elif "【万宝楼快报】" in text:
            event_name_for_error = "万宝楼快报"
            gained_items, sold_items = {}, {}
            gained_match = re.search(r"你获得了：\s*(.*)", text, re.DOTALL)
            if gained_match:
                for item, quantity in re.findall(r"【(.+?)】x([\d,]+)", gained_match.group(1)):
                    gained_items[item] = int(quantity.replace(',', ''))
            sold_match = re.search(r"你成功出售了【(.+?)】x([\d,]+)", text)
            if sold_match:
                sold_items[sold_match.group(1)] = int(sold_match.group(2).replace(',', ''))
            if gained_items or sold_items:
                event_payload = {"event_type": "TRADE_COMPLETED", "gained": gained_items, "sold": sold_items}

        elif "你向宗门捐献了" in text:
            event_name_for_error = "宗门捐献"
            consumed_match = re.search(r"捐献了 \*\*【(.+?)】\*\*x([\d,]+)", text)
            contrib_match = re.search(r"获得了 \*\*([\d,]+)\*\* 点宗门贡献", text)
            if consumed_match and contrib_match:
                event_payload = {
                    "event_type": "DONATION_COMPLETED",
                    "consumed_item": {consumed_match.group(1): int(consumed_match.group(2).replace(',', ''))},
                    "gained_contribution": int(contrib_match.group(1).replace(',', ''))
                }

        elif "**兑换成功！**" in text:
            event_name_for_error = "宗门兑换"
            gain_match = re.search(r"获得了【(.+?)】x([\d,]+)", text)
            cost_match = re.search(r"消耗了 \*\*([\d,]+)\*\* 点贡献", text)
            if gain_match and cost_match:
                event_payload = {
                    "event_type": "EXCHANGE_COMPLETED",
                    "gained_item": {gain_match.group(1): int(gain_match.group(2).replace(',', ''))},
                    "consumed_contribution": int(cost_match.group(1).replace(',', ''))
                }

        elif original_message and ("获得了" in text and "点宗门贡献" in text) and \
                (game_adaptor.sect_check_in() in original_message.text or game_adaptor.sect_contribute_skill() in original_message.text):
            event_name_for_error = "点卯或传功"
            contrib_match = re.search(r"获得了 \*\*([\d,]+)\*\* 点宗门贡献", text)
            if contrib_match:
                event_payload = {"event_type": "CONTRIBUTION_GAINED",
                                 "gained_contribution": int(contrib_match.group(1).replace(',', ''))}

        elif "【试炼古塔 - 战报】" in text and "总收获" in text:
            event_name_for_error = "闯塔战报"
            gained_items = {item: int(q.replace(',', '')) for item, q in re.findall(r"获得了【(.+?)】x([\d,]+)", text)}
            if gained_items:
                event_payload = {"event_type": "TOWER_CHALLENGE_COMPLETED", "gained_items": gained_items}

        elif "炼制结束！" in text and "最终获得" in text:
            event_name_for_error = "炼制结束"
            gained_items = {item: int(q.replace(',', '')) for item, q in
                            re.findall(r"最终获得【(.+?)】x\*\*([\d,]+)\*\*", text)}
            if gained_items and original_message:
                command_parts = original_message.text.split()
                crafted_quantity = 1
                if len(command_parts) > 2 and command_parts[-1].isdigit():
                    crafted_quantity = int(command_parts[-1])
                event_payload = {
                    "event_type": "CRAFTING_COMPLETED",
                    "crafted_item": {"name": next(iter(gained_items)), "quantity": crafted_quantity},
                    "gained_items": gained_items
                }

        elif "一键采药完成！" in text:
            event_name_for_error = "一键采药"
            gained_items = {item: int(q.replace(',', '')) for item, q in re.findall(r"【(.+?)】x([\d,]+)", text)}
            if gained_items:
                event_payload = {"event_type": "HARVEST_COMPLETED", "gained_items": gained_items}

        elif "成功领悟了" in text:
            event_name_for_error = "学习成功"
            consumed_match = re.search(r"消耗了【(.+?)】", text)
            if consumed_match:
                event_payload = {"event_type": "LEARNING_COMPLETED", "consumed_item": {consumed_match.group(1): 1}}

        elif "你已成功在" in text and "播下" in text:
            event_name_for_error = "播种成功"
            consumed_match = re.search(r"播下【(.+?)】", text)
            if consumed_match:
                event_payload = {"event_type": "SOWING_COMPLETED", "consumed_item": {consumed_match.group(1): 1}}

        if event_payload:
            format_and_log(LogType.SYSTEM, "事件总线", {'监听到': event_name_for_error})
            event_payload.update({"account_id": my_id, "raw_text": text})
            await publish_task(event_payload, channel=GAME_EVENTS_CHANNEL)

    except Exception as e:
        await _handle_parsing_error(client, event_name_for_error, e, text)


def initialize(app):
    app.client.client.on(events.NewMessage(incoming=True, chats=settings.GAME_GROUP_IDS))(handle_game_report)
    app.client.client.on(events.MessageEdited(incoming=True, chats=settings.GAME_GROUP_IDS))(handle_game_report)
