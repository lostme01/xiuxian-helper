# -*- coding: utf-8 -*-
import asyncio
import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone

from app import game_adaptor
from app.character_stats_manager import stats_manager
from app.constants import (CRAFTING_SESSIONS_KEY, TASK_ID_CRAFTING_TIMEOUT,
                           TASK_ID_SESSION_CLEANUP)
from app.context import get_application
from app.data_manager import data_manager
from app.inventory_manager import inventory_manager
from app.logging_service import LogType, format_and_log
from app.plugins.logic import trade_logic
from app.task_scheduler import scheduler
from app.telegram_client import CommandTimeoutError
from app.utils import create_error_reply, progress_manager
from config import settings
# [新增] 导入新的会话管理器
from app.session_manager import get_session_manager

# --- 用户指令处理 ---

HELP_TEXT_FOCUS_FIRE = """🔥 **集火购买 (v11.0 - 持久化)**
**说明**: 任务状态将被持久化，即使程序重启，任务也能在超时后被清理，极大提升可靠性。
**用法 1 (换灵石)**: 
  `,集火购买 <要买的物品> <数量>`
**用法 2 (以物易物)**:
  `,集火购买 <要买的物品> <数量> <用于交换的物品> <数量>`
"""

HELP_TEXT_RECEIVE_GOODS = """📦 **收货上架**
**说明**: 在控制群或私聊中，使用想发起任务的账号发送此指令。该账号将上架物品，并通知网络中拥有足够物品的另一个助手购买。
**用法**: `,收货上架 <物品名称> <数量>`
"""


async def _cmd_focus_fire(event, parts):
    app = get_application()
    client = app.client
    my_id = str(client.me.id)
    my_username = client.me.username or my_id

    if len(parts) < 3:
        await client.reply_to_admin(event, create_error_reply("集火购买", "参数不足", usage_text=HELP_TEXT_FOCUS_FIRE))
        return

    item_details = {}
    try:
        if len(parts) == 3:
            item_details = {"item_to_sell_name": parts[1], "item_to_sell_quantity": int(parts[2]), "item_to_buy_name": "灵石", "item_to_buy_quantity": 1}
        elif len(parts) == 5:
            item_details = {"item_to_sell_name": parts[1], "item_to_sell_quantity": int(parts[2]), "item_to_buy_name": parts[3], "item_to_buy_quantity": int(parts[4])}
        else:
            await client.reply_to_admin(event, create_error_reply("集火购买", "参数格式错误", usage_text=HELP_TEXT_FOCUS_FIRE))
            return
    except ValueError:
        await client.reply_to_admin(event, create_error_reply("集火购买", "数量参数无效", usage_text=HELP_TEXT_FOCUS_FIRE))
        return

    async with progress_manager(event, f"⏳ `[{my_username}] 集火任务启动`\n正在检查自身库存...") as progress:
        session_id = f"ff_{my_id}_{int(time.time())}"
        session_manager = get_session_manager()

        try:
            payment_item = item_details["item_to_buy_name"]
            payment_quantity = item_details["item_to_buy_quantity"]
            my_current_quantity = await inventory_manager.get_item_count(payment_item)
            if my_current_quantity < payment_quantity:
                raise ValueError(f"你需要 `{payment_quantity}` 个`{payment_item}`，但背包中只有 `{my_current_quantity}` 个。")

            await progress.update(f"✅ `自身库存充足`\n正在扫描网络查找目标物品...")
            item_to_find = item_details["item_to_sell_name"]
            quantity_to_find = item_details["item_to_sell_quantity"]
            best_account_id, _ = await trade_logic.find_best_executor(item_to_find, quantity_to_find, exclude_id=my_id)
            if not best_account_id:
                raise RuntimeError(f"未在网络中找到拥有足够数量 `{item_to_find}` 的其他助手。")
            
            session_data = {
                "type": "focus_fire",
                "status": "INITIATED",
                "requester_id": my_id,
                "progress_message_info": {"chat_id": event.chat_id, "message_id": progress.message.id},
                "item_details": item_details,
                "executor_id": best_account_id
            }
            await session_manager.create_session(session_id, session_data)
            
            await progress.update(f"✅ `已定位助手`\n⏳ 正在下达上架指令 (阶段1)...")

            task_to_publish = {
                "task_type": "list_item_for_ff", 
                "requester_account_id": my_id, 
                "target_account_id": best_account_id, 
                "payload": {**item_details, "session_id": session_id}
            }
            if not await trade_logic.publish_task(task_to_publish):
                raise ConnectionError("发布上架任务至 Redis 失败。")
            
            await progress.update(f"✅ `上架指令已发送`\n正在等待对方上架成功 (阶段2)...")

        except Exception as e:
            await session_manager.delete_session(session_id)
            await progress.update(create_error_reply("集火购买", "任务启动失败", details=str(e)))


