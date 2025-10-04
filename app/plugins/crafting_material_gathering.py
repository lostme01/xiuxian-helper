# -*- coding: utf-8 -*-
import json
import re
import asyncio
import random
from telethon import events
from app.context import get_application
from .logic import crafting_logic, trade_logic
from app.logger import format_and_log
from config import settings
from app.telegram_client import CommandTimeoutError
from app.utils import create_error_reply

HELP_TEXT_GATHER_MATERIALS = """🛠️ **炼制集材 (材料收集)**
**说明**: 作为材料收集任务的发起者，从所有其他助手中规划并集齐材料。
**用法**: `,炼制集材 <物品名称> [数量]`
**示例**: `,炼制集材 风雷翅`
"""

async def _internal_gather_materials(event, item_to_craft: str, quantity: int):
    """
    [内部函数] 这是材料收集的核心逻辑，不包含任何权限检查。
    接受明确的物品和数量参数。
    """
    app = get_application()
    client = app.client
    my_id = str(client.me.id)
    my_username = client.me.username or my_id
    
    progress_msg = await client.reply_to_admin(event, f"⏳ `[{my_username}] 材料收集中...`\n正在规划“{item_to_craft}” x{quantity} 的收集计划...")
    client.pin_message(progress_msg)
    
    try:
        plan = await crafting_logic.logic_plan_crafting_session(item_to_craft, my_id, quantity)
        
        if isinstance(plan, str):
            raise RuntimeError(plan)

        if not plan:
            await progress_msg.edit(f"ℹ️ **无需收集**: 网络中没有其他助手需要为此任务贡献材料。")
            client.unpin_message(progress_msg)
            return
            
        report_lines = [f"✅ **规划完成，开始分派收集任务**:"]
        
        for executor_id, materials in plan.items():
            materials_str = " ".join([f"{name}*{count}" for name, count in materials.items()])
            report_lines.append(f"\n向 `...{executor_id[-4:]}` 收取: `{materials_str}`")
            
            try:
                await progress_msg.edit("\n".join(report_lines) + f"\n- 正在上架交易...")
                
                list_command = f".上架 灵石*1 换 {materials_str}"
                _sent, reply = await client.send_game_command_request_response(list_command)
                
                match = re.search(r"挂单ID\D+(\d+)", reply.raw_text)
                if "上架成功" in reply.raw_text and match:
                    listing_id = match.group(1)
                    report_lines[-1] += f" -> 挂单ID: `{listing_id}` (已通知)"
                    await progress_msg.edit("\n".join(report_lines))
                    
                    task = {
                        "task_type": "purchase_item",
                        "target_account_id": executor_id,
                        "payload": { "item_id": listing_id, "cost": { "name": "灵石", "quantity": 1 } }
                    }
                    await trade_logic.publish_task(task)
                    await asyncio.sleep(random.uniform(3, 5))
                else:
                    report_lines[-1] += f" -> ❌ **上架失败**"
                    await progress_msg.edit("\n".join(report_lines))
            
            except Exception as e:
                report_lines[-1] += f" -> ❌ **上架异常**: `{e}`"
                await progress_msg.edit("\n".join(report_lines))
                continue
        
        await progress_msg.edit("\n".join(report_lines) + "\n\n✅ **所有材料收集任务已分派完毕！**")

    except Exception as e:
        error_text = create_error_reply("炼制集材", "任务失败", details=str(e))
        await progress_msg.edit(error_text)
    finally:
        client.unpin_message(progress_msg)

async def _cmd_gather_materials(event, parts):
    """
    [指令处理器] 这是面向用户的指令入口，负责解析 parts 并调用内部函数。
    权限检查已移至 group_control.py。
    """
    item_to_craft = ""
    quantity = 1
    if len(parts) > 2 and parts[-1].isdigit():
        try:
            quantity = int(parts[-1])
            item_to_craft = " ".join(parts[1:-1])
        except (ValueError, IndexError):
            item_to_craft = " ".join(parts[1:])
    else:
        item_to_craft = " ".join(parts[1:])
    
    await _internal_gather_materials(event, item_to_craft, quantity)


def initialize(app):
    app.register_command("炼制集材", _cmd_gather_materials, help_text="🛠️ 协同助手凑材料炼制物品。", category="协同", usage=HELP_TEXT_GATHER_MATERIALS)

