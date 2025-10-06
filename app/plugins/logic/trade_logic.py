# -*- coding: utf-8 -*-
import json
import logging
import re
import asyncio
import random
import pytz
from datetime import datetime, timedelta
from app.context import get_application
from app.logger import format_and_log
from app.telegram_client import CommandTimeoutError, Message
from app import redis_client, game_adaptor
from config import settings
from app.task_scheduler import scheduler
from app.data_manager import data_manager

TASK_CHANNEL = "tg_helper:tasks"

async def publish_task(task: dict, channel: str = TASK_CHANNEL) -> bool:
    if not redis_client.db:
        format_and_log("ERROR", "任务/事件发布失败", {'原因': 'Redis未连接'}, level=logging.ERROR)
        return False
    try:
        payload = json.dumps(task)
        receiver_count = await redis_client.db.publish(channel, payload)
        log_data = {'频道': channel, '任务/事件': task.get('task_type') or task.get('event_type'), '接收者数量': receiver_count}
        
        log_level = "INFO" if receiver_count > 0 else "DEBUG"
        
        format_and_log(log_level, f"Redis-发布", log_data)
        return True
    except Exception as e:
        format_and_log("ERROR", "任务/事件发布异常", {'错误': str(e)}, level=logging.ERROR)
        return False

async def find_best_executor(item_name: str, required_quantity: int, exclude_id: str) -> (str, int):
    if not data_manager.db: return None, 0
    best_account_id = None
    min_sufficient_quantity = float('inf') 
    try:
        keys_found = await data_manager.get_all_assistant_keys()
        for key in keys_found:
            account_id_str = key.split(':')[-1]
            if account_id_str == exclude_id: continue
            
            inventory_json = await data_manager.db.hget(key, "inventory")
            if not inventory_json: continue

            try:
                inventory = json.loads(inventory_json)
                current_quantity = inventory.get(item_name, 0)
                if current_quantity >= required_quantity:
                    if current_quantity < min_sufficient_quantity:
                        min_sufficient_quantity = current_quantity
                        best_account_id = account_id_str
            except json.JSONDecodeError: continue
    except Exception as e:
        format_and_log("ERROR", "扫描库存时发生严重异常", {'错误': str(e)}, level=logging.ERROR)
    found_quantity = 0
    if best_account_id:
        found_quantity = min_sufficient_quantity if min_sufficient_quantity != float('inf') else 0
    return best_account_id, found_quantity

async def find_any_executor(exclude_id: str) -> str | None:
    if not data_manager.db: return None
    try:
        keys_found = await data_manager.get_all_assistant_keys()
        for key in keys_found:
            account_id_str = key.split(':')[-1]
            if account_id_str != exclude_id: return account_id_str
    except Exception as e:
        format_and_log("ERROR", "扫描执行者时发生异常", {'错误': str(e)})
    return None

