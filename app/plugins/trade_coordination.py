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

HELP_TEXT_FOCUS_FIRE = """🔥 **集火指令 (v6.1 同步增强版)**
**说明**: 在决策阶段实时查询双方的发言冷却时间，计算出由服务器认证的、绝对同步的执行时间点，以最高的成功率完成交易。
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

        await progress_msg.edit(f"✅ `已定位助手` (ID: `...{best_account_id[-4:]}`)\n⏳ 正在下达上架指令 (第一阶段)...")

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

        await progress_msg.edit(f"✅ `上架指令已发送`\n正在等待助手回报挂单ID (第二阶段)...")

        listing_id, executor_id = await asyncio.wait_for(future, timeout=settings.COMMAND_TIMEOUT)

        await progress_msg.edit(f"✅ `已收到挂单ID`: `{listing_id}`\n⏳ 正在实时查询双方冷却状态 (第三阶段)...")

        game_group_id = settings.GAME_GROUP_IDS[0]

        my_until_date_task = client.get_participant_info(game_group_id, int(my_id))
        executor_until_date_task = client.get_participant_info(game_group_id, int(executor_id))

        my_until_date, executor_until_date = await asyncio.gather(my_until_date_task, executor_until_date_task)

        now_utc = datetime.now(timezone.utc)

        latest_time = now_utc
        if my_until_date and my_until_date > latest_time:
            latest_time = my_until_date
        if executor_until_date and executor_until_date > latest_time:
            latest_time = executor_until_date

        go_time = latest_time + timedelta(seconds=0.5)
        wait_duration = (go_time - now_utc).total_seconds()
        
        await progress_msg.edit(f"✅ `同步点已计算`\n根据服务器权威时间，将在 **{wait_duration:.1f}** 秒后同步执行...")
        
        async def buyer_action():
            if wait_duration > 0:
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
    client = app.client
    my_id = str(client.me.id)
    if my_id != event_data.get("account_id"):
        return
    # ... (event handling logic remains the same)


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
        # [修复] 移除 .decode()，因为 decode_responses=True 已经处理
        channel = message['channel']
        data_str = message['data']
        
        # 确保 data 是字符串类型再加载
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


async def _check_crafting_session_timeouts():
    # ... (function logic remains the same)
    pass


def initialize(app):
    app.register_command("集火", _cmd_focus_fire, help_text="🔥 协同助手上架并购买物品。", category="协同", usage=HELP_TEXT_FOCUS_FIRE)
    app.register_command("收货", _cmd_receive_goods, help_text="📦 协同助手接收物品。", category="协同", usage=HELP_TEXT_RECEIVE_GOODS)

    scheduler.add_job(
        _check_crafting_session_timeouts, 'interval', minutes=1,
        id=TASK_ID_CRAFTING_TIMEOUT, replace_existing=True
    )
