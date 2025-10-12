# -*- coding: utf-8 -*-
import asyncio
import json
import re
import time

from app import game_adaptor
from app.constants import CRAFTING_SESSIONS_KEY, STATE_KEY_LEARNED_RECIPES
from app.context import get_application
from app.inventory_manager import inventory_manager
from app.logging_service import LogType, format_and_log
from app.plugins.logic import crafting_logic, trade_logic
from app.plugins.common_tasks import update_inventory_cache
from app.utils import create_error_reply, parse_item_and_quantity, progress_manager


HELP_TEXT_SMART_CRAFT = """✨ **智能炼制 (v2.2)**
**说明**: 自动检查配方学习状态、收集材料并炼制物品。
**用法**: `,智能炼制 <物品名称> [数量]`
**示例**: `,智能炼制 增元丹 2`
"""

HELP_TEXT_GATHER_MATERIALS = """📦 **收集材料 (v2.2)**
**说明**: 自动检查配方学习状态并协同收集材料，但不执行最终的炼制步骤。
**用法**: `,收集材料 <物品名称> [数量]`
**示例**: `,收集材料 增元丹 2`
"""

async def _try_auto_learn(item_name: str, progress) -> bool:
    """
    一个独立的、纯粹的自动学习函数。
    返回 True 表示学习成功或已学，返回 False 表示失败且任务应中止。
    """
    app = get_application()
    client = app.client

    await progress.update(f"⚠️ **前置检查**: 您尚未学习 **{item_name}**\n正在尝试自动学习...")
    
    inventory = await inventory_manager.get_inventory()
    recipe_name = next((name for name in [f"{item_name}丹方", f"{item_name}图纸"] if name in inventory), None)

    if not recipe_name:
        await progress.update(f"❌ **任务中止**: 您尚未学习该配方，且背包中未找到对应的丹方/图纸。")
        return False

    await progress.update(f"✅ **发现配方**: `{recipe_name}`\n正在发送学习指令...")
    learn_command = game_adaptor.learn_recipe(recipe_name)
    _sent_learn, reply_learn = await client.send_game_command_request_response(learn_command)

    if "成功领悟了它的炼制之法" in reply_learn.text:
        learned_recipes = await app.data_manager.get_value(STATE_KEY_LEARNED_RECIPES, is_json=True, default=[])
        # [核心修复] 使用正确的变量名 item_name
        learned_recipes.append(item_name)
        await app.data_manager.save_value(STATE_KEY_LEARNED_RECIPES, learned_recipes)
        await progress.update(f"✅ **学习成功!**\n前置检查通过，继续执行...")
        return True
    elif f"你的储物袋中没有【{recipe_name}】" in reply_learn.text:
        await progress.update(f"⚠️ **学习失败**: 缓存与实际背包不符。\n正在自动校准背包缓存...")
        await update_inventory_cache(force_run=True)
        await progress.update(f"❌ **任务中止**: 背包已校准，请您再次尝试。")
        return False
    else:
        await progress.update(f"❌ **任务中止**: 学习失败。\n\n**游戏回复**:\n`{reply_learn.text}`")
        return False


async def _execute_coordinated_crafting(event, parts, synthesize_after: bool):
    app = get_application()
    client = app.client
    my_id = str(client.me.id)
    cmd_name = "智能炼制" if synthesize_after else "收集材料"
    usage_text = HELP_TEXT_SMART_CRAFT if synthesize_after else HELP_TEXT_GATHER_MATERIALS

    item_to_craft, quantity, error = parse_item_and_quantity(parts)
    if error:
        await client.reply_to_admin(event, create_error_reply(cmd_name, error, usage_text=usage_text))
        return

    async with progress_manager(event, f"🧠 **{cmd_name}任务: {item_to_craft} x{quantity}**\n正在进行前置检查...") as progress:
        session_id = f"craft_{my_id}_{int(time.time())}"
        try:
            learned_recipes = await app.data_manager.get_value(STATE_KEY_LEARNED_RECIPES, is_json=True, default=[])
            if item_to_craft not in learned_recipes:
                if not await _try_auto_learn(item_to_craft, progress):
                    return

            await progress.update(f"✅ **前置检查通过**\n正在检查本地库存...")
            
            missing_locally = await crafting_logic.logic_check_local_materials(item_to_craft, quantity)
            if isinstance(missing_locally, str):
                raise ValueError(missing_locally)

            if not missing_locally:
                if synthesize_after:
                    await progress.update(f"✅ **本地材料充足**\n正在为您执行炼制操作...")
                    await crafting_logic.logic_execute_crafting(item_to_craft, quantity, progress.update)
                else:
                    await progress.update(f"✅ **本地材料充足**\n无需从网络收集材料。")
                return

            await progress.update(f"⚠️ **本地材料不足**\n- 缺失: `{json.dumps(missing_locally, ensure_ascii=False)}`\n正在规划P2P材料收集...")
            plan = await crafting_logic.logic_plan_crafting_session(missing_locally, my_id)
            if isinstance(plan, str): raise RuntimeError(plan)

            if not plan:
                await progress.update(f"ℹ️ **网络中亦无足够材料**\n无法完成材料收集。")
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
                    await progress.update("\n".join(report_lines) + f"\n- 正在上架交易...")
                    
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
                    await progress.update("\n".join(report_lines))
                    await app.redis_db.hset(CRAFTING_SESSIONS_KEY, session_id, json.dumps(session_data))

            if plan_failed:
                await app.redis_db.hdel(CRAFTING_SESSIONS_KEY, session_id)
                final_text = "\n".join(report_lines) + f"\n\n❌ **任务中止**: {failure_reason}"
                await progress.update(final_text)
                return

            final_action = "将自动炼制" if synthesize_after else "任务将结束"
            final_text = "\n".join(report_lines) + f"\n\n⏳ **所有收集任务已分派，等待材料全部送达后{final_action}...**"
            await progress.update(final_text)

        except Exception as e:
            if 'session_id' in locals() and app.redis_db and await app.redis_db.exists(CRAFTING_SESSIONS_KEY):
                await app.redis_db.hdel(CRAFTING_SESSIONS_KEY, session_id)
            raise e

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
        name="收集材料",
        handler=_cmd_gather_materials,
        help_text="📦 自动检查并收集材料，但不炼制。",
        category="协同",
        aliases=["凑材料"],
        usage=HELP_TEXT_GATHER_MATERIALS
    )
