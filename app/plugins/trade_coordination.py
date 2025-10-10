# -*- coding: utf-8 -*-
import asyncio
import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone

from app import game_adaptor
from app.character_stats_manager import stats_manager
from app.constants import (CRAFTING_SESSIONS_KEY, GAME_EVENTS_CHANNEL,
                           TASK_ID_CRAFTING_TIMEOUT)
from app.context import get_application
from app.data_manager import data_manager
from app.inventory_manager import inventory_manager
from app.logging_service import LogType, format_and_log
from app.plugins.logic import trade_logic
from app.task_scheduler import scheduler
from app.telegram_client import CommandTimeoutError
from app.utils import create_error_reply
from config import settings

FOCUS_FIRE_SESSIONS = {}

HELP_TEXT_FOCUS_FIRE = """🔥 **集火指令 (v10.0 - 购买前自检版)**
**说明**: 在发起任务前，会首先检查您（购买方）的背包，确保有足够的物品/灵石用于交易。如果不足，任务将立即中止。
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
            item_details = {"item_to_sell_name": parts[1], "item_to_sell_quantity": int(parts[2]), "item_to_buy_name": "灵石", "item_to_buy_quantity": 1}
        elif len(parts) == 5:
            item_details = {"item_to_sell_name": parts[1], "item_to_sell_quantity": int(parts[2]), "item_to_buy_name": parts[3], "item_to_buy_quantity": int(parts[4])}
        else:
            await client.reply_to_admin(event, f"❌ 参数格式错误！\n\n{HELP_TEXT_FOCUS_FIRE}")
            return
    except ValueError:
        await client.reply_to_admin(event, f"❌ 参数中的“数量”必须是数字！\n\n{HELP_TEXT_FOCUS_FIRE}")
        return

    progress_msg = await client.reply_to_admin(event, f"⏳ `[{my_username}] 集火任务启动`\n正在检查自身库存...")
    client.pin_message(progress_msg)
    
    payment_item = item_details["item_to_buy_name"]
    payment_quantity = item_details["item_to_buy_quantity"]
    my_current_quantity = await inventory_manager.get_item_count(payment_item)

    if my_current_quantity < payment_quantity:
        error_msg = create_error_reply("集火", "物品不足，无法发起交易", details=f"你需要 `{payment_quantity}` 个`{payment_item}`，但背包中只有 `{my_current_quantity}` 个。")
        await progress_msg.edit(error_msg)
        client.unpin_message(progress_msg)
        return

    session_id = f"ff_{my_id}_{int(time.time())}"
    try:
        await progress_msg.edit(f"✅ `自身库存充足`\n正在扫描网络查找目标物品...")
        item_to_find = item_details["item_to_sell_name"]
        quantity_to_find = item_details["item_to_sell_quantity"]
        best_account_id, _ = await trade_logic.find_best_executor(item_to_find, quantity_to_find, exclude_id=my_id)
        if not best_account_id: raise RuntimeError(f"未在网络中找到拥有足够数量 `{item_to_find}` 的其他助手。")
        await progress_msg.edit(f"✅ `已定位助手`\n⏳ 正在下达上架指令 (阶段1)...")
        list_future = asyncio.Future()
        FOCUS_FIRE_SESSIONS[session_id + "_list"] = list_future
        task_to_publish = {"task_type": "list_item_for_ff", "requester_account_id": my_id, "target_account_id": best_account_id, "payload": {**item_details, "session_id": session_id}}
        if not await trade_logic.publish_task(task_to_publish): raise ConnectionError("发布上架任务至 Redis 失败。")
        await progress_msg.edit(f"✅ `上架指令已发送`\n正在等待回报挂单ID (阶段2)...")
        listing_id, executor_id = await asyncio.wait_for(list_future, timeout=settings.COMMAND_TIMEOUT)
        await progress_msg.edit(f"✅ `已收到挂单ID`: `{listing_id}`\n⏳ 正在进行状态质询以计算安全同步点 (阶段3)...")
        state_future = asyncio.Future()
        FOCUS_FIRE_SESSIONS[session_id + "_state"] = state_future
        game_group_id = settings.GAME_GROUP_IDS[0]
        buyer_ready_time_task = client.get_next_sendable_time(game_group_id)
        query_task = trade_logic.publish_task({"task_type": "query_state", "requester_account_id": my_id, "target_account_id": executor_id, "payload": {"session_id": session_id, "chat_id": game_group_id}})
        buyer_ready_time, _ = await asyncio.gather(buyer_ready_time_task, query_task)
        await progress_msg.edit(f"✅ `状态质询已发送`\n正在等待对方回报最早可发送时间...")
        seller_ready_time_iso = await asyncio.wait_for(state_future, timeout=settings.COMMAND_TIMEOUT)
        seller_ready_time = datetime.fromisoformat(seller_ready_time_iso)
        earliest_sync_time = max(buyer_ready_time, seller_ready_time)
        buffer_seconds = settings.TRADE_COORDINATION_CONFIG.get('focus_fire_sync_buffer_seconds', 3)
        go_time = earliest_sync_time + timedelta(seconds=buffer_seconds)
        now_utc = datetime.now(timezone.utc)
        wait_duration = (go_time - now_utc).total_seconds()
        await progress_msg.edit(f"✅ `状态同步完成!`\n将在 **{max(0, wait_duration):.1f}** 秒后执行。")
        async def buyer_action():
            if wait_duration > 0: await asyncio.sleep(wait_duration)
            await client.send_game_command_fire_and_forget(game_adaptor.buy_item(listing_id))
        async def seller_action():
            await trade_logic.publish_task({"task_type": "execute_synced_delist", "target_account_id": executor_id, "payload": {"item_id": listing_id, "go_time_iso": go_time.isoformat()}})
        await asyncio.gather(buyer_action(), seller_action())
        await progress_msg.edit(f"✅ **集火任务完成**\n双方指令已在 `{go_time.strftime('%H:%M:%S.%f')[:-3]}` UTC 发送。")
    except asyncio.TimeoutError:
        await progress_msg.edit(create_error_reply("集火", "任务超时", details=f"在 {settings.COMMAND_TIMEOUT} 秒内未收到必要回复。"))
    except Exception as e:
        await progress_msg.edit(create_error_reply("集火", "任务失败", details=str(e)))
    finally:
        client.unpin_message(progress_msg)
        FOCUS_FIRE_SESSIONS.pop(session_id + "_list", None)
        FOCUS_FIRE_SESSIONS.pop(session_id + "_state", None)

async def _cmd_receive_goods(event, parts):
    app = get_application(); client = app.client; my_id = str(client.me.id); my_username = client.me.username or my_id
    if len(parts) < 3: await client.reply_to_admin(event, f"❌ 参数不足！"); return
    try: quantity = int(parts[-1]); item_name = " ".join(parts[1:-1])
    except (ValueError, IndexError): await client.reply_to_admin(event, f"❌ 参数格式错误！"); return
    progress_msg = await client.reply_to_admin(event, f"⏳ `[{my_username}] 收货任务: {item_name}`\n正在扫描网络...")
    client.pin_message(progress_msg)
    try:
        executor_id, _ = await trade_logic.find_best_executor(item_name, quantity, exclude_id=my_id)
        if not executor_id: raise RuntimeError(f"未在网络中找到拥有足够 `{item_name}` 的助手。")
        await progress_msg.edit(f"✅ `已定位助手`\n⏳ `正在上架...`")
        list_command = game_adaptor.list_item("灵石", 1, item_name, quantity)
        _sent, reply = await client.send_game_command_request_response(list_command)
        if "上架成功" in reply.text:
            match_id = re.search(r"挂单ID\D+(\d+)", reply.text)
            if not match_id: raise ValueError("无法解析挂单ID。")
            item_id = match_id.group(1)
            await progress_msg.edit(f"✅ `上架成功` (ID: `{item_id}`)\n⏳ `正在通知购买...`")
            task = {"task_type": "purchase_item", "target_account_id": executor_id, "payload": {"item_id": item_id, "cost": {"name": item_name, "quantity": quantity}}}
            if await trade_logic.publish_task(task): await progress_msg.edit(f"✅ `指令已发送`")
            else: raise ConnectionError("发布Redis任务失败。")
        else: raise RuntimeError(f"上架失败: {reply.text}")
    except Exception as e: await progress_msg.edit(create_error_reply("收货", "任务失败", details=str(e)))
    finally: client.unpin_message(progress_msg)

async def _handle_game_event(app, event_data):
    client = app.client; my_id = str(client.me.id)
    if my_id != event_data.get("account_id"): return
    my_username = client.me.username if client.me else my_id; update_details = []; event_type = event_data.get("event_type")
    source_map = {"TRADE_COMPLETED": "交易", "DONATION_COMPLETED": "宗门捐献", "EXCHANGE_COMPLETED": "宗门兑换", "CONTRIBUTION_GAINED": "宗门任务", "TOWER_CHALLENGE_COMPLETED": "闯塔", "CRAFTING_COMPLETED": "炼制", "HARVEST_COMPLETED": "药园采药", "LEARNING_COMPLETED": "学习", "SOWING_COMPLETED": "药园播种", "DELIST_COMPLETED": "下架"}
    source = source_map.get(event_type, "未知来源")
    if event_type == "TRADE_COMPLETED":
        for item, qty in event_data.get("gained", {}).items(): await inventory_manager.add_item(item, qty); update_details.append(f"获得`{item}`x{qty} ({source})")
        for item, qty in event_data.get("sold", {}).items(): await inventory_manager.remove_item(item, qty); update_details.append(f"售出`{item}`x{qty} ({source})")
    elif event_type == "DONATION_COMPLETED":
        for item, qty in event_data.get("consumed_item", {}).items(): await inventory_manager.remove_item(item, qty); update_details.append(f"消耗`{item}`x{qty} ({source})")
        if gained_contrib := event_data.get("gained_contribution"): await stats_manager.add_contribution(gained_contrib); update_details.append(f"贡献+`{gained_contrib}` ({source})")
    elif event_type == "EXCHANGE_COMPLETED":
        for item, qty in event_data.get("gained_item", {}).items(): await inventory_manager.add_item(item, qty); update_details.append(f"获得`{item}`x{qty} ({source})")
        if consumed_contrib := event_data.get("consumed_contribution"): await stats_manager.remove_contribution(consumed_contrib); update_details.append(f"贡献-`{consumed_contrib}` ({source})")
    elif event_type == "CONTRIBUTION_GAINED":
        if gained_contrib := event_data.get("gained_contribution"): await stats_manager.add_contribution(gained_contrib); update_details.append(f"贡献+`{gained_contrib}` ({source})")
    elif event_type in ["TOWER_CHALLENGE_COMPLETED", "CRAFTING_COMPLETED", "HARVEST_COMPLETED", "DELIST_COMPLETED"]:
        for item, qty in event_data.get("gained_items", {}).items(): await inventory_manager.add_item(item, qty); update_details.append(f"获得`{item}`x{qty} ({source})")
    elif event_type in ["LEARNING_COMPLETED", "SOWING_COMPLETED"]:
         for item, qty in event_data.get("consumed_item", {}).items(): await inventory_manager.remove_item(item, qty); update_details.append(f"消耗`{item}`x{qty} ({source})")
    if update_details: await client.send_admin_notification(f"📦 **状态更新 (`@{my_username}`)**\n- {', '.join(update_details)}")

async def _handle_listing_successful(app, data):
    if str(app.client.me.id) == data.get("target_account_id"):
        payload = data.get("payload", {}); session_id = payload.get("session_id")
        if future := FOCUS_FIRE_SESSIONS.pop(session_id + "_list", None):
            if not future.done(): future.set_result((payload["item_id"], payload["executor_id"]))

async def _handle_report_state(app, data):
    if str(app.client.me.id) == data.get("target_account_id"):
        payload = data.get("payload", {}); session_id = payload.get("session_id")
        if future := FOCUS_FIRE_SESSIONS.get(session_id + "_state"):
            if not future.done(): future.set_result(payload["ready_time_iso"])

async def _handle_broadcast_command(app, data):
    my_id = str(app.client.me.id);
    if my_id == str(settings.ADMIN_USER_ID): return
    target_sect = data.get("target_sect")
    if target_sect and target_sect != settings.SECT_NAME: return
    command_to_run = data.get("command_to_run")
    if command_to_run:
        format_and_log(LogType.TASK, "广播指令-执行", {'指令': command_to_run, '宗门匹配': bool(target_sect)})
        await app.client.send_game_command_fire_and_forget(command_to_run)

# [核心修复] 将 handle_material_delivered 函数的定义补充回来
async def handle_material_delivered(app, data):
    if str(app.client.me.id) != data.get("target_account_id"):
        return
    payload = data.get("payload", {}); session_id = payload.get("session_id"); supplier_id = payload.get("supplier_id")
    if not session_id or not supplier_id: return
    session_json = await app.redis_db.hget(CRAFTING_SESSIONS_KEY, session_id)
    if not session_json: return
    session_data = json.loads(session_json)
    session_data["needed_from"][supplier_id] = True
    await app.redis_db.hset(CRAFTING_SESSIONS_KEY, session_id, json.dumps(session_data))
    format_and_log(LogType.TASK, "智能炼制-回执", {'状态': '已签收', '会话ID': session_id, '提供方': f'...{supplier_id[-4:]}'})
    if all(status for status in session_data["needed_from"].values()):
        format_and_log(LogType.TASK, "智能炼制", {'状态': '材料已集齐', '会话ID': session_id})
        if session_data.get("synthesize", False):
            item_to_craft = session_data.get("item"); quantity = session_data.get("quantity")
            await app.client.send_admin_notification(f"✅ **材料已集齐**\n正在为 `{item_to_craft}` x{quantity} 执行最终炼制...")
            from .crafting_actions import _cmd_craft_item as execute_craft_item
            class FakeEvent: pass
            await execute_craft_item(FakeEvent(), ["炼制", item_to_craft, str(quantity)])
        else:
             await app.client.send_admin_notification(f"✅ **材料已集齐**\n为炼制 `{session_data.get('item', '未知物品')}` 发起的材料收集任务已完成。")
        await app.redis_db.hdel(CRAFTING_SESSIONS_KEY, session_id)

async def redis_message_handler(message):
    app = get_application()
    # [核心修复] 将 handle_material_delivered 添加到处理器字典中
    task_handlers = {"listing_successful": _handle_listing_successful, "broadcast_command": _handle_broadcast_command, "report_state": _handle_report_state, "crafting_material_delivered": handle_material_delivered}
    try:
        channel, data_str = message['channel'], message['data']
        data = json.loads(data_str) if isinstance(data_str, (str, bytes)) else {}
        if channel == GAME_EVENTS_CHANNEL: await _handle_game_event(app, data); return
        task_type = data.get("task_type")
        if handler := task_handlers.get(task_type): await handler(app, data); return
        if task_type == "propose_knowledge_share" and str(app.client.me.id) == data.get("target_account_id"): await handle_propose_knowledge_share(app, data); return
        if hasattr(app, 'extra_redis_handlers'):
            for handler in app.extra_redis_handlers:
                if await handler(data): return
        if str(app.client.me.id) == data.get("target_account_id"):
            format_and_log(LogType.TASK, "Redis 任务匹配成功", {'任务类型': task_type})
            if task_type == "list_item_for_ff": await trade_logic.execute_listing_task(app, data.get("requester_account_id"), **data.get("payload", {}))
            elif task_type == "purchase_item": await trade_logic.execute_purchase_task(app, data.get("payload", {}))
            elif task_type == "execute_synced_delist": await trade_logic.execute_synced_unlisting_task(app, data.get("payload", {}))
            elif task_type == "query_state": await handle_query_state(app, data)
    except Exception as e:
        format_and_log(LogType.ERROR, "Redis 任务处理器", {'状态': '执行异常', '错误': str(e), '原始消息': message.get('data', '')})

async def handle_query_state(app, data):
    payload = data.get("payload", {}); chat_id = payload.get("chat_id")
    if not chat_id: return
    ready_time = await app.client.get_next_sendable_time(chat_id)
    await trade_logic.publish_task({"task_type": "report_state", "target_account_id": data.get("requester_account_id"), "payload": {"session_id": payload.get("session_id"), "ready_time_iso": ready_time.isoformat()}})

async def handle_propose_knowledge_share(app, data):
    payload = data.get("payload", {}); recipe_name = payload.get("recipe_name")
    if not recipe_name: return
    learned_recipes = await data_manager.get_value("learned_recipes", is_json=True, default=[])
    if recipe_name in learned_recipes:
        format_and_log(LogType.TASK, "知识共享", {'状态': '提议已拒绝', '原因': '该知识已掌握', '知识': recipe_name}); return
    format_and_log(LogType.TASK, "知识共享", {'状态': '提议已接受', '知识': recipe_name, '来源': f"...{payload.get('teacher_id', '')[-4:]}"})
    class FakeEvent:
        class FakeMessage:
            def __init__(self, text, sender_id): self.text = text; self.sender_id = sender_id
            async def reply(self, text): await app.client.send_admin_notification(f"【知识共享】: {text}")
        def __init__(self, text, sender_id): self.message = self.FakeMessage(text, sender_id)
    fake_event = FakeEvent(f",收货 {recipe_name} 1", app.client.me.id)
    await _cmd_receive_goods(fake_event, [",收货", recipe_name, "1"])

async def _check_crafting_session_timeouts():
    app = get_application(); db = app.redis_db
    if not db or not db.is_connected: return
    try:
        sessions = await db.hgetall(CRAFTING_SESSIONS_KEY); now = time.time()
        timeout_seconds = settings.TRADE_COORDINATION_CONFIG.get('crafting_session_timeout_seconds', 300)
        for session_id, session_json in sessions.items():
            try:
                session_data = json.loads(session_json)
                if now - session_data.get("timestamp", 0) > timeout_seconds:
                    format_and_log(LogType.TASK, "智能炼制-超时检查", {'状态': '发现超时任务', '会话ID': session_id})
                    owner_id = session_id.split('_')[1]
                    await app.client.send_admin_notification(f"⚠️ **智能炼制任务超时**\n\n为炼制 `{session_data.get('item', '未知物品')}` 发起的任务 (ID: `...{session_id[-6:]}`) 已超时并取消。")
                    await db.hdel(CRAFTING_SESSIONS_KEY, session_id)
            except (json.JSONDecodeError, IndexError) as e:
                format_and_log(LogType.ERROR, "智能炼制-超时检查", {'状态': '处理单个会话异常', '会话ID': session_id, '错误': str(e)})
    except Exception as e:
        format_and_log(LogType.ERROR, "智能炼制-超时检查", {'状态': '执行异常', '错误': str(e)})

def initialize(app):
    app.register_command("集火", _cmd_focus_fire, help_text="🔥 协同助手上架并购买物品。", category="协同", usage=HELP_TEXT_FOCUS_FIRE)
    app.register_command("收货", _cmd_receive_goods, help_text="📦 协同助手接收物品。", category="协同", usage=HELP_TEXT_RECEIVE_GOODS)
    scheduler.add_job(_check_crafting_session_timeouts, 'interval', minutes=1, id=TASK_ID_CRAFTING_TIMEOUT, replace_existing=True)
