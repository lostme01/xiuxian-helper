# -*- coding: utf-8 -*-
import json
import logging
import re
import shlex
import asyncio
import random
import pytz
import time
from datetime import datetime, timedelta
from telethon import events
from app.context import get_application
from .logic import trade_logic
from app.logger import format_and_log
from config import settings
from app.telegram_client import CommandTimeoutError
from app.task_scheduler import scheduler
from app.plugins.common_tasks import update_inventory_cache
from app.utils import create_error_reply
from app.inventory_manager import inventory_manager
from app.character_stats_manager import stats_manager
from app.plugins.logic.crafting_logic import logic_execute_crafting, CRAFTING_RECIPES_KEY
from app.plugins.game_event_handler import GAME_EVENTS_CHANNEL
from app import game_adaptor

KNOWLEDGE_SESSIONS_KEY = "knowledge_sessions"
FOCUS_FIRE_SESSIONS = {}

HELP_TEXT_FOCUS_FIRE = """🔥 **集火指令 (v3.0)**
**说明**: 使用三步握手机制，实现近乎同步的购买与下架，确保交易安全。
**用法 1 (换灵石)**: 
  `,集火 <要买的物品> <数量>`
**用法 2 (以物易物)**:
  `,集火 <要买的物品> <数量> <用于交换的物品> <数量>`
"""

HELP_TEXT_RECEIVE_GOODS = """📦 **收货指令**
**说明**: 在控制群或私聊中，使用想发起任务的账号发送此指令。该账号将上架物品，并通知网络中拥有足够物品的另一个助手购买。
**用法**: `,收货 <物品名称> <数量>`
"""

async def _cmd_focus_fire(event, parts):
    app = get_application()
    client = app.client
    my_id = str(client.me.id)
    my_username = client.me.username or my_id

    if len(parts) < 3:
        await client.reply_to_admin(event, f"❌ 参数不足！\n\n{HELP_TEXT_FOCUS_FIRE}")
        return

    item_details = {}
    try:
        if len(parts) == 3:
            item_details = {
                "item_to_sell_name": parts[1], "item_to_sell_quantity": int(parts[2]),
                "item_to_buy_name": "灵石", "item_to_buy_quantity": 1
            }
        elif len(parts) == 5:
            item_details = {
                "item_to_sell_name": parts[1], "item_to_sell_quantity": int(parts[2]),
                "item_to_buy_name": parts[3], "item_to_buy_quantity": int(parts[4])
            }
        else:
            await client.reply_to_admin(event, f"❌ 参数格式错误！\n\n{HELP_TEXT_FOCUS_FIRE}")
            return
    except ValueError:
        await client.reply_to_admin(event, f"❌ 参数中的“数量”必须是数字！\n\n{HELP_TEXT_FOCUS_FIRE}")
        return

    item_to_find = item_details["item_to_sell_name"]
    quantity_to_find = item_details["item_to_sell_quantity"]
    progress_msg = await client.reply_to_admin(event, f"⏳ `[{my_username}] 集火任务启动`\n正在扫描网络查找 `{item_to_find}`...")
    client.pin_message(progress_msg)
    
    session_id = f"ff_{my_id}_{int(time.time())}"
    try:
        best_account_id, _ = await trade_logic.find_best_executor(item_to_find, quantity_to_find, exclude_id=my_id)

        if not best_account_id:
            raise RuntimeError(f"未在网络中找到拥有足够数量 `{item_to_find}` 的其他助手。")
        
        await progress_msg.edit(f"✅ `已定位助手` (ID: `...{best_account_id[-4:]}`)\n⏳ 正在通过 Redis 下达上架指令 (第一阶段)...")
        
        future = asyncio.Future()
        FOCUS_FIRE_SESSIONS[session_id] = future
        
        task_to_publish = {
            "task_type": "list_item_for_ff",
            "requester_account_id": my_id,
            "target_account_id": best_account_id,
            "payload": {
                **item_details,
                "session_id": session_id
            }
        }
        
        if not await trade_logic.publish_task(task_to_publish):
            raise ConnectionError("任务发布至 Redis 失败，请检查连接。")

        await progress_msg.edit(f"✅ `上架指令已发送`\n正在等待助手回报挂单ID (第二阶段)...")
        
        listing_id, executor_id = await asyncio.wait_for(future, timeout=settings.COMMAND_TIMEOUT)
        
        await progress_msg.edit(f"✅ `已收到挂单ID`: `{listing_id}`\n⏳ 正在执行购买并触发同步下架 (第三阶段)...")
        
        purchase_command = game_adaptor.buy_item(listing_id)
        purchase_task = asyncio.create_task(client.send_game_command_fire_and_forget(purchase_command))
        
        delist_task_payload = {
            "task_type": "delist_item_for_ff",
            "target_account_id": executor_id,
            "payload": {"item_id": listing_id}
        }
        delist_task = asyncio.create_task(trade_logic.publish_task(delist_task_payload))
        
        await asyncio.gather(purchase_task, delist_task)
        await progress_msg.edit(f"✅ **集火任务完成** (挂单ID: `{listing_id}`)\n- `购买`指令已发送\n- `下架`通知已发送")

    except asyncio.TimeoutError:
        error_text = create_error_reply("集火", "任务超时", details=f"在 {settings.COMMAND_TIMEOUT} 秒内未收到执行者的挂单回报。")
        await progress_msg.edit(error_text)
    except Exception as e:
        error_text = create_error_reply("集火", "任务失败", details=str(e))
        await progress_msg.edit(error_text)
    finally:
        client.unpin_message(progress_msg)
        if session_id in FOCUS_FIRE_SESSIONS:
            del FOCUS_FIRE_SESSIONS[session_id]

