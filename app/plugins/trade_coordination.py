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

HELP_TEXT_FOCUS_FIRE = """🔥 **集火指令 (v9.0 状态质询同步版)**
**说明**: 采用“状态质询”协议。指挥官（购买方）在行动前会主动查询双方的“最早可发言时间”，并以此为依据计算出一个对双方都安全的、动态的同步时间点，从根本上解决慢速模式和消息队列的干扰。
**用法**: `,集火 <物品名称> <数量>`
"""

HELP_TEXT_RECEIVE_GOODS = """📦 **收货指令**
**说明**: ... (内容不变) ...
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
            await client.reply_to_admin(event, f"❌ 参数格式错误！\n\n{HELP_TEXT_FOCUS_FIRE}"); return
    except ValueError:
        await client.reply_to_admin(event, f"❌ 参数中的“数量”必须是数字！\n\n{HELP_TEXT_FOCUS_FIRE}"); return

    item_to_find = item_details["item_to_sell_name"]
    progress_msg = await client.reply_to_admin(event, f"⏳ `[{my_username}] 集火任务启动`\n正在扫描网络...")
    client.pin_message(progress_msg)

    session_id = f"ff_{my_id}_{int(time.time())}"
    try:
        best_account_id, _ = await trade_logic.find_best_executor(item_to_find, item_details["item_to_sell_quantity"], exclude_id=my_id)
        if not best_account_id: raise RuntimeError(f"未在网络中找到拥有足够 `{item_to_find}` 的其他助手。")

        await progress_msg.edit(f"✅ `已定位助手`\n⏳ 正在下达上架指令 (阶段1)...")

        list_future = asyncio.Future()
        FOCUS_FIRE_SESSIONS[session_id + "_list"] = list_future
        task_to_publish = {"task_type": "list_item_for_ff", "requester_account_id": my_id, "target_account_id": best_account_id, "payload": {**item_details, "session_id": session_id}}
        if not await trade_logic.publish_task(task_to_publish): raise ConnectionError("发布上架任务至 Redis 失败。")

        await progress_msg.edit(f"✅ `上架指令已发送`\n正在等待回报挂单ID (阶段2)...")
        listing_id, executor_id = await asyncio.wait_for(list_future, timeout=settings.COMMAND_TIMEOUT)

        await progress_msg.edit(f"✅ `已收到挂单ID`: `{listing_id}`\n⏳ 正在进行状态质询以计算安全同步点 (阶段3)...")

        # [重构] 状态质询流程
        state_future = asyncio.Future()
        FOCUS_FIRE_SESSIONS[session_id + "_state"] = state_future
        game_group_id = settings.GAME_GROUP_IDS[0]

        # 1. 并发查询双方状态
        buyer_ready_time_task = client.get_next_sendable_time(game_group_id)
        query_task = trade_logic.publish_task({"task_type": "query_state", "requester_account_id": my_id, "target_account_id": executor_id, "payload": {"session_id": session_id, "chat_id": game_group_id}})
        
        buyer_ready_time, _ = await asyncio.gather(buyer_ready_time_task, query_task)
        
        await progress_msg.edit(f"✅ `状态质询已发送`\n正在等待对方回报最早可发送时间...")
        seller_ready_time_iso = await asyncio.wait_for(state_future, timeout=settings.COMMAND_TIMEOUT)
        seller_ready_time = datetime.fromisoformat(seller_ready_time_iso)

        # 2. 计算最终同步点
        earliest_sync_time = max(buyer_ready_time, seller_ready_time)
        buffer_seconds = settings.TRADE_COORDINATION_CONFIG.get('focus_fire_sync_buffer_seconds', 3)
        go_time = earliest_sync_time + timedelta(seconds=buffer_seconds)
        
        now_utc = datetime.now(timezone.utc)
        wait_duration = (go_time - now_utc).total_seconds()
        
        await progress_msg.edit(f"✅ `状态同步完成!`\n将在 **{max(0, wait_duration):.1f}** 秒后执行。")

        # 3. 双方独立倒计时并执行
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
    # ... (此函数保持不变)
    pass

async def _handle_game_event(app, event_data):
    # ... (此函数保持不变)
    pass

async def _handle_listing_successful(app, data):
    if str(app.client.me.id) == data.get("target_account_id"):
        payload = data.get("payload", {})
        session_id = payload.get("session_id")
        if future := FOCUS_FIRE_SESSIONS.pop(session_id + "_list", None):
            if not future.done(): future.set_result((payload["item_id"], payload["executor_id"]))

async def _handle_report_state(app, data):
    if str(app.client.me.id) == data.get("target_account_id"):
        payload = data.get("payload", {})
        session_id = payload.get("session_id")
        if future := FOCUS_FIRE_SESSIONS.get(session_id + "_state"):
            if not future.done(): future.set_result(payload["ready_time_iso"])

async def _handle_broadcast_command(app, data):
    # ... (此函数保持不变)
    pass

async def redis_message_handler(message):
    app = get_application()
    task_handlers = {"listing_successful": _handle_listing_successful, "broadcast_command": _handle_broadcast_command, "report_state": _handle_report_state}
    try:
        channel, data_str = message['channel'], message['data']
        data = json.loads(data_str) if isinstance(data_str, (str, bytes)) else {}
        if channel == GAME_EVENTS_CHANNEL: await _handle_game_event(app, data); return
        task_type = data.get("task_type")
        if hasattr(app, 'extra_redis_handlers'):
            for handler in app.extra_redis_handlers:
                if await handler(data): return
        if handler := task_handlers.get(task_type): await handler(app, data)
        elif str(app.client.me.id) == data.get("target_account_id"):
            format_and_log(LogType.TASK, "Redis 任务匹配成功", {'任务类型': task_type})
            if task_type == "list_item_for_ff": await trade_logic.execute_listing_task(app, data.get("requester_account_id"), **data.get("payload", {}))
            elif task_type == "purchase_item": await trade_logic.execute_purchase_task(app, data.get("payload", {}))
            elif task_type == "execute_synced_delist": await trade_logic.execute_synced_unlisting_task(app, data.get("payload", {}))
            elif task_type == "query_state": await handle_query_state(app, data)
    except Exception as e:
        format_and_log(LogType.ERROR, "Redis 任务处理器", {'状态': '执行异常', '错误': str(e), '原始消息': message.get('data', '')})

async def handle_query_state(app, data):
    payload = data.get("payload", {})
    chat_id = payload.get("chat_id")
    if not chat_id: return
    ready_time = await app.client.get_next_sendable_time(chat_id)
    await trade_logic.publish_task({
        "task_type": "report_state",
        "target_account_id": data.get("requester_account_id"),
        "payload": {"session_id": payload.get("session_id"), "ready_time_iso": ready_time.isoformat()}
    })

async def _check_crafting_session_timeouts():
    # ... (此函数保持不变)
    pass

def initialize(app):
    app.register_command("集火", _cmd_focus_fire, help_text="🔥 协同助手上架并购买物品。", category="协同", usage=HELP_TEXT_FOCUS_FIRE)
    app.register_command("收货", _cmd_receive_goods, help_text="📦 协同助手接收物品。", category="协同", usage=HELP_TEXT_RECEIVE_GOODS)
    scheduler.add_job(_check_crafting_session_timeouts, 'interval', minutes=1, id=TASK_ID_CRAFTING_TIMEOUT, replace_existing=True)