async def execute_listing_task(requester_account_id: str, **kwargs):
    app = get_application()
    
    command = game_adaptor.list_item(
        sell_item=kwargs['item_to_sell_name'],
        sell_quantity=kwargs['item_to_sell_quantity'],
        buy_item=kwargs.get('item_to_buy_name', '灵石'),
        buy_quantity=kwargs.get('item_to_buy_quantity', 1)
    )
    format_and_log("TASK", "集火-上架", {'阶段': '开始执行', '指令': command})
    
    try:
        _sent, reply = await app.client.send_game_command_request_response(command)
        reply_text = reply.text
        
        if "上架成功" in reply_text:
            match_id = re.search(r"挂单ID\D+(\d+)", reply_text)
            if not match_id:
                raise ValueError("上架成功但无法解析挂单ID。")
            
            item_id = match_id.group(1)
            format_and_log("TASK", "集火-上架", {'阶段': '成功', '物品ID': item_id})
            
            # [核心优化] 将通知发起者和执行者下架两个操作并行化
            
            # 1. 准备购买任务，先通知发起者
            task_payload = {
                "item_id": item_id,
                "cost": {
                    "name": kwargs.get('item_to_buy_name', '灵石'),
                    "quantity": kwargs.get('item_to_buy_quantity', 1)
                }
            }
            result_task = {"task_type": "purchase_item", "target_account_id": requester_account_id, "payload": task_payload}
            
            # 2. 创建两个并行的异步任务
            publish_to_requester_task = asyncio.create_task(publish_task(result_task))
            delist_item_task = asyncio.create_task(asyncio.sleep(0)) # 默认为空任务

            if settings.TRADE_COORDINATION_CONFIG.get('focus_fire_auto_delist', True):
                async def delist_with_delay():
                    await asyncio.sleep(random.uniform(0.5, 1.5)) 
                    format_and_log("TASK", "集火-安全操作", {'阶段': '发送立即下架指令', '挂单ID': item_id})
                    await execute_unlisting_task(item_id, is_auto=True)
                delist_item_task = asyncio.create_task(delist_with_delay())

            # 3. 等待两个任务完成
            await asyncio.gather(publish_to_requester_task, delist_item_task)

        else:
            format_and_log("WARNING", "集火-上架", {'阶段': '失败', '原因': '游戏返回上架失败信息', '回复': reply_text})
            await app.client.send_admin_notification(f"❌ **集火-上架失败**\n助手号上架 `{kwargs['item_to_sell_name']}` 时，游戏返回错误:\n`{reply_text}`")
    except Exception as e:
        await app.client.send_admin_notification(f"❌ **集火-上架异常**\n助手号上架 `{kwargs['item_to_sell_name']}` 时发生异常: `{e}`")

async def execute_unlisting_task(item_id: str, is_auto: bool = False):
    app = get_application()
    command = game_adaptor.unlist_item(item_id)
    log_context = {'阶段': '开始执行', '指令': command, '自动任务': is_auto}
    format_and_log("TASK", "下架物品", log_context)
    try:
        _sent, reply = await app.client.send_game_command_request_response(command)
        reply_text = reply.text
        if not ("成功将" in reply_text and "归还至你的储物袋" in reply_text) and not is_auto:
            await app.client.send_admin_notification(f"⚠️ **下架失败** (挂单ID: `{item_id}`)\n游戏返回: `{reply_text}`")
    except Exception as e:
        if not is_auto:
            await app.client.send_admin_notification(f"❌ **下架失败** (挂单ID: `{item_id}`)\n发生异常: `{e}`")

async def execute_purchase_task(payload: dict):
    app = get_application()
    command = game_adaptor.buy_item(payload.get("item_id"))
    format_and_log("TASK", "协同任务-购买", {'阶段': '开始执行', '指令': command})
    try:
        _sent, reply = await app.client.send_game_command_request_response(command)
        reply_text = reply.text
        
        if "交易成功" in reply_text:
            format_and_log("TASK", "协同任务-购买", {'阶段': '成功', '挂单ID': payload.get("item_id")})
            await app.client.send_admin_notification(f"✅ **协同购买成功** (挂单ID: `{payload.get('item_id')}`)\n系统将通过事件监听自动更新库存。")

            if crafting_session_id := payload.get("crafting_session_id"):
                receipt_task = {
                    "task_type": "crafting_material_delivered",
                    "payload": {
                        "session_id": crafting_session_id,
                        "supplier_id": str(app.client.me.id)
                    },
                    "target_account_id": crafting_session_id.split('_')[1]
                }
                await publish_task(receipt_task)
                format_and_log("DEBUG", "智能炼制-回执", {'状态': '已发送送达回执', '会话ID': crafting_session_id})
        else:
            error_reason = "未知"
            if "你还缺少" in reply_text: error_reason = "购买方物品不足"
            elif "已被捷足先登" in reply_text: error_reason = "已被抢购"
            format_and_log("WARNING", "协同任务-购买", {'阶段': '失败', '挂单ID': payload.get("item_id"), '原因': error_reason, '回复': reply_text})
            await app.client.send_admin_notification(f"⚠️ **协同购买失败** (挂单ID: `{payload.get('item_id')}`)\n**原因**: `{error_reason}`\n**游戏回复**:\n`{reply_text}`")
    except Exception as e:
        await app.client.send_admin_notification(f"❌ **协同购买异常** (挂单ID: `{payload.get('item_id')}`)\n发生异常: `{e}`。")
