# -*- coding: utf-8 -*-
import json
import logging
import re
from app.context import get_application
from app.logger import format_and_log
from app.telegram_client import CommandTimeoutError
from app import redis_client
from config import settings

# Redis Pub/Sub 频道名称
TASK_CHANNEL = "tg_helper:tasks"

def get_self_inventory():
    """获取当前账号自己的库存信息"""
    app = get_application()
    if not redis_client.db: return None
    
    key = f"tg_helper:task_states:{app.client.me.id}"
    inventory_json = redis_client.db.hget(key, "inventory")
    if inventory_json:
        return json.loads(inventory_json)
    return {}

def find_best_executor(item_name: str, required_quantity: int, exclude_id: str) -> (str, int):
    """
    在除指定ID外的所有助手中，查找拥有某物品数量最多的账号。
    :param exclude_id: 需要排除的账号ID (通常是发起者自己)
    :return: (账户ID, 拥有数量) 或 (None, 0)
    """
    if not redis_client.db:
        return None, 0

    best_account_id = None
    max_quantity = 0

    try:
        for key in redis_client.db.scan_iter("tg_helper:task_states:*"):
            account_id_str = key.split(':')[-1]
            
            if account_id_str == exclude_id:
                continue

            inventory_json = redis_client.db.hget(key, "inventory")
            if not inventory_json:
                continue

            inventory = json.loads(inventory_json)
            current_quantity = inventory.get(item_name, 0)

            if current_quantity >= required_quantity and current_quantity > max_quantity:
                max_quantity = current_quantity
                best_account_id = account_id_str
    
    except Exception as e:
        format_and_log("ERROR", "扫描库存失败", {'错误': str(e)}, level=logging.ERROR)

    return best_account_id, max_quantity

def publish_task(task: dict):
    """将任务发布到 Redis 频道。"""
    if not redis_client.db:
        format_and_log("ERROR", "任务发布失败", {'原因': 'Redis未连接'}, level=logging.ERROR)
        return False
    try:
        payload = json.dumps(task)
        redis_client.db.publish(TASK_CHANNEL, payload)
        format_and_log("DEBUG", "任务已发布", task)
        return True
    except Exception as e:
        format_and_log("ERROR", "任务发布异常", {'错误': str(e)}, level=logging.ERROR)
        return False

async def execute_listing_task(item_name: str, quantity: int, price: int, requester_id: str):
    """
    执行上架物品的任务流程。
    :return: 成功时返回 True，失败时返回 False
    """
    app = get_application()
    command = f".上架 {item_name}*{quantity} 换 灵石*{price}"
    format_and_log("TASK", "集火-上架", {'阶段': '开始执行', '指令': command})

    try:
        _sent, reply = await app.client.send_game_command_request_response(command)
        
        match = re.search(r"挂单ID\s*:\s*(\d+)", reply.text)
        
        if "成功" in reply.text and match:
            item_id = match.group(1)
            format_and_log("TASK", "集火-上架", {'阶段': '成功', '物品ID': item_id})
            
            # 将结果回报给发起者
            result_task = {
                "task_type": "purchase_item",
                "target_account_id": requester_id,
                "item_id": item_id
            }
            publish_task(result_task)
            return True
        else:
            format_and_log("WARNING", "集火-上架", {'阶段': '失败', '原因': '未解析到ID或成功信息', '回复': reply.text})
            # (可选) 在此通知发起者上架失败
            return False
    except CommandTimeoutError:
        format_and_log("ERROR", "集火-上架", {'阶段': '失败', '原因': '等待回复超时'}, level=logging.ERROR)
        return False
    except Exception as e:
        format_and_log("ERROR", "集火-上架", {'阶段': '异常', '错误': str(e)}, level=logging.ERROR)
        return False

async def execute_purchase_task(item_id: str):
    """执行购买物品的任务流程。"""
    app = get_application()
    command = f".购买 {item_id}"
    format_and_log("TASK", "集火-购买", {'阶段': '开始执行', '指令': command})
    
    try:
        await app.client.send_game_command_fire_and_forget(command)
        await app.client.send_admin_notification(f"✅ **集火成功**：已发送购买指令购买物品 ID `{item_id}`。")
    except Exception as e:
        format_and_log("ERROR", "集火-购买", {'阶段': '异常', '错误': str(e)}, level=logging.ERROR)
        await app.client.send_admin_notification(f"❌ **集火失败**：发送购买指令时发生错误: `{e}`。")

async def logic_debug_inventories() -> str:
    # ... (此函数内容不变)
    app = get_application()
    if not redis_client.db:
        return "❌ 错误: Redis 未连接。"

    admin_id = str(settings.ADMIN_USER_ID)
    output_lines = []
    
    try:
        all_keys = list(redis_client.db.scan_iter("tg_helper:task_states:*"))
        
        if not all_keys:
            output_lines.append("\n**诊断结果: 🔴 失败**\n在 Redis 中没有扫描到任何账户的状态键 (`tg_helper:task_states:*)。")
            output_lines.append("\n**可能原因:**\n1. 所有助手都未能成功连接到 Redis。\n2. Redis 配置错误。")
            return "🔬 **跨账户库存调试**\n\n" + "\n".join(output_lines)

        output_lines.append(f"✅ 在 Redis 中扫描到 **{len(all_keys)}** 个账户状态键。")
        output_lines.append(f"ℹ️ 系统定义的主管理号 (Admin ID) 为: `{admin_id}`")
        output_lines.append("---")

        for key in all_keys:
            account_id_str = key.split(':')[-1]
            is_admin = (account_id_str == admin_id)
            
            line = f"- **{'[管理号]' if is_admin else '[助手号]'}** ID: `{account_id_str}`\n"
            inventory_json = redis_client.db.hget(key, "inventory")
            
            if not inventory_json:
                line += "  - `库存`: ⚠️ **未找到** (请确保此账号已成功执行 `,立即刷新背包`)"
            else:
                try:
                    inventory = json.loads(inventory_json)
                    line += f"  - `库存`: ✅ **已找到** (共 {len(inventory)} 项物品)\n"
                    target_item = "凝血草"
                    if target_item in inventory:
                        line += f"    - **`{target_item}`**: `{inventory[target_item]}`"
                    else:
                        line += f"    - `{target_item}`: (未持有)"
                except Exception as e:
                    line += f"  - `库存`: ❌ **JSON解析失败**! 错误: {e}"
            
            output_lines.append(line)

    except Exception as e:
        return f"❌ 扫描 Redis 时发生严重错误: {e}"
        
    return "🔬 **跨账户库存调试**\n\n" + "\n".join(output_lines)
