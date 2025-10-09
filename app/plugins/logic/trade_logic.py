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


async def publish_task(task: dict, channel: str = TASK_CHANNEL) -> bool:
    if not redis_client.db:
        format_and_log(LogType.ERROR, "任务/事件发布失败", {'原因': 'Redis未连接'}, level=logging.ERROR)
        return False
    try:
        payload = json.dumps(task)
        receiver_count = await redis_client.db.publish(channel, payload)
        log_data = {'频道': channel, '任务/事件': task.get('task_type') or task.get('event_type'), '接收者数量': receiver_count}

        log_level = logging.INFO if receiver_count > 0 else logging.DEBUG

        format_and_log(log_level, f"Redis-发布", log_data)
        return True
    except Exception as e:
        format_and_log(LogType.ERROR, "任务/事件发布异常", {'错误': str(e)}, level=logging.ERROR)
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
            except json.JSONDecodeError:
                continue
    except Exception as e:
        format_and_log(LogType.ERROR, "扫描库存时发生严重异常", {'错误': str(e)}, level=logging.ERROR)
    
    found_quantity = 0
    if best_account_id:
        found_quantity = min_sufficient_quantity if min_sufficient_quantity != float('inf') else 0
    return best_account_id, found_quantity


async def execute_listing_task(app, requester_account_id: str, **kwargs):
    command = game_adaptor.list_item(
        sell_item=kwargs['item_to_sell_name'],
        sell_quantity=kwargs['item_to_sell_quantity'],
        buy_item=kwargs.get('item_to_buy_name', '灵石'),
        buy_quantity=kwargs.get('item_to_buy_quantity', 1)
    )
    format_and_log(LogType.TASK, "集火-上架", {'阶段': '开始执行', '指令': command})

    try:
        _sent, reply = await app.client.send_game_command_request_response(command)
        reply_text = reply.text

        if "上架成功" in reply_text:
            match_id = re.search(r"挂单ID\D+(\d+)", reply_text)
            if not match_id:
                raise ValueError("上架成功但无法解析挂单ID。")

            item_id = match_id.group(1)
            format_and_log(LogType.TASK, "集火-上架", {'阶段': '成功', '物品ID': item_id})

            result_payload = {
                "item_id": item_id,
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
            await app.client.send_admin_notification(
                f"❌ **集火-上架失败**\n助手号上架 `{kwargs['item_to_sell_name']}` 时，游戏返回错误:\n`{reply_text}`")
    except Exception as e:
        await app.client.send_admin_notification(f"❌ **集火-上架异常**\n助手号上架 `{kwargs['item_to_sell_name']}` 时发生异常: `{e}`")


async def execute_unlisting_task(app, item_id: str, is_auto: bool = False):
    command = game_adaptor.unlist_item(item_id)
    log_context = {'阶段': '开始执行', '指令': command, '自动任务': is_auto}
    format_and_log(LogType.TASK, "下架物品", log_context)
    try:
        await app.client.send_game_command_fire_and_forget(command)
    except Exception as e:
        my_username = app.client.me.username if app.client.me else "未知助手"
        await app.client.send_admin_notification(
            f"❌ **下架失败 (`@{my_username}`)**\n\n"
            f"助手在尝试下架挂单ID `{item_id}` 时发生异常。\n"
            f"**错误**: `{e}`"
        )

# [新增] 处理同步下架任务的逻辑
async def execute_synced_unlisting_task(app, payload: dict):
    """
    根据给定的权威时间戳，计算等待时间并执行下架指令。
    """
    item_id = payload.get("item_id")
    go_time_iso = payload.get("go_time_iso")
    if not item_id or not go_time_iso:
        format_and_log(LogType.WARNING, "同步下架", {'阶段': '跳过', '原因': '任务载荷缺少 item_id 或 go_time_iso'})
        return

    try:
        go_time = datetime.fromisoformat(go_time_iso)
        now_utc = datetime.now(timezone.utc)
        wait_seconds = (go_time - now_utc).total_seconds()

        log_data = {
            '阶段': '收到同步任务',
            '挂单ID': item_id,
            '权威时间': go_time_iso,
            '等待秒数': f"{wait_seconds:.2f}"
        }
        format_and_log(LogType.TASK, "同步下架", log_data)

        if wait_seconds > 0:
            await asyncio.sleep(wait_seconds)

        command = game_adaptor.unlist_item(item_id)
        await app.client.send_game_command_fire_and_forget(command)
        format_and_log(LogType.TASK, "同步下架", {'阶段': '指令已发送', '挂单ID': item_id})

    except Exception as e:
        my_username = app.client.me.username if app.client.me else "未知助手"
        await app.client.send_admin_notification(
            f"❌ **同步下架失败 (`@{my_username}`)**\n\n"
            f"助手在尝试同步下架挂单ID `{item_id}` 时发生异常。\n"
            f"**错误**: `{e}`"
        )


async def execute_purchase_task(app, payload: dict):
    command = game_adaptor.buy_item(payload.get("item_id"))
    format_and_log(LogType.TASK, "协同任务-购买", {'阶段': '开始执行', '指令': command})
    try:
        _sent, reply = await app.client.send_game_command_request_response(command)
        reply_text = reply.text

        if "交易成功" in reply_text:
            format_and_log(LogType.TASK, "协同任务-购买", {'阶段': '成功', '挂单ID': payload.get("item_id")})
            await app.client.send_admin_notification(
                f"✅ **协同购买成功** (挂单ID: `{payload.get('item_id')}`)\n系统将通过事件监听自动更新库存。")

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
                format_and_log(LogType.DEBUG, "智能炼制-回执", {'状态': '已发送送达回执', '会话ID': crafting_session_id})
        else:
            error_reason = "未知"
            if "你还缺少" in reply_text:
                error_reason = "购买方物品不足"
            elif "已被捷足先登" in reply_text:
                error_reason = "已被抢购"
            format_and_log(LogType.WARNING, "协同任务-购买", {'阶段': '失败', '挂单ID': payload.get("item_id"), '原因': error_reason, '回复': reply_text})
            await app.client.send_admin_notification(
                f"⚠️ **协同购买失败** (挂单ID: `{payload.get('item_id')}`)\n**原因**: `{error_reason}`\n**游戏回复**:\n`{reply_text}`")
    except Exception as e:
        await app.client.send_admin_notification(f"❌ **协同购买异常** (挂单ID: `{payload.get('item_id')}`)\n发生异常: `{e}`。")
