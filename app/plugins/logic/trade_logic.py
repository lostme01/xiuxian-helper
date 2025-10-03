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
from app import redis_client
from config import settings
from app.task_scheduler import scheduler
from app.plugins.common_tasks import update_inventory_cache

TASK_CHANNEL = "tg_helper:tasks"

async def publish_task(task: dict) -> bool:
    if not redis_client.db:
        format_and_log("ERROR", "任务发布失败", {'原因': 'Redis未连接'}, level=logging.ERROR)
        return False
    try:
        payload = json.dumps(task)
        receiver_count = await redis_client.db.publish(TASK_CHANNEL, payload)
        log_data = {'频道': TASK_CHANNEL, '任务': task, '接收者数量': receiver_count}
        if receiver_count > 0:
            format_and_log("INFO", "Redis-任务已发布", log_data)
        else:
            format_and_log("WARNING", "Redis-任务发布", {**log_data, '诊断': '没有任何客户端订阅此频道！'})
        return True
    except Exception as e:
        format_and_log("ERROR", "任务发布异常", {'错误': str(e)}, level=logging.ERROR)
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

async def execute_listing_task(item_to_sell_name: str, item_to_sell_quantity: int, item_to_buy_name: str, item_to_buy_quantity: int, requester_id: str):
    app = get_application()
    command = f".上架 {item_to_sell_name}*{item_to_sell_quantity} 换 {item_to_buy_name}*{item_to_buy_quantity}"
    format_and_log("TASK", "集火-上架", {'阶段': '开始执行', '指令': command})
    try:
        _sent, reply = await app.client.send_game_command_request_response(command)
        raw_reply_text = reply.raw_text
        match = re.search(r"挂单ID\D+(\d+)", raw_reply_text)
        if "上架成功" in raw_reply_text and match:
            item_id = match.group(1)
            format_and_log("TASK", "集火-上架", {'阶段': '成功', '物品ID': item_id})
            if settings.TRADE_COORDINATION_CONFIG.get('focus_fire_auto_delist', True):
                await asyncio.sleep(random.uniform(1, 2)) 
                format_and_log("TASK", "集火-安全操作", {'阶段': '发送立即下架指令', '挂单ID': item_id})
                await app.client.send_game_command_fire_and_forget(f".下架 {item_id}")
            result_task = {"task_type": "purchase_item", "target_account_id": requester_id, "item_id": item_id}
            await publish_task(result_task)
        else:
            format_and_log("WARNING", "集火-上架", {'阶段': '失败', '原因': '未解析到ID或成功信息', '回复': raw_reply_text})
            await app.client.send_admin_notification(f"❌ **集火失败**：助手号上架 `{item_to_sell_name}` 时，游戏返回异常或无法解析挂单ID。")
    except CommandTimeoutError:
        await app.client.send_admin_notification(f"❌ **集火失败**：助手号上架 `{item_to_sell_name}` 时，等待游戏机器人回复超时。")
    except Exception as e:
        await app.client.send_admin_notification(f"❌ **集火失败**：助手号上架 `{item_to_sell_name}` 时发生未知异常: `{e}`")

async def execute_purchase_task(item_id: str):
    app = get_application()
    command = f".购买 {item_id}"
    format_and_log("TASK", "协同任务-购买", {'阶段': '开始执行', '指令': command})
    try:
        _sent, reply = await app.client.send_game_command_request_response(command)
        
        if "交易成功" in reply.text:
            format_and_log("TASK", "协同任务-购买", {'阶段': '成功', '挂单ID': item_id})
            
            # --- 核心修改：改为调度延迟刷新 ---
            delay_minutes = random.randint(3, 10)
            next_run_time = datetime.now(pytz.timezone(settings.TZ)) + timedelta(minutes=delay_minutes)
            job_id = f"post_purchase_refresh_{app.client.me.id}"
            scheduler.add_job(update_inventory_cache, 'date', run_date=next_run_time, id=job_id, replace_existing=True, args=[True])
            
            await app.client.send_admin_notification(f"✅ **协同购买成功** (挂单ID: `{item_id}`)\n背包将在约 {delay_minutes} 分钟后刷新。")

        elif "你还缺少" in reply.text:
            await app.client.send_admin_notification(f"⚠️ **协同购买失败** (挂单ID: `{item_id}`)\n**原因**: `物品不足`\n{reply.text}")
        elif "已被捷足先登" in reply.text:
            await app.client.send_admin_notification(f"⚠️ **协同购买失败** (挂单ID: `{item_id}`)\n**原因**: `此物已被捷足先登`")
        else:
            await app.client.send_admin_notification(f"⚠️ **协同购买失败** (挂单ID: `{item_id}`)\n游戏机器人返回未知信息:\n`{reply.text}`")
    except CommandTimeoutError:
        await app.client.send_admin_notification(f"❌ **协同购买失败** (挂单ID: `{item_id}`)\n等待游戏机器人回复超时。")
    except Exception as e:
        await app.client.send_admin_notification(f"❌ **协同购买失败** (挂单ID: `{item_id}`)\n发生未知异常: `{e}`。")