async def _cmd_receive_goods(event, parts):
    app = get_application(); client = app.client; my_id = str(client.me.id); my_username = client.me.username or my_id
    if len(parts) < 3: 
        await client.reply_to_admin(event, create_error_reply("收货上架", "参数不足", usage_text=HELP_TEXT_RECEIVE_GOODS))
        return
    try: 
        quantity = int(parts[-1])
        item_name = " ".join(parts[1:-1])
    except (ValueError, IndexError): 
        await client.reply_to_admin(event, create_error_reply("收货上架", "参数格式错误", usage_text=HELP_TEXT_RECEIVE_GOODS))
        return

    async with progress_manager(event, f"⏳ `[{my_username}] 收货任务: {item_name}`\n正在扫描网络...") as progress:
        try:
            executor_id, _ = await trade_logic.find_best_executor(item_name, quantity, exclude_id=my_id)
            if not executor_id: raise RuntimeError(f"未在网络中找到拥有足够 `{item_name}` 的助手。")
            
            await progress.update(f"✅ `已定位助手`\n⏳ `正在上架...`")
            list_command = game_adaptor.list_item("灵石", 1, item_name, quantity)
            _sent, reply = await client.send_game_command_request_response(list_command)
            
            if "上架成功" in reply.text:
                match_id = re.search(r"挂单ID\D+(\d+)", reply.text)
                if not match_id: raise ValueError("无法解析挂单ID。")
                item_id = match_id.group(1)
                
                await progress.update(f"✅ `上架成功` (ID: `{item_id}`)\n⏳ `正在通知购买...`")
                task = {"task_type": "purchase_item", "target_account_id": executor_id, "payload": {"item_id": item_id, "cost": {"name": item_name, "quantity": quantity}}}
                
                if await trade_logic.publish_task(task):
                    await progress.update(f"✅ **收货任务已分派**\n已通知目标助手购买挂单 `{item_id}`。")
                else:
                    raise ConnectionError("发布Redis任务失败。")
            else:
                raise RuntimeError(f"上架失败: {reply.text}")
        except Exception as e:
            raise e

# --- Redis 任务处理器 ---

async def _handle_game_event(app, event_data):
    """处理来自游戏事件总线的事件"""
    client = app.client; my_id = str(client.me.id)
    if my_id != event_data.get("account_id"): return
    
    my_username = client.me.username if client.me else my_id
    update_details = []
    event_type = event_data.get("event_type")
    
    source_map = {
        "TRADE_COMPLETED": "交易", "DONATION_COMPLETED": "宗门捐献", 
        "EXCHANGE_COMPLETED": "宗门兑换", "CONTRIBUTION_GAINED": "宗门任务", 
        "TOWER_CHALLENGE_COMPLETED": "闯塔", "CRAFTING_COMPLETED": "炼制", 
        "HARVEST_COMPLETED": "药园采药", "LEARNING_COMPLETED": "学习", 
        "SOWING_COMPLETED": "药园播种", "DELIST_COMPLETED": "下架"
    }
    source = source_map.get(event_type, "未知来源")

    if event_type == "TRADE_COMPLETED":
        for item, qty in event_data.get("gained", {}).items(): 
            await inventory_manager.add_item(item, qty)
            update_details.append(f"获得`{item}`x{qty} ({source})")
        for item, qty in event_data.get("sold", {}).items(): 
            await inventory_manager.remove_item(item, qty)
            update_details.append(f"售出`{item}`x{qty} ({source})")
    elif event_type == "DONATION_COMPLETED":
        for item, qty in event_data.get("consumed_item", {}).items(): 
            await inventory_manager.remove_item(item, qty)
            update_details.append(f"消耗`{item}`x{qty} ({source})")
        if gained_contrib := event_data.get("gained_contribution"): 
            await stats_manager.add_contribution(gained_contrib)
            update_details.append(f"贡献+`{gained_contrib}` ({source})")
    elif event_type == "EXCHANGE_COMPLETED":
        for item, qty in event_data.get("gained_item", {}).items(): 
            await inventory_manager.add_item(item, qty)
            update_details.append(f"获得`{item}`x{qty} ({source})")
        if consumed_contrib := event_data.get("consumed_contribution"): 
            await stats_manager.remove_contribution(consumed_contrib)
            update_details.append(f"贡献-`{consumed_contrib}` ({source})")
    elif event_type == "CONTRIBUTION_GAINED":
        if gained_contrib := event_data.get("gained_contribution"): 
            await stats_manager.add_contribution(gained_contrib)
            update_details.append(f"贡献+`{gained_contrib}` ({source})")
    elif event_type in ["TOWER_CHALLENGE_COMPLETED", "CRAFTING_COMPLETED", "HARVEST_COMPLETED", "DELIST_COMPLETED"]:
        for item, qty in event_data.get("gained_items", {}).items(): 
            await inventory_manager.add_item(item, qty)
            update_details.append(f"获得`{item}`x{qty} ({source})")
    elif event_type in ["LEARNING_COMPLETED", "SOWING_COMPLETED"]:
         for item, qty in event_data.get("consumed_item", {}).items(): 
            await inventory_manager.remove_item(item, qty)
            update_details.append(f"消耗`{item}`x{qty} ({source})")

    if update_details: 
        await client.send_admin_notification(f"📦 **状态更新 (`@{my_username}`)**\n- {', '.join(update_details)}")

