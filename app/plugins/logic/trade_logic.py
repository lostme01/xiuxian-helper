# -*- coding: utf-8 -*-
import json
import logging
import re
from app.context import get_application
from app.logger import format_and_log
from app.telegram_client import CommandTimeoutError
from app import redis_client
from config import settings # 引入 settings

# Redis Pub/Sub 频道名称
TASK_CHANNEL = "tg_helper:tasks"


def find_best_account_for_item(item_name: str, required_quantity: int) -> (str, int):
    """
    扫描 Redis 查找拥有指定物品数量最多的助手号（非 admin_user_id）。
    :return: (账户ID, 拥有数量) 或 (None, 0)
    """
    if not redis_client.db:
        return None, 0

    best_account_id = None
    max_quantity = 0
    admin_id = str(settings.ADMIN_USER_ID)

    try:
        for key in redis_client.db.scan_iter("tg_helper:task_states:*"):
            account_id_str = key.split(':')[-1]
            
            if account_id_str == admin_id:
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


def publish_task_to_account(task: dict):
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


async def execute_listing_task(task: dict):
    """由助手号执行的上架任务。"""
    app = get_application()
    item_name = task.get("item_name")
    quantity = task.get("quantity")
    price = task.get("price")
    requester_id = task.get("requester_account_id")

    command = f".上架 {item_name}*{quantity} 换 灵石*{price}"
    format_and_log("TASK", "集火-上架", {'阶段': '开始执行', '指令': command})

    try:
        _sent, reply = await app.client.send_game_command_request_response(command)
        
        match = re.search(r"挂单ID\s*:\s*(\d+)", reply.text)
        
        if "成功" in reply.text and match:
            item_id = match.group(1)
            format_and_log("TASK", "集火-上架", {'阶段': '成功', '物品ID': item_id})
            
            result_task = {
                "task_type": "purchase_item",
                "target_account_id": requester_id,
                "item_id": item_id
            }
            publish_task_to_account(result_task)
        else:
            format_and_log("WARNING", "集火-上架", {'阶段': '失败', '原因': '未解析到ID或成功信息', '回复': reply.text})
    except CommandTimeoutError:
        format_and_log("ERROR", "集火-上架", {'阶段': '失败', '原因': '等待回复超时'}, level=logging.ERROR)
    except Exception as e:
        format_and_log("ERROR", "集火-上架", {'阶段': '异常', '错误': str(e)}, level=logging.ERROR)


async def execute_purchase_task(task: dict):
    """由管理号执行的购买任务。"""
    app = get_application()
    item_id = task.get("item_id")
    command = f".购买 {item_id}"
    format_and_log("TASK", "集火-购买", {'阶段': '开始执行', '指令': command})
    
    try:
        await app.client.send_game_command_fire_and_forget(command)
        await app.client.send_admin_notification(f"✅ **集火成功**：已发送购买指令购买物品 ID `{item_id}`。")
    except Exception as e:
        format_and_log("ERROR", "集火-购买", {'阶段': '异常', '错误': str(e)}, level=logging.ERROR)
        await app.client.send_admin_notification(f"❌ **集火失败**：发送购买指令时发生错误: `{e}`。")

# --- 改造：为 find_best_executor 植入超详细的“黑匣子”日志 ---
def find_best_executor(item_name: str, required_quantity: int, exclude_id: str) -> (str, int):
    """
    在除指定ID外的所有助手中，查找拥有某物品数量最多的账号。
    """
    if not redis_client.db:
        format_and_log("DEBUG", "集火-查找", {'阶段': '中止', '原因': 'Redis未连接'})
        return None, 0

    best_account_id = None
    max_quantity = 0
    format_and_log("DEBUG", "集火-查找", {
        '阶段': '开始扫描',
        '查找物品': item_name,
        '要求数量': required_quantity,
        '排除ID': exclude_id
    })

    try:
        keys_found = list(redis_client.db.scan_iter("tg_helper:task_states:*"))
        format_and_log("DEBUG", "集火-查找", {'阶段': '扫描Redis', '发现Key数量': len(keys_found), 'Keys': str(keys_found)})
        
        for key in keys_found:
            account_id_str = key.split(':')[-1]
            log_context = {'当前检查Key': key, '提取ID': account_id_str}

            if account_id_str == exclude_id:
                log_context['结果'] = '跳过 (是发起者自己)'
                format_and_log("DEBUG", "集火-查找", log_context)
                continue

            inventory_json = redis_client.db.hget(key, "inventory")
            if not inventory_json:
                log_context['结果'] = '跳过 (无库存数据)'
                format_and_log("DEBUG", "集火-查找", log_context)
                continue

            try:
                inventory = json.loads(inventory_json)
                current_quantity = inventory.get(item_name, 0)
                log_context['库存数量'] = current_quantity
                
                if current_quantity >= required_quantity:
                    if current_quantity > max_quantity:
                        log_context['决策'] = f'更新最佳选择 (之前: {max_quantity}, 现在: {current_quantity})'
                        max_quantity = current_quantity
                        best_account_id = account_id_str
                    else:
                        log_context['决策'] = '忽略 (非更优选择)'
                else:
                    log_context['决策'] = f'忽略 (数量 {current_quantity} < 要求 {required_quantity})'
                
                format_and_log("DEBUG", "集火-查找", log_context)

            except json.JSONDecodeError:
                format_and_log("WARNING", "集火-查找", {'阶段': '库存解析失败', 'Key': key, '原始数据': inventory_json[:100]})
                continue
    
    except Exception as e:
        format_and_log("ERROR", "扫描库存时发生严重异常", {'错误': str(e)}, level=logging.ERROR)

    format_and_log("DEBUG", "集火-查找", {'阶段': '扫描结束', '最终选择ID': best_account_id, '最大数量': max_quantity})
    return best_account_id, max_quantity


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
