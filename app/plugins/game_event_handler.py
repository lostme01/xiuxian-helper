# -*- coding: utf-8 -*-
import re
import json
from telethon import events
from app.context import get_application
from app.logger import format_and_log
from app.plugins.logic.trade_logic import publish_task
from config import settings
from app import game_adaptor

GAME_EVENTS_CHANNEL = "tg_helper:game_events"

async def handle_game_report(event):
    """
    监听并解析所有游戏报告类消息,
    然后将其作为结构化事件发布到 Redis。
    """
    app = get_application()
    client = app.client
    my_id = str(client.me.id)
    my_username = client.me.username if client.me else None
    
    if not (my_username and event.text):
        return

    is_reply_to_me = False
    original_message = None # 被回复或被编辑的原始消息
    
    # 处理新消息（回复）
    if event.is_reply:
        reply_to_msg = await event.get_reply_message()
        if reply_to_msg and reply_to_msg.sender_id == client.me.id:
            is_reply_to_me = True
            original_message = reply_to_msg
            
    # 处理编辑消息
    elif hasattr(event, 'message') and event.message.edit_date:
        original_msg_id = event.message.id
        # [BUG修复] 使用正确的变量名 pending_edit_waits
        if app.client.pending_edit_waits.get(original_msg_id):
             is_reply_to_me = True

    is_mentioning_me = f"@{my_username}" in event.text
    
    if not is_reply_to_me and not is_mentioning_me:
        return
        
    text = event.text
    event_payload = None

    # 1. 万宝楼快报
    if "【万宝楼快报】" in text:
        format_and_log("SYSTEM", "事件总线", {'监听到': '万宝楼快报', '用户': my_username})
        gained_items = {}
        sold_items = {}
        gain_match = re.search(r"你获得了：(.+)", text)
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

    # 2. 宗门捐献
    elif "你向宗门捐献了" in text:
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
            format_and_log("SYSTEM", "事件总线", {'监听到': '宗门捐献成功'})

    # 3. 宗门兑换
    elif "**兑换成功！**" in text:
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
            format_and_log("SYSTEM", "事件总线", {'监听到': '宗门兑换成功'})
            
    # 4. 点卯或传功获得贡献
    elif "获得了" in text and "点宗门贡献" in text and original_message and (game_adaptor.sect_check_in() in original_message.text or game_adaptor.sect_contribute_skill() in original_message.text):
        contrib_match = re.search(r"获得了 \*\*([\d,]+)\*\* 点宗门贡献", text)
        if contrib_match:
            contrib_str = contrib_match.group(1)
            event_payload = {
                "event_type": "CONTRIBUTION_GAINED",
                "gained_contribution": int(contrib_str.replace(',', ''))
            }
            format_and_log("SYSTEM", "事件总线", {'监听到': '点卯/传功成功'})

    # 5. 闯塔战报
    elif "【试炼古塔 - 战报】" in text and "总收获" in text:
        gained_items = {}
        for item, quantity_str in re.findall(r"获得了【(.+?)】x([\d,]+)", text):
            gained_items[item] = int(quantity_str.replace(',', ''))
        
        if gained_items:
            event_payload = { "event_type": "TOWER_CHALLENGE_COMPLETED", "gained_items": gained_items }
            format_and_log("SYSTEM", "事件总线", {'监听到': '闯塔成功'})

    # 6. 炼制战报
    elif "炼制结束！" in text and "最终获得" in text:
        gained_items = {}
        for item, quantity_str in re.findall(r"最终获得【(.+?)】x\*\*([\d,]+)\*\*", text):
             gained_items[item] = int(quantity_str.replace(',', ''))
        
        if gained_items:
             crafted_item_name = next(iter(gained_items))
             crafted_quantity = 1 
             
             event_payload = {
                 "event_type": "CRAFTING_COMPLETED",
                 "crafted_item": {"name": crafted_item_name, "quantity": crafted_quantity},
                 "gained_items": gained_items
             }
             format_and_log("SYSTEM", "事件总线", {'监听到': '炼制成功'})
    
    # 7. 采药收获
    elif "一键采药完成！" in text:
        gained_items = {}
        for item, quantity_str in re.findall(r"【(.+?)】x([\d,]+)", text):
            gained_items[item] = int(quantity_str.replace(',', ''))
        
        if gained_items:
            event_payload = {
                "event_type": "HARVEST_COMPLETED",
                "gained_items": gained_items
            }
            format_and_log("SYSTEM", "事件总线", {'监听到': '采药成功'})
            
    # 8. 学习成功
    elif "成功领悟了" in text:
        consumed_match = re.search(r"消耗了【(.+?)】", text)
        if consumed_match:
            item = consumed_match.group(1)
            event_payload = {
                "event_type": "LEARNING_COMPLETED",
                "consumed_item": {item: 1}
            }
            format_and_log("SYSTEM", "事件总线", {'监听到': '学习成功'})

    # 9. 播种成功
    elif "你已成功在" in text and "播下" in text:
        consumed_match = re.search(r"播下【(.+?)】", text)
        if consumed_match:
            item = consumed_match.group(1)
            event_payload = {
                "event_type": "SOWING_COMPLETED",
                "consumed_item": {item: 1}
            }
            format_and_log("SYSTEM", "事件总线", {'监听到': '播种成功'})


    # --- 发布事件 ---
    if event_payload:
        event_payload.update({ "account_id": my_id, "raw_text": text })
        await publish_task(event_payload, channel=GAME_EVENTS_CHANNEL)

def initialize(app):
    app.client.client.on(events.NewMessage(incoming=True, chats=settings.GAME_GROUP_IDS))(handle_game_report)
    app.client.client.on(events.MessageEdited(incoming=True, chats=settings.GAME_GROUP_IDS))(handle_game_report)