async def handle_ff_listing_successful(app, data):
    """处理集火任务中的“上架成功”事件"""
    payload = data.get("payload", {})
    session_id = payload.get("session_id")
    session_manager = get_session_manager()
    session = await session_manager.get_session(session_id)

    if not session or session['status'] != 'INITIATED':
        return

    try:
        await session_manager.update_session(session_id, {
            "status": "AWAITING_SYNC",
            "listing_id": payload["item_id"],
            "executor_id": payload["executor_id"] # 确认最终执行者
        })
        
        progress_info = session['progress_message_info']
        await app.client.client.edit_message(
            progress_info['chat_id'],
            progress_info['message_id'],
            f"✅ `已收到挂单ID`: `{payload['item_id']}`\n⏳ 正在进行状态质询 (阶段3)..."
        )
        
        query_task = {
            "task_type": "query_state", 
            "requester_account_id": session['requester_id'], 
            "target_account_id": payload["executor_id"], 
            "payload": {"session_id": session_id, "chat_id": settings.GAME_GROUP_IDS[0]}
        }
        await trade_logic.publish_task(query_task)

    except Exception as e:
        format_and_log(LogType.ERROR, "集火-处理上架成功时异常", {'session_id': session_id, '错误': str(e)})


async def handle_ff_report_state(app, data):
    """处理集火任务中的“状态回报”事件"""
    payload = data.get("payload", {})
    session_id = payload.get("session_id")
    session_manager = get_session_manager()
    session = await session_manager.get_session(session_id)

    if not session or session['status'] != 'AWAITING_SYNC':
        return

    try:
        client = app.client
        requester_id = session['requester_id']
        executor_id = session['executor_id']
        listing_id = session['listing_id']
        
        buyer_ready_time = await client.get_next_sendable_time(settings.GAME_GROUP_IDS[0])
        seller_ready_time = datetime.fromisoformat(payload["ready_time_iso"])
        go_time = max(buyer_ready_time, seller_ready_time) + timedelta(seconds=settings.TRADE_COORDINATION_CONFIG.get('focus_fire_sync_buffer_seconds', 3))
        
        await session_manager.update_session(session_id, {
            "status": "EXECUTED",
            "go_time_iso": go_time.isoformat()
        })

        progress_info = session['progress_message_info']
        wait_duration = (go_time - datetime.now(timezone.utc)).total_seconds()
        await client.client.edit_message(
            progress_info['chat_id'],
            progress_info['message_id'],
            f"✅ `状态同步完成!`\n将在 **{max(0, wait_duration):.1f}** 秒后执行。"
        )

        buyer_task = {"task_type": "execute_purchase", "target_account_id": requester_id, "payload": {"listing_id": listing_id, "go_time_iso": go_time.isoformat()}}
        seller_task = {"task_type": "execute_synced_delist", "target_account_id": executor_id, "payload": {"item_id": listing_id, "go_time_iso": go_time.isoformat()}}
        
        await trade_logic.publish_task(buyer_task)
        await trade_logic.publish_task(seller_task)

    except Exception as e:
        format_and_log(LogType.ERROR, "集火-处理状态回报时异常", {'session_id': session_id, '错误': str(e)})

