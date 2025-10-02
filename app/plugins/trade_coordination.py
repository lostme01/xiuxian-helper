# -*- coding: utf-8 -*-
import json
import logging
from app.context import get_application
from .logic import trade_logic
from app.logger import format_and_log
from config import settings

HELP_TEXT_FOCUS_FIRE = """🔥 **集火指令 (v2)**
**说明**: 自动协调其他助手上架指定物品，然后由本机购买。
**用法 1 (换灵石)**: 
  `,集火 <要买的物品> <数量>`
  *示例*: `,集火 金精矿 10`

**用法 2 (以物易物)**:
  `,集火 <要买的物品> <数量> <用于交换的物品> <数量>`
  *示例*: `,集火 百年铁木 2 凝血草 20`
"""

async def _cmd_focus_fire(event, parts):
    """
    [v2版] 处理 ,集火 指令，支持两种交易模式。
    """
    app = get_application()
    client = app.client
    my_id = client.me.id if client.me else "未知"
    
    # --- 核心优化：简化身份判断 ---
    # 集火指令只能由管理员实例（即自身ID等于配置中的admin_user_id）发起。
    if str(my_id) != str(settings.ADMIN_USER_ID):
        return

    format_and_log("INFO", "集火-身份确认", {'结果': '本机为管理员实例，开始执行任务'})
    
    if len(parts) < 3:
        await client.reply_to_admin(event, f"❌ 参数不足！\n\n{HELP_TEXT_FOCUS_FIRE}")
        return

    task_payload = {
        "task_type": "list_item",
        "requester_account_id": str(my_id),
    }

    try:
        if len(parts) == 3:
            task_payload["item_to_sell_name"] = parts[1]
            task_payload["item_to_sell_quantity"] = int(parts[2])
            task_payload["item_to_buy_name"] = "灵石"
            task_payload["item_to_buy_quantity"] = 1
            
        elif len(parts) == 5:
            task_payload["item_to_sell_name"] = parts[1]
            task_payload["item_to_sell_quantity"] = int(parts[2])
            task_payload["item_to_buy_name"] = parts[3]
            task_payload["item_to_buy_quantity"] = int(parts[4])

        else:
            await client.reply_to_admin(event, f"❌ 参数格式错误！\n\n{HELP_TEXT_FOCUS_FIRE}")
            return
            
    except ValueError:
        await client.reply_to_admin(event, f"❌ 参数中的“数量”必须是数字！\n\n{HELP_TEXT_FOCUS_FIRE}")
        return

    item_to_find = task_payload["item_to_sell_name"]
    quantity_to_find = task_payload["item_to_sell_quantity"]

    progress_msg = await client.reply_to_admin(event, f"⏳ `集火任务启动`\n我是发起者，正在扫描其他助手库存查找`{item_to_find}`...")
    client.pin_message(progress_msg)

    best_account_id, _ = await trade_logic.find_best_executor(item_to_find, quantity_to_find, exclude_id=str(my_id))

    if not best_account_id:
        await progress_msg.edit(f"❌ `任务失败`\n未在【任何其他助手】中找到拥有足够数量`{item_to_find}`的账号。")
        client.unpin_message(progress_msg)
        client._schedule_message_deletion(progress_msg, 30, "集火查找失败")
        return

    await progress_msg.edit(f"✅ `已定位助手` (ID: `...{best_account_id[-4:]}`)\n⏳ 正在通过 Redis 下达上架指令...")
    
    task_payload["target_account_id"] = best_account_id
    
    if await trade_logic.publish_task(task_payload):
        await progress_msg.edit(f"✅ `指令已发送`\n等待助手号回报上架结果...")
    else:
        await progress_msg.edit(f"❌ `任务失败`\n任务发布至 Redis 失败，请检查连接。")
        client.unpin_message(progress_msg)
        client._schedule_message_deletion(progress_msg, 30, "集火发布失败")


async def redis_message_handler(message):
    app = get_application()
    my_id = str(app.client.me.id)
    
    try:
        data = json.loads(message['data'])
        target_account_id = data.get("target_account_id")
        task_type = data.get("task_type")

        if my_id != target_account_id:
            return
        
        format_and_log("INFO", "Redis 任务匹配成功", {'任务类型': task_type, '详情': str(data)})

        if task_type == "list_item":
            await trade_logic.execute_listing_task(
                item_to_sell_name=data["item_to_sell_name"],
                item_to_sell_quantity=data["item_to_sell_quantity"],
                item_to_buy_name=data["item_to_buy_name"],
                item_to_buy_quantity=data["item_to_buy_quantity"],
                requester_id=data["requester_account_id"]
            )
        elif task_type == "purchase_item":
            await trade_logic.execute_purchase_task(item_id=data["item_id"])

    except Exception as e:
        format_and_log("ERROR", "Redis 任务处理器", {'状态': '执行异常', '错误': str(e)})


def initialize(app):
    app.register_command("集火", _cmd_focus_fire, help_text="🔥 协同助手上架并购买物品。", category="高级协同", usage=HELP_TEXT_FOCUS_FIRE)
