# -*- coding: utf-8 -*-
import json
import logging
import re
import shlex
from telethon import events
from app.context import get_application
from .logic import trade_logic
from app.logger import format_and_log
from config import settings
from app.telegram_client import CommandTimeoutError

HELP_TEXT_FOCUS_FIRE = """🔥 **集火指令 (P2P最终版)**
**说明**: 在控制群或私聊中，使用想发起任务的账号发送此指令。该账号将成为发起者，并自动协调网络中其他助手完成交易。
**用法 1 (换灵石)**: 
  `,集火 <要买的物品> <数量>`
  *示例*: `,集火 金精矿 10`

**用法 2 (以物易物)**:
  `,集火 <要买的物品> <数量> <用于交换的物品> <数量>`
  *示例*: `,集火 百年铁木 2 凝血草 20`
"""

HELP_TEXT_RECEIVE_GOODS = """📦 **收货指令 (P2P最终版)**
**说明**: 在控制群或私聊中，使用想发起任务的账号发送此指令。该账号将上架物品，并通知网络中其他助手购买。
**用法**: `,收货 <物品名称> <数量>`
**示例**: `,收货 凝血草 100`
"""

async def _cmd_focus_fire(event, parts):
    """
    处理“集火”指令的函数，由统一分发器在确认权限后调用。
    """
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
    
    best_account_id, _ = await trade_logic.find_best_executor(item_to_find, quantity_to_find, exclude_id=my_id)

    if not best_account_id:
        await progress_msg.edit(f"❌ `任务失败`\n未在网络中找到拥有足够数量 `{item_to_find}` 的其他助手。")
    else:
        await progress_msg.edit(f"✅ `已定位助手` (ID: `...{best_account_id[-4:]}`)\n⏳ 正在通过 Redis 下达上架指令...")
        task_payload["target_account_id"] = best_account_id
        if await trade_logic.publish_task(task_payload):
            await progress_msg.edit(f"✅ `指令已发送`\n等待助手号回报上架结果...")
        else:
            await progress_msg.edit(f"❌ `任务失败`\n任务发布至 Redis 失败，请检查连接。")
    
    client.unpin_message(progress_msg)

async def _cmd_receive_goods(event, parts):
    """
    处理“收货”指令的函数，由统一分发器在确认权限后调用。
    """
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

    progress_msg = await client.reply_to_admin(event, f"⏳ `[{my_username}] 收货任务启动`\n正在寻找网络中任意一个助手...")
    client.pin_message(progress_msg)

    executor_id = await trade_logic.find_any_executor(exclude_id=my_id)
    if not executor_id:
        await progress_msg.edit("❌ `任务失败`\n未在 Redis 中找到任何其他在线的助手。")
        client.unpin_message(progress_msg)
        return

    await progress_msg.edit(f"✅ `已定位助手` (ID: `...{executor_id[-4:]}`)\n⏳ 正在上架物品以生成交易单...")
    try:
        list_command = f".上架 灵石*1 换 {item_name}*{quantity}"
        _sent, reply = await client.send_game_command_request_response(list_command)
        raw_reply_text = reply.raw_text
        match = re.search(r"挂单ID\D+(\d+)", raw_reply_text)
        if "上架成功" in raw_reply_text and match:
            item_id = match.group(1)
            await progress_msg.edit(f"✅ `上架成功` (挂单ID: `{item_id}`)\n⏳ 正在通知助手购买...")
            task = {"task_type": "purchase_item", "target_account_id": executor_id, "item_id": item_id}
            if await trade_logic.publish_task(task):
                await progress_msg.edit(f"✅ `指令已发送`\n助手 (ID: `...{executor_id[-4:]}`) 将购买挂单 `{item_id}`。")
            else:
                await progress_msg.edit("❌ `任务失败`\n向 Redis 发布购买任务时失败。")
        else:
            await progress_msg.edit(f"❌ `任务失败`\n上架时未能获取挂单ID。\n**回复**:\n`{raw_reply_text}`")
    except (CommandTimeoutError, Exception) as e:
        await progress_msg.edit(f"❌ `任务失败`\n在上架物品时发生错误: `{e}`")
    finally:
        client.unpin_message(progress_msg)

async def redis_message_handler(message):
    app = get_application()
    my_id = str(app.client.me.id)
    try:
        data = json.loads(message['data'])
        task_type = data.get("task_type")
        if task_type in ["list_item", "purchase_item"]:
            target_account_id = data.get("target_account_id")
            if my_id != target_account_id:
                return
            format_and_log("INFO", "Redis 任务匹配成功", {'任务类型': task_type, '详情': str(data)})
            if task_type == "list_item":
                await trade_logic.execute_listing_task(
                    item_to_sell_name=data["item_to_sell_name"], item_to_sell_quantity=data["item_to_sell_quantity"],
                    item_to_buy_name=data["item_to_buy_name"], item_to_buy_quantity=data["item_to_buy_quantity"],
                    requester_id=data["requester_account_id"]
                )
            elif task_type == "purchase_item":
                await trade_logic.execute_purchase_task(item_id=data["item_id"])
    except Exception as e:
        format_and_log("ERROR", "Redis 任务处理器", {'状态': '执行异常', '错误': str(e)})

def initialize(app):
    # 将指令注册回标准的指令系统
    app.register_command("集火", _cmd_focus_fire, help_text="🔥 协同助手上架并购买物品。", category="高级协同", usage=HELP_TEXT_FOCUS_FIRE)
    app.register_command("收货", _cmd_receive_goods, help_text="📦 协同助手接收物品。", category="高级协同", usage=HELP_TEXT_RECEIVE_GOODS)