async def handle_material_delivered(app, data):
    payload = data.get("payload", {})
    session_id = payload.get("session_id")
    supplier_id = payload.get("supplier_id")
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
            item_to_craft = session_data.get("item")
            quantity = session_data.get("quantity")
            await app.client.send_admin_notification(f"✅ **材料已集齐**\n正在为 `{item_to_craft}` x{quantity} 执行最终炼制...")
            from .crafting_actions import _cmd_craft_item as execute_craft_item
            class FakeEvent:
                def __init__(self):
                    self.chat_id = int(settings.ADMIN_USER_ID)
                    self.is_private = True
                async def reply(self, text):
                     await app.client.send_admin_notification(text)
            await execute_craft_item(FakeEvent(), ["炼制", item_to_craft, str(quantity)])
        else:
             await app.client.send_admin_notification(f"✅ **材料已集齐**\n为炼制 `{session_data.get('item', '未知物品')}` 发起的材料收集任务已完成。")
        await app.redis_db.hdel(CRAFTING_SESSIONS_KEY, session_id)

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

async def handle_propose_knowledge_share(app, data):
    payload = data.get("payload", {})
    recipe_name = payload.get("recipe_name")
    if not recipe_name: return
    
    learned_recipes = await data_manager.get_value("learned_recipes", is_json=True, default=[])
    if recipe_name in learned_recipes:
        format_and_log(LogType.TASK, "知识共享", {'状态': '提议已拒绝', '原因': '该知识已掌握', '知识': recipe_name})
        return
    
    format_and_log(LogType.TASK, "知识共享", {'状态': '提议已接受', '知识': recipe_name, '来源': f"...{payload.get('teacher_id', '')[-4:]}"})
    
    class FakeEvent:
        def __init__(self, sender_id): 
            self.sender_id = sender_id
            self.chat_id = sender_id
            self.is_private = True
            
        async def reply(self, text): 
            await app.client.send_admin_notification(f"【知识共享】: {text}")

    fake_event = FakeEvent(app.client.me.id)
    await _cmd_receive_goods(fake_event, ["收货上架", recipe_name, "1"])


# --- 周期性任务 ---

async def _check_stale_sessions():
    """定期清理超时的协同任务会话"""
    app = get_application()
    session_manager = get_session_manager()
    all_sessions = await session_manager.get_all_sessions()
    now = time.time()
    timeout_seconds = settings.TRADE_COORDINATION_CONFIG.get('crafting_session_timeout_seconds', 300)

    for session_id, session_json in all_sessions.items():
        try:
            session = json.loads(session_json)
            if now - session.get("timestamp", 0) > timeout_seconds:
                if session.get("status") not in ["EXECUTED", "FAILED", "TIMED_OUT"]:
                    await session_manager.update_session(session_id, {"status": "TIMED_OUT"})
                    format_and_log(LogType.TASK, "协同任务-超时检查", {'状态': '发现超时任务', '会话ID': session_id})
                    
                    progress_info = session.get("progress_message_info")
                    if progress_info:
                        try:
                            await app.client.client.edit_message(
                                progress_info['chat_id'],
                                progress_info['message_id'],
                                create_error_reply("集火购买", "任务超时", details=f"任务（ID: ...{session_id[-6:]}）在 {timeout_seconds} 秒内未完成。")
                            )
                        except Exception:
                            # 忽略编辑失败，例如消息已被删除
                            pass
        except Exception as e:
            format_and_log(LogType.ERROR, "协同任务-超时检查异常", {'会话ID': session_id, '错误': str(e)})


def initialize(app):
    app.register_command("集火购买", _cmd_focus_fire, help_text="🔥 协同助手上架并购买物品。", category="协同", aliases=["集火"], usage=HELP_TEXT_FOCUS_FIRE)
    app.register_command("收货上架", _cmd_receive_goods, help_text="📦 协同助手接收物品。", category="协同", aliases=["收货"], usage=HELP_TEXT_RECEIVE_GOODS)
    
    if scheduler.get_job(TASK_ID_CRAFTING_TIMEOUT):
        scheduler.remove_job(TASK_ID_CRAFTING_TIMEOUT)
    scheduler.add_job(_check_stale_sessions, 'interval', minutes=1, id=TASK_ID_SESSION_CLEANUP, replace_existing=True)
