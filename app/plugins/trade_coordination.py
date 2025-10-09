# -*- coding: utf-8 -*-
import asyncio
import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone

from app import game_adaptor
from app.character_stats_manager import stats_manager
from app.constants import (CRAFTING_RECIPES_KEY, CRAFTING_SESSIONS_KEY,
                           GAME_EVENTS_CHANNEL, KNOWLEDGE_SESSIONS_KEY,
                           TASK_ID_CRAFTING_TIMEOUT)
from app.context import get_application
from app.inventory_manager import inventory_manager
from app.logging_service import LogType, format_and_log
from app.plugins.logic import trade_logic
from app.plugins.logic.crafting_logic import logic_execute_crafting
from app.task_scheduler import scheduler
from app.telegram_client import CommandTimeoutError
from app.utils import create_error_reply
from config import settings

FOCUS_FIRE_SESSIONS = {}

HELP_TEXT_FOCUS_FIRE = """🔥 **集火指令 (v7.0 时间同步协议版)**
**说明**: 采用时间同步协议，由指挥官设定一个未来的绝对时间点，通知双方各自倒数并同时执行购买和下架操作，以实现最高精度的同步。
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

        await progress_msg.edit(f"✅ `已定位助手` (ID: `...{best_account_id[-4:]}`)\n⏳ 正在下达上架指令 (阶段1)...")

        future = asyncio.Future()
        FOCUS_FIRE_SESSIONS[session_id] = future

        task_to_publish = {
            "task_type": "list_item_for_ff",
            "requester_account_id": my_id,
            "target_account_id": best_account_id,
            "payload": {**item_details, "session_id": session_id}
        }

        if not await trade_logic.publish_task(task_to_publish):
            raise ConnectionError("任务发布至 Redis 失败，请检查连接。")

        await progress_msg.edit(f"✅ `上架指令已发送`\n正在等待助手回报挂单ID (阶段2)...")

        listing_id, executor_id = await asyncio.wait_for(future, timeout=settings.COMMAND_TIMEOUT)

        await progress_msg.edit(f"✅ `已收到挂单ID`: `{listing_id}`\n⏳ 正在计算并分发同步时间点 (阶段3)...")

        buffer_seconds = settings.TRADE_COORDINATION_CONFIG.get('focus_fire_sync_buffer_seconds', 5)
        now_utc = datetime.now(timezone.utc)
        go_time = now_utc + timedelta(seconds=buffer_seconds)
        wait_duration = (go_time - now_utc).total_seconds()
        
        await progress_msg.edit(f"✅ `同步点已设定`\n将在 **{wait_duration:.1f}** 秒后同步执行...")
        
        async def buyer_action():
            await asyncio.sleep(wait_duration)
            purchase_command = game_adaptor.buy_item(listing_id)
            await client.send_game_command_fire_and_forget(purchase_command)

        async def seller_action():
            delist_task_payload = {
                "task_type": "execute_synced_delist",
                "target_account_id": executor_id,
                "payload": {
                    "item_id": listing_id,
                    "go_time_iso": go_time.isoformat()
                }
            }
            await trade_logic.publish_task(delist_task_payload)

        await asyncio.gather(buyer_action(), seller_action())
        
        await progress_msg.edit(f"✅ **集火任务完成** (挂单ID: `{listing_id}`)\n- `购买`指令已在同步点发送\n- `同步下架`指令已通知出售方在同步点发送")

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

    progress_msg = await client.reply_to_admin(event,
                                               f"⏳ `[{my_username}] 收货任务启动`\n正在扫描网络查找拥有`{item_name} x{quantity}`的助手...")
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
                "cost": {"name": item_name, "quantity": quantity}
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

# --- Redis Task Handlers ---

async def _handle_game_event(app, event_data):
    """
    [完整实现]
    处理来自 Redis 的游戏事件，并更新相应的状态管理器。
    """
    client = app.client
    my_id = str(client.me.id)
    # 确保事件是针对当前账户的
    if my_id != event_data.get("account_id"):
        return

    my_username = client.me.username if client.me else my_id
    update_details = []
    event_type = event_data.get("event_type")

    # 根据事件类型，调用不同的状态管理器
    if event_type == "TRADE_COMPLETED":
        for item, qty in event_data.get("gained", {}).items():
            await inventory_manager.add_item(item, qty)
            update_details.append(f"获得`{item}`x{qty}")
        for item, qty in event_data.get("sold", {}).items():
            await inventory_manager.remove_item(item, qty)
            update_details.append(f"售出`{item}`x{qty}")
    
    elif event_type == "DONATION_COMPLETED":
        for item, qty in event_data.get("consumed_item", {}).items():
            await inventory_manager.remove_item(item, qty)
            update_details.append(f"捐献`{item}`x{qty}")
        await stats_manager.add_contribution(event_data.get("gained_contribution", 0))
        update_details.append(f"贡献增加`{event_data.get('gained_contribution', 0)}`")

    elif event_type == "EXCHANGE_COMPLETED":
        for item, qty in event_data.get("gained_item", {}).items():
            await inventory_manager.add_item(item, qty)
            update_details.append(f"兑换获得`{item}`x{qty}")
        await stats_manager.remove_contribution(event_data.get("consumed_contribution", 0))
        update_details.append(f"贡献减少`{event_data.get('consumed_contribution', 0)}`")
        
    elif event_type == "CONTRIBUTION_GAINED":
        await stats_manager.add_contribution(event_data.get("gained_contribution", 0))
        update_details.append(f"贡献增加`{event_data.get('gained_contribution', 0)}`")

    elif event_type in ["TOWER_CHALLENGE_COMPLETED", "CRAFTING_COMPLETED", "HARVEST_COMPLETED"]:
        for item, qty in event_data.get("gained_items", {}).items():
            await inventory_manager.add_item(item, qty)
            update_details.append(f"获得`{item}`x{qty}")
            
    elif event_type in ["LEARNING_COMPLETED", "SOWING_COMPLETED"]:
         for item, qty in event_data.get("consumed_item", {}).items():
            await inventory_manager.remove_item(item, qty)
            update_details.append(f"消耗`{item}`x{qty}")

    if update_details:
        await client.send_admin_notification(f"📦 **状态更新通知 (`@{my_username}`)**\n{', '.join(update_details)}")


async def _handle_listing_successful(app, data):
    if str(app.client.me.id) == data.get("target_account_id"):
        payload = data.get("payload", {})
        session_id = payload.get("session_id")
        if future := FOCUS_FIRE_SESSIONS.pop(session_id, None):
            if not future.done():
                future.set_result((payload["item_id"], payload["executor_id"]))


async def _handle_broadcast_command(app, data):
    my_id = str(app.client.me.id)
    if my_id == str(settings.ADMIN_USER_ID): return
    target_sect = data.get("target_sect")
    if target_sect and target_sect != settings.SECT_NAME: return

    command_to_run = data.get("command_to_run")
    if command_to_run:
        format_and_log(LogType.TASK, "广播指令-执行", {'指令': command_to_run, '宗门匹配': bool(target_sect)})
        await app.client.send_game_command_fire_and_forget(command_to_run)


async def redis_message_handler(message):
    app = get_application()
    
    task_handlers = {
        "listing_successful": _handle_listing_successful,
        "broadcast_command": _handle_broadcast_command,
    }
    
    try:
        channel = message['channel']
        data_str = message['data']
        
        if isinstance(data_str, bytes):
            data = json.loads(data_str.decode('utf-8'))
        elif isinstance(data_str, str):
            data = json.loads(data_str)
        else:
             format_and_log(LogType.WARNING, "Redis 任务处理器", {'状态': '跳过', '原因': '消息数据格式未知', '类型': type(data_str)})
             return

        if channel == GAME_EVENTS_CHANNEL:
            await _handle_game_event(app, data)
            return

        task_type = data.get("task_type")

        if hasattr(app, 'extra_redis_handlers'):
            for handler in app.extra_redis_handlers:
                if await handler(data):
                    return
        
        if handler := task_handlers.get(task_type):
            await handler(app, data)

        elif str(app.client.me.id) == data.get("target_account_id"):
            format_and_log(LogType.TASK, "Redis 任务匹配成功", {'任务类型': task_type, '详情': str(data)})
            if task_type == "list_item_for_ff":
                await trade_logic.execute_listing_task(app, data['requester_account_id'], **data.get("payload", {}))
            elif task_type == "purchase_item":
                await trade_logic.execute_purchase_task(app, data.get("payload", {}))
            elif task_type == "execute_synced_delist":
                await trade_logic.execute_synced_unlisting_task(app, data.get("payload", {}))

    except Exception as e:
        format_and_log(LogType.ERROR, "Redis 任务处理器", {'状态': '执行异常', '错误': str(e), '原始消息': message.get('data', '')})

# [重构] 恢复完整的函数体
async def _check_crafting_session_timeouts():
    app = get_application()
    db = app.redis_db
    if not db or not db.is_connected:
        return

    try:
        sessions = await db.hgetall(CRAFTING_SESSIONS_KEY)
        now = time.time()
        timeout_seconds = settings.TRADE_COORDINATION_CONFIG.get('crafting_session_timeout_seconds', 300)

        for session_id, session_json in sessions.items():
            try:
                session_data = json.loads(session_json)
                if now - session_data.get("timestamp", 0) > timeout_seconds:
                    format_and_log(LogType.TASK, "智能炼制-超时检查", {'状态': '发现超时任务', '会话ID': session_id})
                    
                    owner_id = session_id.split('_')[1]
                    # 向发起者发送失败通知
                    await app.client.send_admin_notification(
                        f"⚠️ **智能炼制任务超时**\n\n"
                        f"为炼制 `{session_data.get('item', '未知物品')}` 发起的任务 (ID: `...{session_id[-6:]}`) 已超时并取消。"
                    )
                    
                    await db.hdel(CRAFTING_SESSIONS_KEY, session_id)

            except (json.JSONDecodeError, IndexError) as e:
                format_and_log(LogType.ERROR, "智能炼制-超时检查", {'状态': '处理单个会话异常', '会话ID': session_id, '错误': str(e)})
    
    except Exception as e:
        format_and_log(LogType.ERROR, "智能炼制-超时检查", {'状态': '执行异常', '错误': str(e)})


def initialize(app):
    app.register_command("集火", _cmd_focus_fire, help_text="🔥 协同助手上架并购买物品。", category="协同", usage=HELP_TEXT_FOCUS_FIRE)
    app.register_command("收货", _cmd_receive_goods, help_text="📦 协同助手接收物品。", category="协同", usage=HELP_TEXT_RECEIVE_GOODS)

    scheduler.add_job(
        _check_crafting_session_timeouts, 'interval', minutes=1,
        id=TASK_ID_CRAFTING_TIMEOUT, replace_existing=True
    )
