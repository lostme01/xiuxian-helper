# -*- coding: utf-8 -*-
import json
import asyncio
import time
import re
from telethon.errors.rpcerrorlist import MessageEditTimeExpiredError
from app.context import get_application
from app.utils import create_error_reply
from app.inventory_manager import inventory_manager
from app.plugins.logic import crafting_logic, trade_logic
from app.plugins.crafting_actions import _cmd_craft_item as execute_craft_item

HELP_TEXT_SMART_CRAFT = """✨ **智能炼制 (全自动版)**
**说明**: 终极一键指令。自动检查材料，如果不足，则自动向其他助手收集，材料收齐后将自动执行最终的炼制操作。
**用法**: `,智能炼制 <物品名称> [数量]`
**示例**: `,智能炼制 增元丹 2`
"""

async def _cmd_smart_craft(event, parts):
    app = get_application()
    client = app.client
    my_id = str(client.me.id)
    
    if len(parts) < 2:
        await client.reply_to_admin(event, create_error_reply("智能炼制", "参数不足", usage_text=HELP_TEXT_SMART_CRAFT))
        return

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

    
    progress_message = await client.reply_to_admin(event, f"🧠 **智能炼制任务启动: {item_to_craft} x{quantity}**\n正在检查本地库存...")
    if not progress_message: return
    client.pin_message(progress_message)

    try:
        # 检查本地材料是否足够
        required_materials = await crafting_logic.logic_check_local_materials(item_to_craft, quantity)
        if isinstance(required_materials, str): # 如果返回的是错误字符串
            raise ValueError(required_materials)

        if not required_materials:
            await progress_message.edit(f"✅ **本地材料充足**\n正在为您执行炼制操作...")
            craft_parts = ["炼制物品", item_to_craft, str(quantity)]
            await execute_craft_item(event, craft_parts)
            return 

        # --- 材料不足，启动全自动收集与炼制流程 ---
        await progress_message.edit(f"⚠️ **本地材料不足**\n正在启动P2P协同，规划材料收集...")
        
        # 1. 制定收集计划
        plan = await crafting_logic.logic_plan_crafting_session(item_to_craft, my_id, quantity)
        if isinstance(plan, str): raise RuntimeError(plan)
        if not plan:
            await progress_message.edit(f"ℹ️ **无需收集**: 网络中没有其他助手需要为此任务贡献材料。")
            client.unpin_message(progress_message)
            return

        # 2. 创建一个炼制会话
        session_id = f"craft_{my_id}_{int(time.time())}"
        session_data = {
            "item": item_to_craft, "quantity": quantity, "status": "gathering",
            "needed_from": {executor_id: False for executor_id in plan.keys()},
            "timestamp": time.time()  # [新功能] 添加时间戳用于超时判断
        }
        await app.redis_db.hset("crafting_sessions", session_id, json.dumps(session_data))
        
        # 3. 分派任务
        report_lines = [f"✅ **规划完成 (会话ID: `{session_id[-6:]}`)**:"]
        for executor_id, materials in plan.items():
            materials_str = " ".join([f"{name}*{count}" for name, count in materials.items()])
            report_lines.append(f"\n向 `...{executor_id[-4:]}` 收取: `{materials_str}`")
            
            try:
                await progress_message.edit("\n".join(report_lines) + f"\n- 正在上架交易...")
                
                list_command = f".上架 灵石*1 换 {materials_str}"
                _sent, reply = await client.send_game_command_request_response(list_command)
                
                match = re.search(r"挂单ID\D+(\d+)", reply.text)
                if "上架成功" in reply.text and match:
                    listing_id = match.group(1)
                    report_lines[-1] += f" -> 挂单ID: `{listing_id}` (已通知)"
                    
                    task = {
                        "task_type": "purchase_item", "target_account_id": executor_id,
                        "payload": { 
                            "item_id": listing_id, "cost": { "name": "灵石", "quantity": 1 },
                            "crafting_session_id": session_id
                        }
                    }
                    await trade_logic.publish_task(task)
                else:
                    report_lines[-1] += f" -> ❌ **上架失败**"
                    session_data["needed_from"][executor_id] = "failed"
            except Exception as e:
                report_lines[-1] += f" -> ❌ **上架异常**: `{e}`"
                session_data["needed_from"][executor_id] = "failed"
            
            await progress_message.edit("\n".join(report_lines))
            await app.redis_db.hset("crafting_sessions", session_id, json.dumps(session_data))

        final_text = "\n".join(report_lines) + "\n\n⏳ **所有收集任务已分派，等待材料全部送达后将自动炼制...**"
        await progress_message.edit(final_text)

    except Exception as e:
        error_text = create_error_reply("智能炼制", "任务失败", details=str(e))
        await progress_message.edit(error_text)
        client.unpin_message(progress_message)

def initialize(app):
    app.register_command(
        name="智能炼制", handler=_cmd_smart_craft, help_text="✨ 自动检查、收集并炼制物品。", category="协同", usage=HELP_TEXT_SMART_CRAFT
    )
