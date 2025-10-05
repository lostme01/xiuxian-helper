# -*- coding: utf-8 -*-
import json
import logging
import re
import shlex
import asyncio
import random
import pytz
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
from app.plugins.crafting_actions import _cmd_craft_item as execute_craft_item

HELP_TEXT_FOCUS_FIRE = """🔥 **集火指令**
**说明**: 在控制群或私聊中，使用想发起任务的账号发送此指令。该账号将成为发起者，并自动协调网络中其他助手完成交易。
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

    task_payload = {"task_type": "list_item", "requester_account_id": my_id}
    try:
        if len(parts) == 3:
            task_payload.update({
                "item_to_sell_name": parts[1], "item_to_sell_quantity": int(parts[2]),
                "item_to_buy_name": "灵石", "item_to_buy_quantity": 1
            })
        elif len(parts) == 5:
            task_payload.update({
                "item_to_sell_name": parts[1], "item_to_sell_quantity": int(parts[2]),
                "item_to_buy_name": parts[3], "item_to_buy_quantity": int(parts[4])
            })
        else:
            await client.reply_to_admin(event, f"❌ 参数格式错误！\n\n{HELP_TEXT_FOCUS_FIRE}")
            return
    except ValueError:
        await client.reply_to_admin(event, f"❌ 参数中的“数量”必须是数字！\n\n{HELP_TEXT_FOCUS_FIRE}")
        return

    item_to_find = task_payload["item_to_sell_name"]
    quantity_to_find = task_payload["item_to_sell_quantity"]
    progress_msg = await client.reply_to_admin(event, f"⏳ `[{my_username}] 集火任务启动`\n正在扫描网络查找 `{item_to_find}`...")
    client.pin_message(progress_msg)
    
    try:
        best_account_id, _ = await trade_logic.find_best_executor(item_to_find, quantity_to_find, exclude_id=my_id)

        if not best_account_id:
            raise RuntimeError(f"未在网络中找到拥有足够数量 `{item_to_find}` 的其他助手。")
        
        await progress_msg.edit(f"✅ `已定位助手` (ID: `...{best_account_id[-4:]}`)\n⏳ 正在通过 Redis 下达上架指令...")
        task_payload["target_account_id"] = best_account_id
        if await trade_logic.publish_task(task_payload):
            await progress_msg.edit(f"✅ `指令已发送`\n等待助手号回报上架结果...")
        else:
            raise ConnectionError("任务发布至 Redis 失败，请检查连接。")
            
    except Exception as e:
        error_text = create_error_reply("集火", "任务失败", details=str(e))
        await progress_msg.edit(error_text)
    finally:
        client.unpin_message(progress_msg)


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
        
        list_command = f".上架 灵石*1 换 {item_name}*{quantity}"
        _sent, reply = await client.send_game_command_request_response(list_command)
        reply_text = reply.text
        
        if "上架成功" in reply_text:
            match_id = re.search(r"挂单ID\D+(\d+)", reply_text)
            if not match_id:
                raise ValueError("上架成功但无法解析挂单ID。")
            
            item_id = match_id.group(1)
            await inventory_manager.remove_item("灵石", 1)

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

async def redis_message_handler(message):
    app = get_application()
    my_id = str(app.client.me.id)
    try:
        data = json.loads(message['data'])
        task_type = data.get("task_type")

        if hasattr(app, 'extra_redis_handlers'):
            for handler in app.extra_redis_handlers:
                if await handler(data):
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

        if my_id != data.get("target_account_id"): return
        
        format_and_log("INFO", "Redis 任务匹配成功", {'任务类型': task_type, '详情': str(data)})
        
        if task_type == "list_item":
            payload = {k: v for k, v in data.items() if k not in ['task_type', 'target_account_id']}
            await trade_logic.execute_listing_task(**payload)
        elif task_type == "purchase_item":
            await trade_logic.execute_purchase_task(data.get("payload", {}))
        
        elif task_type == "crafting_material_delivered":
            session_id = data.get("session_id")
            supplier_id = data.get("supplier_id")
            session_json = await app.redis_db.hget("crafting_sessions", session_id)
            if session_json:
                session_data = json.loads(session_json)
                session_data["needed_from"][supplier_id] = True
                
                if all(session_data["needed_from"].values()):
                    session_data["status"] = "ready_to_craft"
                    final_craft_task = {
                        "task_type": "trigger_final_craft",
                        "target_account_id": my_id,
                        "session_id": session_id
                    }
                    await trade_logic.publish_task(final_craft_task)
                    await app.client.send_admin_notification(f"✅ **智能炼制**: 材料已全部收齐 (会话: `{session_id[-6:]}`)\n⏳ 即将自动执行最终炼制...")
                
                await app.redis_db.hset("crafting_sessions", session_id, json.dumps(session_data))

        elif task_type == "trigger_final_craft":
            session_id = data.get("session_id")
            session_json = await app.redis_db.hget("crafting_sessions", session_id)
            if session_json:
                session_data = json.loads(session_json)
                item = session_data['item']
                quantity = session_data['quantity']
                
                fake_event = type('FakeEvent', (object,), {
                    'reply': app.client.send_admin_notification,
                })()

                craft_parts = ["炼制物品", item, str(quantity)]
                await execute_craft_item(fake_event, craft_parts)
                await app.redis_db.hdel("crafting_sessions", session_id)

            
    except Exception as e:
        format_and_log("ERROR", "Redis 任务处理器", {'状态': '执行异常', '错误': str(e)})

async def handle_trade_report(event):
    """
    [最终修复版]
    处理万宝楼快报，统一解析单件或多件物品。
    """
    app = get_application()
    client = app.client
    if not (client.me and client.me.username and event.text):
        return
    
    my_username = client.me.username
    if "【万宝楼快报】" not in event.text or f"@{my_username}" not in event.text:
        return
        
    format_and_log("INFO", "万宝楼快报", {'状态': '匹配成功', '用户': my_username})
    
    gain_match = re.search(r"你获得了：(.+)", event.text)
    if gain_match:
        gained_items_str = gain_match.group(1).strip().rstrip('。')
        
        # 使用 findall 一次性解析所有物品，无论是一个还是多个
        gained_items = re.findall(r"【(.+?)】x([\d,]+)", gained_items_str)
        
        if gained_items:
            update_details = []
            for item, quantity_str in gained_items:
                quantity = int(quantity_str.replace(',', ''))
                await inventory_manager.add_item(item, quantity)
                update_details.append(f"`{item} x{quantity}`")
            
            await client.send_admin_notification(f"✅ **交易售出通知 (`@{my_username}`)**\n库存已实时增加: {', '.join(update_details)}")

def initialize(app):
    app.register_command("集火", _cmd_focus_fire, help_text="🔥 协同助手上架并购买物品。", category="协同", usage=HELP_TEXT_FOCUS_FIRE)
    app.register_command("收货", _cmd_receive_goods, help_text="📦 协同助手接收物品。", category="协同", usage=HELP_TEXT_RECEIVE_GOODS)
