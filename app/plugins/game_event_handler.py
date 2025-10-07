# -*- coding: utf-8 -*-
import re
import json
import logging
from telethon import events
from app.context import get_application
from app.logger import format_and_log
from app.plugins.logic.trade_logic import publish_task
from config import settings
from app import game_adaptor

GAME_EVENTS_CHANNEL = "tg_helper:game_events"

async def _handle_parsing_error(client, event_name: str, error: Exception, raw_text: str):
    """
    [NEW] 统一的解析失败处理器。
    负责记录详细日志并向管理员发送警报。
    """
    log_data = {
        '事件': event_name,
        '错误': str(error),
        '原始文本': raw_text
    }
    format_and_log("ERROR", "游戏事件解析失败", log_data, level=logging.ERROR)
    
    await client.send_admin_notification(
        f"⚠️ **严重警报：游戏事件解析失败**\n\n"
        f"**事件类型**: `{event_name}`\n"
        f"**失败原因**: `{str(error)}`\n\n"
        f"这很可能是因为游戏机器人更新了消息格式。请根据以下原文修正解析逻辑：\n"
        f"-----------------\n"
        f"`{raw_text}`"
    )

async def handle_game_report(event):
    app = get_application()
    client = app.client
    my_id = str(client.me.id)
    my_username = client.me.username if client.me else None
    
    if not (my_username and event.text):
        return

    is_reply_to_me = False
    original_message = None
    
    if event.is_reply:
        reply_to_msg = await event.get_reply_message()
        if reply_to_msg and reply_to_msg.sender_id == client.me.id:
            is_reply_to_me = True
            original_message = reply_to_msg
            
    elif hasattr(event, 'message') and event.message.edit_date:
        for sent_msg_id, wait_obj in app.client.pending_waits.items():
            if wait_obj.get('initial_reply_id') == event.message.id:
                is_reply_to_me = True
                try:
                    original_message = await client.client.get_messages(event.chat_id, ids=sent_msg_id)
                except Exception:
                    pass
                break

    is_mentioning_me = f"@{my_username}" in event.text
    
    if not is_reply_to_me and not is_mentioning_me:
        return
        
    text = event.text
    event_payload = None
    event_name_for_error = "未知"

    # --- [REFACTOR] 为每个解析块添加安全网 ---

    # 1. 万宝楼快报
    if "【万宝楼快报】" in text:
        event_name_for_error = "万宝楼快报"
        try:
            gained_items = {}
            sold_items = {}
            
            gain_match = re.search(r"你获得了：(.*?)(?:你成功出售了|$)", text, re.DOTALL)
            if gain_match:
                gained_items_str = gain_match.group(1).strip().rstrip('。')
                for item, quantity_str in re.findall(r"【(.+?)】x([\d,]+)", gained_items_str):
                    gained_items[item] = int(quantity_str.replace(',', ''))
            
            sold_match = re.search(r"你成功出售了【(.+?)】x([\d,]+)", text)
            if sold_match:
                item, quantity_str = sold_match.groups()
                sold_items[item] = int(quantity_str.replace(',', ''))
            
            if gained_items or sold_items:
                event_payload = {"event_type": "TRADE_COMPLETED", "gained": gained_items, "sold": sold_items}
                format_and_log("SYSTEM", "事件总线", {'监听到': event_name_for_error})
        except Exception as e:
            await _handle_parsing_error(client, event_name_for_error, e, text)

    # 2. 宗门捐献
    elif "你向宗门捐献了" in text:
        event_name_for_error = "宗门捐献"
        try:
            consumed_match = re.search(r"捐献了 \*\*【(.+?)】\*\*x([\d,]+)", text)
            contrib_match = re.search(r"获得了 \*\*([\d,]+)\*\* 点宗门贡献", text)
            if consumed_match and contrib_match:
                item, quantity_str = consumed_match.groups()
                contrib_str = contrib_match.group(1)
                event_payload = {
                    "event_type": "DONATION_COMPLETED",
                    "consumed_item": {item: int(quantity_str.replace(',', ''))},
                    "gained_contribution": int(contrib_str.replace(',', ''))
                }
                format_and_log("SYSTEM", "事件总线", {'监听到': event_name_for_error})
        except Exception as e:
            await _handle_parsing_error(client, event_name_for_error, e, text)

    # 3. 宗门兑换
    elif "**兑换成功！**" in text:
        event_name_for_error = "宗门兑换"
        try:
            gain_match = re.search(r"获得了【(.+?)】x([\d,]+)", text)
            cost_match = re.search(r"消耗了 \*\*([\d,]+)\*\* 点贡献", text)
            if gain_match and cost_match:
                item, quantity_str = gain_match.groups()
                cost_str = cost_match.group(1)
                event_payload = {
                    "event_type": "EXCHANGE_COMPLETED",
                    "gained_item": {item: int(quantity_str.replace(',', ''))},
                    "consumed_contribution": int(cost_str.replace(',', ''))
                }
                format_and_log("SYSTEM", "事件总线", {'监听到': event_name_for_error})
        except Exception as e:
            await _handle_parsing_error(client, event_name_for_error, e, text)
            
    # 4. 点卯/传功
    elif "获得了" in text and "点宗门贡献" in text and original_message and (game_adaptor.sect_check_in() in original_message.text or game_adaptor.sect_contribute_skill() in original_message.text):
        event_name_for_error = "点卯或传功"
        try:
            contrib_match = re.search(r"获得了 \*\*([\d,]+)\*\* 点宗门贡献", text)
            if contrib_match:
                contrib_str = contrib_match.group(1)
                event_payload = { "event_type": "CONTRIBUTION_GAINED", "gained_contribution": int(contrib_str.replace(',', '')) }
                format_and_log("SYSTEM", "事件总线", {'监听到': event_name_for_error})
        except Exception as e:
            await _handle_parsing_error(client, event_name_for_error, e, text)

    # 5. 闯塔战报
    elif "【试炼古塔 - 战报】" in text and "总收获" in text:
        event_name_for_error = "闯塔战报"
        try:
            gained_items = {}
            for item, quantity_str in re.findall(r"获得了【(.+?)】x([\d,]+)", text):
                gained_items[item] = int(quantity_str.replace(',', ''))
            
            if gained_items:
                event_payload = { "event_type": "TOWER_CHALLENGE_COMPLETED", "gained_items": gained_items }
                format_and_log("SYSTEM", "事件总线", {'监听到': event_name_for_error})
        except Exception as e:
            await _handle_parsing_error(client, event_name_for_error, e, text)

    # 6. 炼制结束
    elif "炼制结束！" in text and "最终获得" in text:
        event_name_for_error = "炼制结束"
        try:
            gained_items = {}
            for item, quantity_str in re.findall(r"最终获得【(.+?)】x\*\*([\d,]+)\*\*", text):
                 gained_items[item] = int(quantity_str.replace(',', ''))
            
            if gained_items and original_message:
                 crafted_item_name = next(iter(gained_items))
                 crafted_quantity = 1
                 command_parts = original_message.text.split()
                 if len(command_parts) > 2 and command_parts[-1].isdigit():
                     crafted_quantity = int(command_parts[-1])
                 
                 event_payload = {
                     "event_type": "CRAFTING_COMPLETED",
                     "crafted_item": {"name": crafted_item_name, "quantity": crafted_quantity},
                     "gained_items": gained_items
                 }
                 format_and_log("SYSTEM", "事件总线", {'监听到': event_name_for_error})
        except Exception as e:
            await _handle_parsing_error(client, event_name_for_error, e, text)
    
    # 7. 采药完成
    elif "一键采药完成！" in text:
        event_name_for_error = "一键采药"
        try:
            gained_items = {}
            for item, quantity_str in re.findall(r"【(.+?)】x([\d,]+)", text):
                gained_items[item] = int(quantity_str.replace(',', ''))
            
            if gained_items:
                event_payload = { "event_type": "HARVEST_COMPLETED", "gained_items": gained_items }
                format_and_log("SYSTEM", "事件总线", {'监听到': event_name_for_error})
        except Exception as e:
            await _handle_parsing_error(client, event_name_for_error, e, text)
            
    # 8. 学习成功
    elif "成功领悟了" in text:
        event_name_for_error = "学习成功"
        try:
            consumed_match = re.search(r"消耗了【(.+?)】", text)
            if consumed_match:
                item = consumed_match.group(1)
                event_payload = { "event_type": "LEARNING_COMPLETED", "consumed_item": {item: 1} }
                format_and_log("SYSTEM", "事件总线", {'监听到': event_name_for_error})
        except Exception as e:
            await _handle_parsing_error(client, event_name_for_error, e, text)

    # 9. 播种成功
    elif "你已成功在" in text and "播下" in text:
        event_name_for_error = "播种成功"
        try:
            consumed_match = re.search(r"播下【(.+?)】", text)
            if consumed_match:
                item = consumed_match.group(1)
                event_payload = { "event_type": "SOWING_COMPLETED", "consumed_item": {item: 1} }
                format_and_log("SYSTEM", "事件总线", {'监听到': event_name_for_error})
        except Exception as e:
            await _handle_parsing_error(client, event_name_for_error, e, text)

    # --- 最终发布 ---
    if event_payload:
        event_payload.update({ "account_id": my_id, "raw_text": text })
        await publish_task(event_payload, channel=GAME_EVENTS_CHANNEL)

def initialize(app):
    app.client.client.on(events.NewMessage(incoming=True, chats=settings.GAME_GROUP_IDS))(handle_game_report)
    app.client.client.on(events.MessageEdited(incoming=True, chats=settings.GAME_GROUP_IDS))(handle_game_report)
