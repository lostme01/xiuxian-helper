# -*- coding: utf-8 -*-
import json
import logging
import re
import asyncio
from datetime import datetime, timezone

from app import game_adaptor, redis_client
from app.constants import TASK_CHANNEL
from app.data_manager import data_manager
from app.logging_service import LogType, format_and_log
from app.context import get_application
from config import settings


async def publish_task(task: dict, channel: str = TASK_CHANNEL) -> bool:
    """向 Redis 发布一个任务或事件。"""
    if not redis_client.db or not redis_client.db.is_connected:
        format_and_log(LogType.ERROR, "任务/事件发布失败", {'原因': 'Redis未连接'}, level=logging.ERROR)
        return False
    try:
        payload = json.dumps(task)
        receiver_count = await redis_client.db.publish(channel, payload)
        log_data = {'频道': channel, '任务/事件': task.get('task_type') or task.get('event_type'), '接收者数量': receiver_count}

        log_type = LogType.DEBUG if receiver_count > 0 else LogType.SYSTEM
        log_level = logging.DEBUG if receiver_count > 0 else logging.INFO

        format_and_log(log_type, "Redis-发布", log_data, level=log_level)
        return True
    except Exception as e:
        format_and_log(LogType.ERROR, "任务/事件发布异常", {'错误': str(e)}, level=logging.ERROR)
        return False


async def find_best_executor(item_name: str, required_quantity: int, exclude_id: str) -> (str, int):
    """在网络中寻找拥有足够物品的最佳助手。"""
    if not data_manager.db or not data_manager.db.is_connected: return None, 0
    
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
            except json.JSONDecodeError:
                continue
    except Exception as e:
        format_and_log(LogType.ERROR, "扫描库存时发生严重异常", {'错误': str(e)}, level=logging.ERROR)
    
    found_quantity = 0
    if best_account_id:
        found_quantity = min_sufficient_quantity if min_sufficient_quantity != float('inf') else 0
    return best_account_id, found_quantity


# --- 具体的任务执行逻辑 ---

async def execute_broadcast_command(app, data):
    my_id = str(app.client.me.id);
    if my_id == str(settings.ADMIN_USER_ID): return
    target_sect = data.get("target_sect")
    if target_sect and target_sect != settings.SECT_NAME: return
    command_to_run = data.get("command_to_run")
    if command_to_run:
        format_and_log(LogType.TASK, "广播指令-执行", {'指令': command_to_run, '宗门匹配': bool(target_sect)})
        await app.client.send_game_command_fire_and_forget(command_to_run, priority=1)

async def execute_listing_task(app, requester_account_id: str, **kwargs):
    command = game_adaptor.list_item(
        sell_item=kwargs['item_to_sell_name'],
        sell_quantity=kwargs['item_to_sell_quantity'],
        buy_item=kwargs.get('item_to_buy_name', '灵石'),
        buy_quantity=kwargs.get('item_to_buy_quantity', 1)
    )
    format_and_log(LogType.TASK, "集火-上架", {'阶段': '开始执行', '指令': command})

    try:
        _sent, reply = await app.client.send_game_command_request_response(command, priority=1)
        reply_text = reply.text

        if "上架成功" in reply_text:
            match_id = re.search(r"挂单ID\D+(\d+)", reply_text)
            if not match_id:
                raise ValueError("上架成功但无法解析挂单ID。")

            listing_id = match_id.group(1)
            format_and_log(LogType.TASK, "集火-上架", {'阶段': '成功', '物品ID': listing_id})

            result_payload = {
                "listing_id": listing_id,
                "executor_id": str(app.client.me.id)
            }
            if 'session_id' in kwargs:
                result_payload['session_id'] = kwargs['session_id']

            result_task = {
                "task_type": "listing_successful",
                "target_account_id": requester_account_id,
                "payload": result_payload
            }
            await publish_task(result_task)
        else:
            format_and_log(LogType.WARNING, "集火-上架", {'阶段': '失败', '原因': '游戏返回上架失败信息', '回复': reply_text})
    except Exception as e:
        format_and_log(LogType.ERROR, "集火-上架异常", {'错误': str(e)})


async def execute_synced_unlisting_task(app, **payload):
    listing_id = payload.get("listing_id")
    go_time_iso = payload.get("go_time_iso")
    if not listing_id or not go_time_iso:
        return

    try:
        go_time = datetime.fromisoformat(go_time_iso)
        now_utc = datetime.now(timezone.utc)
        wait_seconds = (go_time - now_utc).total_seconds()

        if wait_seconds > 0:
            await asyncio.sleep(wait_seconds)

        command = game_adaptor.unlist_item(listing_id)
        await app.client.send_game_command_fire_and_forget(command, priority=0)
    except Exception as e:
        format_and_log(LogType.ERROR, "同步下架异常", {'错误': str(e)})


async def execute_purchase_task(app, **payload):
    """[最终修复] 补全等待逻辑"""
    listing_id = payload.get("listing_id") or payload.get("item_id")
    go_time_iso = payload.get("go_time_iso")

    if not listing_id or not go_time_iso:
        format_and_log(LogType.WARNING, "协同任务-购买", {'阶段': '中止', '原因': '缺少listing_id或go_time_iso'})
        return

    try:
        # --- 核心修复：从 execute_synced_unlisting_task 复制过来的等待逻辑 ---
        go_time = datetime.fromisoformat(go_time_iso)
        now_utc = datetime.now(timezone.utc)
        wait_seconds = (go_time - now_utc).total_seconds()

        if wait_seconds > 0:
            await asyncio.sleep(wait_seconds)
        # --- 修复结束 ---

        command = game_adaptor.buy_item(listing_id)
        format_and_log(LogType.TASK, "协同任务-购买", {'阶段': '开始执行', '指令': command, '优先级': '最高'})
        
        _sent, reply = await app.client.send_game_command_request_response(command, priority=0)
        
        if "交易成功" not in reply.text:
             format_and_log(LogType.WARNING, "协同任务-购买失败", {'回复': reply.text})

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
    except Exception as e:
        format_and_log(LogType.ERROR, "协同购买异常", {'错误': str(e)})