async def _cmd_receive_goods(event, parts):
    app = get_application()
    client = app.client
    my_id = str(client.me.id)
    my_username = client.me.username or my_id

    if len(parts) < 3:
        await client.reply_to_admin(event, f"❌ 参数不足！\n\n{HELP_TEXT_RECEIVE_GOODS}")
        return
    try:
        quantity = int(parts[-1])
        item_name = " ".join(parts[1:-1])
    except (ValueError, IndexError):
        await client.reply_to_admin(event, f"❌ 参数格式错误！\n\n{HELP_TEXT_RECEIVE_GOODS}")
        return

    progress_msg = await client.reply_to_admin(event, f"⏳ `[{my_username}] 收货任务启动`\n正在扫描网络查找拥有`{item_name} x{quantity}`的助手...")
    client.pin_message(progress_msg)

    try:
        executor_id, _ = await trade_logic.find_best_executor(item_name, quantity, exclude_id=my_id)
        if not executor_id:
            raise RuntimeError(f"未在网络中找到拥有足够 `{item_name} x{quantity}` 的其他助手。")

        await progress_msg.edit(f"✅ `已定位助手` (ID: `...{executor_id[-4:]}`)\n⏳ 正在上架物品以生成交易单...")
        
        list_command = game_adaptor.list_item("灵石", 1, item_name, quantity)
        _sent, reply = await client.send_game_command_request_response(list_command)
        reply_text = reply.text
        
        if "上架成功" in reply_text:
            match_id = re.search(r"挂单ID\D+(\d+)", reply_text)
            if not match_id:
                raise ValueError("上架成功但无法解析挂单ID。")
            
            item_id = match_id.group(1)
            
            await progress_msg.edit(f"✅ `上架成功` (挂单ID: `{item_id}`)\n⏳ 正在通知助手购买...")
            
            task_payload = {
                "item_id": item_id,
                "cost": { "name": item_name, "quantity": quantity }
            }
            task = {"task_type": "purchase_item", "target_account_id": executor_id, "payload": task_payload}

            if await trade_logic.publish_task(task):
                await progress_msg.edit(f"✅ `指令已发送`\n助手 (ID: `...{executor_id[-4:]}`) 将购买挂单 `{item_id}`。")
            else:
                raise ConnectionError("向 Redis 发布购买任务时失败。")
        else:
            raise RuntimeError(f"上架失败。\n**游戏回复**:\n`{reply_text}`")
    
    except Exception as e:
        error_text = create_error_reply("收货", "任务失败", details=str(e))
        await progress_msg.edit(error_text)
    finally:
        client.unpin_message(progress_msg)


