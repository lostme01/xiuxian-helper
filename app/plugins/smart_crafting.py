# -*- coding: utf-8 -*-
import json
import re
import time
import asyncio

from app import game_adaptor
from app.constants import CRAFTING_SESSIONS_KEY
from app.context import get_application
from app.logging_service import LogType, format_and_log
from app.plugins.logic import crafting_logic, trade_logic
from app.utils import create_error_reply, parse_item_and_quantity
from app.plugins.common_tasks import update_inventory_cache

HELP_TEXT_SMART_CRAFT = """✨ **智能炼制 (v3.2 - 指令修正版)**
**说明**: 修复了当需要向其他助手收集材料时，生成的`.上架`指令格式错误的BUG。
**用法**: `,智能炼制 <物品名称> [数量]`
**示例**: `,智能炼制 增元丹 2`
"""

HELP_TEXT_GATHER_MATERIALS = """📦 **凑材料 (v3.2 - 指令修正版)**
**说明**: 修复了当需要向其他助手收集材料时，生成的`.上架`指令格式错误的BUG。
**用法**: `,凑材料 <物品名称> [数量]`
**示例**: `,凑材料 增元丹 2`
"""

async def _execute_coordinated_crafting(event, parts, synthesize_after: bool):
    """核心逻辑，处理智能炼制和凑材料两个指令。"""
    app = get_application()
    client = app.client
    my_id = str(client.me.id)
    cmd_name = "智能炼制" if synthesize_after else "凑材料"
    usage_text = HELP_TEXT_SMART_CRAFT if synthesize_after else HELP_TEXT_GATHER_MATERIALS

    item_to_craft, quantity, error = parse_item_and_quantity(parts)
    if error:
        await client.reply_to_admin(event, create_error_reply(cmd_name, error, usage_text=usage_text))
        return

    progress_message = await client.reply_to_admin(event, f"🧠 **{cmd_name}任务: {item_to_craft} x{quantity}**\n正在检查本地库存...")
    if not progress_message: return
    client.pin_message(progress_message)

    session_id = f"craft_{my_id}_{int(time.time())}" # 在 try 块外部定义
    try:
        missing_locally = await crafting_logic.logic_check_local_materials(item_to_craft, quantity)
        if isinstance(missing_locally, str):
            raise ValueError(missing_locally)

        if not missing_locally:
            if synthesize_after:
                await progress_message.edit(f"✅ **本地材料充足**\n正在为您执行炼制操作...")
                from .crafting_actions import _cmd_craft_item as execute_craft_item
                craft_parts = ["炼制物品", item_to_craft, str(quantity)]
                await execute_craft_item(event, craft_parts)
            else:
                await progress_message.edit(f"✅ **本地材料充足**\n无需从网络收集材料。")
            return

        await progress_message.edit(f"⚠️ **本地材料不足**\n- 缺失: `{json.dumps(missing_locally, ensure_ascii=False)}`\n正在规划P2P材料收集...")
        plan = await crafting_logic.logic_plan_crafting_session(missing_locally, my_id)
        if isinstance(plan, str): raise RuntimeError(plan)

        if not plan:
            await progress_message.edit(f"ℹ️ **网络中亦无足够材料**\n无法完成材料收集。")
            return

        session_data = {
            "item": item_to_craft, "quantity": quantity, "status": "gathering",
            "synthesize": synthesize_after, "needed_from": {executor_id: False for executor_id in plan.keys()},
            "timestamp": time.time()
        }
        await app.redis_db.hset(CRAFTING_SESSIONS_KEY, session_id, json.dumps(session_data))

        report_lines = [f"✅ **规划完成 (会话ID: `{session_id[-6:]}`)**:"]
        
        plan_failed = False
        failure_reason = ""

        for executor_id, materials in plan.items():
            materials_str = " ".join([f"{name}*{count}" for name, count in materials.items()])
            report_lines.append(f"\n向 `...{executor_id[-4:]}` 收取: `{materials_str}`")

            try:
                await progress_message.edit("\n".join(report_lines) + f"\n- 正在上架交易...")
                
                # [核心修复] 直接、精确地拼接指令字符串，不再使用 game_adaptor.list_item
                sell_item_name = "灵石"
                sell_item_quantity = 1
                list_command = f".上架 {sell_item_name}*{sell_item_quantity} 换 {materials_str}"
                
                _sent, reply = await client.send_game_command_request_response(list_command)

                match = re.search(r"挂单ID\D+(\d+)", reply.text)
                if "上架成功" in reply.text and match:
                    listing_id = match.group(1)
                    report_lines[-1] += f" -> 挂单ID: `{listing_id}` (已通知)"
                    task = {"task_type": "purchase_item", "target_account_id": executor_id, "payload": {"item_id": listing_id, "cost": {"name": "灵石", "quantity": 1}, "crafting_session_id": session_id}}
                    await trade_logic.publish_task(task)
                else:
                    report_lines[-1] += f" -> ❌ **上架失败**"
                    session_data["needed_from"][executor_id] = "failed"
                    plan_failed = True
                    failure_reason = f"为 `{materials_str}` 上架失败。"
                    break
            except Exception as e:
                report_lines[-1] += f" -> ❌ **上架异常**: `{e}`"
                session_data["needed_from"][executor_id] = "failed"
                plan_failed = True
                failure_reason = f"为 `{materials_str}` 上架时发生异常: {e}"
                break
            finally:
                 await progress_message.edit("\n".join(report_lines))
                 await app.redis_db.hset(CRAFTING_SESSIONS_KEY, session_id, json.dumps(session_data))

        if plan_failed:
            await app.redis_db.hdel(CRAFTING_SESSIONS_KEY, session_id)
            final_text = "\n".join(report_lines) + f"\n\n❌ **任务中止**: {failure_reason}"
            await progress_message.edit(final_text)
            return

        final_action = "将自动炼制" if synthesize_after else "任务将结束"
        final_text = "\n".join(report_lines) + f"\n\n⏳ **所有收集任务已分派，等待材料全部送达后{final_action}...**"
        await progress_message.edit(final_text)

    except Exception as e:
        if 'session_id' in locals() and app.redis_db and await app.redis_db.exists(CRAFTING_SESSIONS_KEY):
            await app.redis_db.hdel(CRAFTING_SESSIONS_KEY, session_id)
        error_text = create_error_reply(cmd_name, "任务失败", details=str(e))
        await progress_message.edit(error_text)
    finally:
        client.unpin_message(progress_msg)

async def _cmd_smart_craft(event, parts):
    await _execute_coordinated_crafting(event, parts, synthesize_after=True)

async def _cmd_gather_materials(event, parts):
    await _execute_coordinated_crafting(event, parts, synthesize_after=False)

def initialize(app):
    app.register_command(
        name="智能炼制",
        handler=_cmd_smart_craft,
        help_text="✨ 自动检查、收集并炼制物品。",
        category="协同",
        usage=HELP_TEXT_SMART_CRAFT
    )
    app.register_command(
        name="凑材料",
        handler=_cmd_gather_materials,
        help_text="📦 自动检查并收集材料，但不执行最终炼制。",
        category="协同",
        usage=HELP_TEXT_GATHER_MATERIALS
    )
