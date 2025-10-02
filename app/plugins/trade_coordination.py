# -*- coding: utf-8 -*-
import json
import logging
from app.context import get_application
from .logic import trade_logic
from app.logger import format_and_log
from config import settings

HELP_TEXT_FOCUS_FIRE = """🔥 **集火指令**
**说明**: 由发起者账号在群内发送，该账号对应的助手实例将自动在【其他】助手中查找物品，并协调上架及购买。
**用法**: `,集火 <物品名称> <数量>`
**示例**: `,集火 金精矿 10`
"""

async def _cmd_focus_fire(event, parts):
    """
    处理 ,集火 指令。
    这是最终的、正确的、基于“发送者即发起者”的逻辑。
    """
    app = get_application()
    client = app.client

    # --- 核心改造：最终的身份甄别守卫 ---
    # 检查这条指令消息的发送者ID，是否与当前这个助手实例的ID相同。
    # 只有发送指令的账号所对应的那个助手实例，才有资格成为“发起者”。
    if event.sender_id != client.me.id:
        # 如果当前实例不是发送指令的那个账号，则静默忽略。
        return

    # --- 从这里开始，只有发送指令的那个账号实例会继续执行 ---
    my_id = str(client.me.id)
    
    if len(parts) < 3:
        await client.reply_to_admin(event, f"❌ 参数不足！\n\n{HELP_TEXT_FOCUS_FIRE}")
        return

    try:
        quantity = int(parts[-1])
        item_name = " ".join(parts[1:-1])
    except (ValueError, IndexError):
        await client.reply_to_admin(event, f"❌ 参数格式错误！\n\n{HELP_TEXT_FOCUS_FIRE}")
        return
        
    format_and_log("INFO", "集火-任务启动", {
        '发起者(本机)ID': my_id,
        '指令发送者(确认)': event.sender_id,
        '查找物品': item_name
    })

    progress_msg = await client.reply_to_admin(event, f"⏳ `集火任务启动`\n我是发起者，正在扫描其他助手库存...")
    client.pin_message(progress_msg)

    # 发起者查找时，把自己排除掉，只在其他助手中寻找
    best_account_id, found_quantity = trade_logic.find_best_executor(item_name, quantity, exclude_id=my_id)

    if not best_account_id:
        await progress_msg.edit(f"❌ `任务失败`\n未在【任何其他助手】中找到拥有足够数量`{item_name}`的账号。")
        client.unpin_message(progress_msg)
        client._schedule_message_deletion(progress_msg, 30, "集火查找失败")
        return

    # 分派任务给最佳助手
    await progress_msg.edit(f"✅ `已定位助手` (ID: `...{best_account_id[-4:]}`)\n⏳ 正在通过 Redis 下达上架指令...")
    task = {
        "task_type": "list_item",
        "target_account_id": best_account_id,
        "requester_account_id": my_id, # 回报对象是发起者自己
        "item_name": item_name,
        "quantity": quantity,
        "price": 1 
    }
    
    if trade_logic.publish_task(task):
        await progress_msg.edit(f"✅ `指令已发送`\n等待助手号回报上架结果...")
    else:
        await progress_msg.edit(f"❌ `任务失败`\n任务发布至 Redis 失败，请检查连接。")
        client.unpin_message(progress_msg)
        client._schedule_message_deletion(progress_msg, 30, "集火发布失败")


async def redis_message_handler(message):
    """处理从 Redis Pub/Sub 收到的所有任务"""
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
                item_name=data["item_name"],
                quantity=data["quantity"],
                price=data["price"],
                requester_id=data["requester_account_id"]
            )
        elif task_type == "purchase_item":
            await trade_logic.execute_purchase_task(item_id=data["item_id"])

    except Exception as e:
        format_and_log("ERROR", "Redis 任务处理器", {'状态': '执行异常', '错误': str(e)})


async def _cmd_debug_inventory(event, parts):
    """处理 ,debug库存 指令"""
    app = get_application()
    
    # 同样增加身份甄别，只有发送者自己对应的实例才能执行
    if event.sender_id != app.client.me.id:
        return
        
    result = await trade_logic.logic_debug_inventories()
    await app.client.reply_to_admin(event, result)


def initialize(app):
    app.register_command("集火", _cmd_focus_fire, help_text="🔥 协同助手上架并购买物品。", category="高级协同", usage=HELP_TEXT_FOCUS_FIRE)
    app.register_command("debug库存", _cmd_debug_inventory, help_text="🔬 (调试用)检查所有助手的库存缓存。", category="高级协同")