async def _handle_game_event(app, event_data):
    client = app.client
    my_id = str(client.me.id)
    account_id = event_data.get("account_id")
    event_type = event_data.get("event_type")
    
    if my_id != account_id:
        return

    my_username = client.me.username if client.me else my_id
    update_details = []

    if event_type == "TRADE_COMPLETED":
        for item, quantity in event_data.get("gained", {}).items():
            await inventory_manager.add_item(item, quantity)
            update_details.append(f"获得 `{item} x{quantity}`")
        for item, quantity in event_data.get("sold", {}).items():
            await inventory_manager.remove_item(item, quantity)
            update_details.append(f"售出 `{item} x{quantity}`")
    
    elif event_type == "DONATION_COMPLETED":
        for item, quantity in event_data.get("consumed_item", {}).items():
            await inventory_manager.remove_item(item, quantity)
            update_details.append(f"消耗 `{item} x{quantity}`")
        gained_contrib = event_data.get("gained_contribution", 0)
        if gained_contrib > 0:
            await stats_manager.add_contribution(gained_contrib)
            update_details.append(f"获得 `{gained_contrib}` 点贡献")

    elif event_type == "EXCHANGE_COMPLETED":
        for item, quantity in event_data.get("gained_item", {}).items():
            await inventory_manager.add_item(item, quantity)
            update_details.append(f"获得 `{item} x{quantity}`")
        consumed_contrib = event_data.get("consumed_contribution", 0)
        if consumed_contrib > 0:
            await stats_manager.remove_contribution(consumed_contrib)
            update_details.append(f"消耗 `{consumed_contrib}` 点贡献")

    elif event_type == "CONTRIBUTION_GAINED":
        gained_contrib = event_data.get("gained_contribution", 0)
        if gained_contrib > 0:
            await stats_manager.add_contribution(gained_contrib)
            update_details.append(f"获得 `{gained_contrib}` 点贡献 (来自点卯/传功)")

    elif event_type == "TOWER_CHALLENGE_COMPLETED":
        for item, quantity in event_data.get("gained_items", {}).items():
            await inventory_manager.add_item(item, quantity)
            update_details.append(f"获得 `{item} x{quantity}` (闯塔)")

    elif event_type == "CRAFTING_COMPLETED":
        crafted_item = event_data.get("crafted_item", {})
        item_name = crafted_item.get("name")
        quantity_crafted = crafted_item.get("quantity", 1)

        for item, quantity in event_data.get("gained_items", {}).items():
            await inventory_manager.add_item(item, quantity)
            update_details.append(f"获得 `{item} x{quantity}` (炼制)")
            
        if app.redis_db and item_name:
            recipe_json = await app.redis_db.hget(CRAFTING_RECIPES_KEY, item_name)
            if recipe_json:
                try:
                    recipe = json.loads(recipe_json)
                    for material, count_per_unit in recipe.items():
                        if material == "修为": continue
                        total_consumed = count_per_unit * quantity_crafted
                        await inventory_manager.remove_item(material, total_consumed)
                        update_details.append(f"消耗 `{material} x{total_consumed}`")
                except json.JSONDecodeError:
                    pass
    
    elif event_type == "HARVEST_COMPLETED":
        for item, quantity in event_data.get("gained_items", {}).items():
            await inventory_manager.add_item(item, quantity)
            update_details.append(f"获得 `{item} x{quantity}` (采药)")

    elif event_type == "LEARNING_COMPLETED":
        for item, quantity in event_data.get("consumed_item", {}).items():
            await inventory_manager.remove_item(item, quantity)
            update_details.append(f"消耗 `{item} x{quantity}` (学习)")

    elif event_type == "SOWING_COMPLETED":
        for item, quantity in event_data.get("consumed_item", {}).items():
            await inventory_manager.remove_item(item, quantity)
            update_details.append(f"消耗 `{item} x{quantity}` (播种)")


    if await app.redis_db.hlen(KNOWLEDGE_SESSIONS_KEY) > 0:
        gained_items = event_data.get("gained", {})
        for item in gained_items.keys():
            if item.endswith(("图纸", "丹方")):
                sessions = await app.redis_db.hgetall(KNOWLEDGE_SESSIONS_KEY)
                for session_id, session_json in sessions.items():
                    session_data = json.loads(session_json)
                    if session_data.get("student_id") == my_id and session_data.get("item_name") == item:
                        await inventory_manager.remove_item("灵石", 1)
                        await app.redis_db.hdel(KNOWLEDGE_SESSIONS_KEY, session_id)
                        format_and_log("TASK", "知识共享-学生", {'状态': '交易成功，已扣除灵石', '配方': item})
                        update_details.append(f"消耗 `灵石 x1` (知识交换)")
                        break

    if update_details:
        await client.send_admin_notification(f"📦 **状态更新通知 (`@{my_username}`)**\n{', '.join(update_details)}")


