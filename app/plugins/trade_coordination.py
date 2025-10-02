# -*- coding: utf-8 -*-
import json
import logging
from app.context import get_application
from app.utils import require_args
from .logic import trade_logic
from app.logger import format_and_log # 引入日志工具

HELP_TEXT_FOCUS_FIRE = """🔥 **集火指令**
**说明**: 在所有助手中查找指定物品，并让存量最多的助手上架，然后由管理号购买。
**用法**: `,集火 <物品名称> <数量>`
**示例**: `,集火 金精矿 10`
**注意**: 如果物品名称带空格，无需加引号，例如: `,集火 百年铁木 1`
"""

async def _cmd_focus_fire(event, parts):
    """处理 ,集火 指令，智能解析带空格的物品名称"""
    app = get_application()
    
    if len(parts) < 3:
        await app.client.reply_to_admin(event, f"❌ 参数不足！\n\n{HELP_TEXT_FOCUS_FIRE}")
        return

    try:
        quantity_str = parts[-1]
        quantity = int(quantity_str)
        item_name = " ".join(parts[1:-1])
    except (ValueError, IndexError):
        await app.client.reply_to_admin(event, f"❌ 参数格式错误！\n\n{HELP_TEXT_FOCUS_FIRE}")
        return

    progress_msg = await app.client.reply_to_admin(event, f"⏳ 正在查找拥有`{item_name}` x{quantity}的库存...")
    app.client.pin_message(progress_msg)

    best_account_id, found_quantity = trade_logic.find_best_account_for_item(item_name, quantity)

    if not best_account_id:
        await progress_msg.edit(f"❌ 未找到任何拥有足够数量`{item_name}`的助手账号。")
        app.client.unpin_message(progress_msg)
        app.client._schedule_message_deletion(progress_msg, 30, "集火查找失败")
        return

    await progress_msg.edit(f"✅ 已定位最佳账号 (ID: `...{best_account_id[-4:]}`)，拥有 `{found_quantity}` 个。\n⏳ 正在下达上架指令...")

    task = {
        "task_type": "list_item",
        "target_account_id": best_account_id,
        "requester_account_id": str(app.client.me.id),
        "item_name": item_name,
        "quantity": quantity,
        "price": 1 
    }
    
    if trade_logic.publish_task_to_account(task):
        await progress_msg.edit(f"✅ 上架指令已发送，等待助手号回报...")
    else:
        await progress_msg.edit(f"❌ 任务发布失败，请检查 Redis 连接。")


# --- 改造：为任务处理器添加详细日志 ---
async def redis_message_handler(message):
    """处理从 Redis Pub/Sub 收到的消息"""
    app = get_application()
    my_id = str(app.client.me.id)
    
    try:
        data = json.loads(message['data'])
        task_type = data.get("task_type")
        target_account_id = data.get("target_account_id")

        log_data = {
            '本机ID': my_id,
            '目标ID': target_account_id,
            '任务类型': task_type
        }
        format_and_log("DEBUG", "Redis 任务处理器", log_data)

        # 检查任务是否是发给自己的
        if my_id != target_account_id:
            return

        # 如果ID匹配，则执行任务
        format_and_log("INFO", "Redis 任务匹配成功", {'任务类型': task_type, '详情': str(data)})
        if task_type == "list_item":
            await trade_logic.execute_listing_task(data)
        elif task_type == "purchase_item":
            await trade_logic.execute_purchase_task(data)

    except (json.JSONDecodeError, KeyError):
        format_and_log("WARNING", "Redis 任务处理器", {'状态': '忽略无效消息', '原始数据': str(message.get('data'))})
    except Exception as e:
        format_and_log("ERROR", "Redis 任务处理器", {'状态': '执行异常', '错误': str(e)})


async def _cmd_debug_inventory(event, parts):
    """处理 ,debug库存 指令"""
    app = get_application()
    result = await trade_logic.logic_debug_inventories()
    await app.client.reply_to_admin(event, result)


def initialize(app):
    app.register_command("集火", _cmd_focus_fire, help_text="🔥 协同助手上架并购买物品。", category="高级协同", usage=HELP_TEXT_FOCUS_FIRE)
    app.register_command("debug库存", _cmd_debug_inventory, help_text="🔬 (调试用)检查所有助手的库存缓存。", category="高级协同")

