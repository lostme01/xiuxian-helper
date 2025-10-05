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
from app.plugins.common_tasks import update_inventory_cache
from app.inventory_manager import inventory_manager

TASK_CHANNEL = "tg_helper:tasks"

async def publish_task(task: dict, channel: str = TASK_CHANNEL) -> bool:
    """[升级版] 可向指定频道发布任务或事件"""
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
    if not redis_client.db: return None, 0
    best_account_id = None
    min_sufficient_quantity = float('inf') 
    try:
        keys_found = [key async for key in redis_client.db.scan_iter("tg_helper:task_states:*")]
        for key in keys_found:
            account_id_str = key.split(':')[-1]
            if account_id_str == exclude_id: continue
            
            inventory_json = await redis_client.db.hget(key, "inventory")
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
    if not redis_client.db: return None
    try:
        async for key in redis_client.db.scan_iter("tg_helper:task_states:*"):
            account_id_str = key.split(':')[-1]
            if account_id_str != exclude_id: return account_id_str
    except Exception as e:
        format_and_log("ERROR", "扫描执行者时发生异常", {'错误': str(e)})
    return None

async def execute_listing_task(requester_account_id: str, **kwargs):
    app = get_application()
    
    # [重构] 使用 game_adaptor 生成指令
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

            await inventory_manager.remove_item(kwargs['item_to_sell_name'], kwargs['item_to_sell_quantity'])
            
            format_and_log("TASK", "集火-上架", {'阶段': '成功', '物品ID': item_id})
            
            if settings.TRADE_COORDINATION_CONFIG.get('focus_fire_auto_delist', True):
                await asyncio.sleep(random.uniform(1, 2)) 
                format_and_log("TASK", "集火-安全操作", {'阶段': '发送立即下架指令', '挂单ID': item_id})
                await execute_unlisting_task(item_id, is_auto=True)
            
            task_payload = {
                "item_id": item_id,
                "cost": {
                    "name": kwargs.get('item_to_buy_name', '灵石'),
                    "quantity": kwargs.get('item_to_buy_quantity', 1)
                }
            }
            result_task = {"task_type": "purchase_item", "target_account_id": requester_account_id, "payload": task_payload}
            await publish_task(result_task)

        else:
            format_and_log("WARNING", "集火-上架", {'阶段': '失败', '原因': '游戏返回上架失败信息', '回复': reply_text})
            await app.client.send_admin_notification(f"❌ **集火-上架失败**\n助手号上架 `{kwargs['item_to_sell_name']}` 时，游戏返回错误:\n`{reply_text}`")

    except Exception as e:
        await app.client.send_admin_notification(f"❌ **集火-上架异常**\n助手号上架 `{kwargs['item_to_sell_name']}` 时发生异常: `{e}`")

async def execute_unlisting_task(item_id: str, is_auto: bool = False):
    app = get_application()
    # [重构] 使用 game_adaptor 生成指令
    command = game_adaptor.unlist_item(item_id)
    log_context = {'阶段': '开始执行', '指令': command, '自动任务': is_auto}
    format_and_log("TASK", "下架物品", log_context)
    try:
        _sent, reply = await app.client.send_game_command_request_response(command)
        reply_text = reply.text

        if "成功将" in reply_text and "归还至你的储物袋" in reply_text:
            match_item = re.search(r"\*\*【(.+?)】x(\d+)\*\*", reply_text)
            if match_item:
                returned_item, returned_quantity = match_item.group(1), int(match_item.group(2))
                await inventory_manager.add_item(returned_item, returned_quantity)
        elif not is_auto:
            await app.client.send_admin_notification(f"⚠️ **下架失败** (挂单ID: `{item_id}`)\n游戏返回: `{reply_text}`")
    
    except Exception as e:
        if not is_auto:
            await app.client.send_admin_notification(f"❌ **下架失败** (挂单ID: `{item_id}`)\n发生异常: `{e}`")

async def execute_purchase_task(payload: dict):
    app = get_application()
    my_id = str(app.client.me.id)
    item_id = payload.get("item_id")
    cost = payload.get("cost")
    crafting_session_id = payload.get("crafting_session_id")

    # [重构] 使用 game_adaptor 生成指令
    command = game_adaptor.buy_item(item_id)
    format_and_log("TASK", "协同任务-购买", {'阶段': '开始执行', '指令': command})
    try:
        _sent, reply = await app.client.send_game_command_request_response(command)
        reply_text = reply.text
        
        if "交易成功" in reply_text:
            format_and_log("TASK", "协同任务-购买", {'阶段': '成功', '挂单ID': item_id})
            
            match_gain = re.search(r"你成功购得 \*\*【(.+?)】\*\*x\*\*(\d+)\*\*", reply_text)
            if match_gain:
                gained_item, gained_quantity = match_gain.group(1), int(match_gain.group(2))
                await inventory_manager.add_item(gained_item, gained_quantity)
            
            if cost and cost.get('name') and cost.get('quantity'):
                await inventory_manager.remove_item(cost['name'], cost['quantity'])

            await app.client.send_admin_notification(f"✅ **协同购买成功** (挂单ID: `{item_id}`)\n库存已实时更新。")

            if crafting_session_id:
                receipt_task = {
                    "task_type": "crafting_material_delivered",
                    "target_account_id": crafting_session_id.split('_')[1],
                    "session_id": crafting_session_id,
                    "supplier_id": my_id
                }
                await publish_task(receipt_task)
                format_and_log("DEBUG", "智能炼制-回执", {'状态': '已发送送达回执', '会话ID': crafting_session_id})

        else:
            error_reason = "未知"
            if "你还缺少" in reply_text: 
                error_reason = "购买方物品不足"
            elif "已被捷足先登" in reply_text: 
                error_reason = "已被抢购"
            
            format_and_log("WARNING", "协同任务-购买", {'阶段': '失败', '挂单ID': item_id, '原因': error_reason, '回复': reply_text})
            await app.client.send_admin_notification(f"⚠️ **协同购买失败** (挂单ID: `{item_id}`)\n**原因**: `{error_reason}`\n**游戏回复**:\n`{reply_text}`")
            
    except Exception as e:
        await app.client.send_admin_notification(f"❌ **协同购买异常** (挂单ID: `{item_id}`)\n发生异常: `{e}`。")