async def redis_message_handler(message):
    app = get_application()
    client = app.client
    my_id = str(app.client.me.id)
    try:
        channel = message['channel']
        data = json.loads(message['data'])
        
        if channel == GAME_EVENTS_CHANNEL:
            await _handle_game_event(app, data)
            return

        task_type = data.get("task_type")
        payload = data.get("payload", {})

        if hasattr(app, 'extra_redis_handlers'):
            for handler in app.extra_redis_handlers:
                if await handler(data):
                    return
        
        if task_type == "listing_successful" and my_id == data.get("target_account_id"):
            session_id = payload.get("session_id")
            if future := FOCUS_FIRE_SESSIONS.pop(session_id, None):
                future.set_result((payload["item_id"], payload["executor_id"]))
            return

        if task_type == "delist_item_for_ff" and my_id == data.get("target_account_id"):
            item_id = payload.get("item_id")
            await trade_logic.execute_unlisting_task(item_id, is_auto=True)
            return
            
        if task_type == "broadcast_command":
            if my_id == str(settings.ADMIN_USER_ID): return
            target_sect = data.get("target_sect")
            if target_sect and target_sect != settings.SECT_NAME: return
            
            command_to_run = data.get("command_to_run")
            if command_to_run:
                format_and_log("TASK", "广播指令-执行", {'指令': command_to_run, '宗门匹配': bool(target_sect)})
                await app.client.send_game_command_fire_and_forget(command_to_run)
            return

        if task_type == "initiate_knowledge_request" and my_id == data.get("target_account_id"):
            item_name = payload["item_name"]
            quantity = payload["quantity"]
            list_command = game_adaptor.list_item("灵石", quantity, item_name, quantity)
            
            try:
                _sent, reply = await client.send_game_command_request_response(list_command)
                match = re.search(r"挂单ID\D+(\d+)", reply.text)
                if "上架成功" in reply.text and match:
                    item_id = match.group(1)
                    session_id = f"ks_{my_id}_{item_id}"
                    session_data = {
                        "student_id": my_id, "item_name": item_name, "listing_id": item_id,
                        "status": "LISTED", "timestamp": time.time()
                    }
                    await app.redis_db.hset(KNOWLEDGE_SESSIONS_KEY, session_id, json.dumps(session_data))
                    
                    broadcast_task = { "task_type": "knowledge_listing_available", "payload": session_data }
                    await trade_logic.publish_task(broadcast_task)
                else:
                    raise RuntimeError(f"上架失败: {reply.text}")
            except Exception as e:
                await client.send_admin_notification(f"❌ 自动化知识共享（学生端）上架失败: {e}")
            return
            
        if task_type == "knowledge_listing_available":
            if my_id == str(settings.ADMIN_USER_ID) or my_id == payload.get("student_id"): return
            item_name = payload.get("item_name")
            if await inventory_manager.get_item_count(item_name) > 0:
                command = game_adaptor.buy_item(payload.get('listing_id'))
                await client.send_game_command_fire_and_forget(command)
            return

        if task_type == "cancel_knowledge_request" and my_id == data.get("target_account_id"):
            listing_id = payload.get("listing_id")
            if listing_id:
                command = game_adaptor.unlist_item(listing_id)
                await client.send_game_command_fire_and_forget(command)
                format_and_log("TASK", "知识共享-超时处理", {"动作": "已发送下架指令", "挂单ID": listing_id})
            return

        if my_id != data.get("target_account_id"): return
        
        format_and_log("INFO", "Redis 任务匹配成功", {'任务类型': task_type, '详情': str(data)})
        
        # [核心修复] 新增对 list_item_for_ff 的处理
        if task_type == "list_item_for_ff":
            await trade_logic.execute_listing_task(data['requester_account_id'], **payload)
        elif task_type == "purchase_item":
            await trade_logic.execute_purchase_task(payload)
        
        elif task_type == "crafting_material_delivered":
            session_id = payload.get("session_id")
            supplier_id = payload.get("supplier_id")
            session_json = await app.redis_db.hget("crafting_sessions", session_id)
            if session_json:
                session_data = json.loads(session_json)
                session_data["needed_from"][supplier_id] = True
                if all(session_data["needed_from"].values()):
                    session_data["status"] = "ready_to_craft"
                    final_craft_task = { "task_type": "trigger_final_craft", "target_account_id": my_id, "payload": {"session_id": session_id}}
                    await trade_logic.publish_task(final_craft_task)
                    await app.client.send_admin_notification(f"✅ **智能炼制**: 材料已全部收齐 (会话: `{session_id[-6:]}`)\n⏳ 即将自动执行最终炼制...")
                await app.redis_db.hset("crafting_sessions", session_id, json.dumps(session_data))

        elif task_type == "trigger_final_craft":
            session_id = payload.get("session_id")
            session_json = await app.redis_db.hget("crafting_sessions", session_id)
            if not session_json: return
            session_data = json.loads(session_json)
            async def feedback_handler(text):
                await client.send_admin_notification(f"**智能炼制 (会话: `{session_id[-6:]}`)**\n\n{text}")
            try:
                await logic_execute_crafting(session_data['item'], session_data['quantity'], feedback_handler)
            finally:
                await app.redis_db.hdel("crafting_sessions", session_id)
            
    except Exception as e:
        format_and_log("ERROR", "Redis 任务处理器", {'状态': '执行异常', '错误': str(e)})


