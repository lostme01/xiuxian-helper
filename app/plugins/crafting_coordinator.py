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

HELP_TEXT_CRAFT_GATHER = """🛠️ **协同炼制 (P2P收菜)**
**说明**: 由当前账号发起，自动规划并集齐网络中所有助手号的材料来炼制指定物品。
**用法**: `,炼制 <物品名称>`
**示例**: `,炼制 风雷翅`
"""

async def _cmd_craft_gather(event, parts):
    app = get_application()
    client = app.client
    my_id = str(client.me.id)
    my_username = client.me.username or my_id
    
    if len(parts) < 2:
        await client.reply_to_admin(event, f"❌ 参数不足！\n\n{HELP_TEXT_CRAFT_GATHER}")
        return
        
    item_to_craft = " ".join(parts[1:])
    
    progress_msg = await client.reply_to_admin(event, f"⏳ `[{my_username}] 收菜任务启动`\n正在规划“{item_to_craft}”的材料收集计划...")
    client.pin_message(progress_msg)
    
    try:
        plan = await crafting_logic.logic_plan_crafting_session(item_to_craft, my_id)
        
        if isinstance(plan, str):
            raise RuntimeError(plan)

        if not plan:
            await progress_msg.edit(f"ℹ️ **无需收集**: 网络中没有其他助手需要为此任务贡献材料。")
            client.unpin_message(progress_msg)
            return
            
        report_lines = [f"✅ **规划完成，开始合并上架**:"]
        
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
                        "item_id": listing_id
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
        error_text = create_error_reply("炼制", "任务失败", details=str(e))
        await progress_msg.edit(error_text)
    finally:
        client.unpin_message(progress_msg)


def initialize(app):
    app.register_command("炼制", _cmd_craft_gather, help_text="🛠️ 协同助手凑材料炼制物品。", category="协同", usage=HELP_TEXT_CRAFT_GATHER)