async def _check_crafting_session_timeouts():
    app = get_application()
    if not app.redis_db: return
    sessions = await app.redis_db.hgetall("crafting_sessions")
    now = time.time()
    timeout_seconds = settings.TRADE_COORDINATION_CONFIG.get('crafting_session_timeout_seconds', 600)
    for session_id, session_json in sessions.items():
        try:
            session_data = json.loads(session_json)
            if now - session_data.get("timestamp", 0) > timeout_seconds:
                format_and_log("TASK", "智能炼制-超时检查", {'状态': '发现超时任务', '会话ID': session_id})
                initiator_id = session_id.split('_')[1]
                item_name = session_data.get("item", "未知物品")
                failed_suppliers = [f"`...{uid[-4:]}`" for uid, delivered in session_data.get("needed_from", {}).items() if not delivered]
                report = (f"❌ **智能炼制任务超时失败** (会话: `{session_id[-6:]}`)\n\n"
                          f"- **炼制目标**: `{item_name}`\n"
                          f"- **发起者**: `...{initiator_id[-4:]}`\n"
                          f"- **失败原因**: 超过 {int(timeout_seconds / 60)} 分钟未集齐材料。\n"
                          f"- **未响应的供应方**: {', '.join(failed_suppliers) if failed_suppliers else '无'}")
                if str(app.client.me.id) == str(settings.ADMIN_USER_ID):
                    await app.client.send_admin_notification(report)
                await app.redis_db.hdel("crafting_sessions", session_id)
        except Exception as e:
            format_and_log("ERROR", "智能炼制-超时检查", {'状态': '处理异常', '会话ID': session_id, '错误': str(e)})


def initialize(app):
    app.register_command("集火", _cmd_focus_fire, help_text="🔥 协同助手上架并购买物品。", category="协同", usage=HELP_TEXT_FOCUS_FIRE)
    app.register_command("收货", _cmd_receive_goods, help_text="📦 协同助手接收物品。", category="协同", usage=HELP_TEXT_RECEIVE_GOODS)
    
    scheduler.add_job(
        _check_crafting_session_timeouts, 'interval', minutes=1,
        id='crafting_timeout_checker_task', replace_existing=True
    )
