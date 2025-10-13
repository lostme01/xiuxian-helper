# -*- coding: utf-8 -*-
import asyncio
import json
import re
import random
from app.context import get_application
from app.data_manager import data_manager
from app.inventory_manager import inventory_manager
from app.logging_service import LogType, format_and_log
from app.plugins.logic import trade_logic
from app.task_scheduler import scheduler
from app.utils import progress_manager
from config import settings
from app import game_adaptor

TASK_ID_AUTO_KNOWLEDGE = 'auto_knowledge_sharing_task'
HELP_TEXT_KNOWLEDGE_SHARING = """🤝 **知识共享 (v3.0 安全版)**
**说明**: [仅限管理员] 手动触发一次安全的知识共享扫描。学生将主动上架求购，老师负责完成交易，杜绝配方被抢的风险。
**用法**: `,知识共享`
"""

async def _execute_knowledge_sharing_logic():
    """
    [v3.0 全新安全逻辑]
    学生上架求购，老师完成交易。
    """
    app = get_application()
    my_id = str(app.client.me.id)
    
    if my_id != str(settings.ADMIN_USER_ID):
        return

    format_and_log(LogType.TASK, "知识共享", {'阶段': '开始扫描 (v3.0)'})

    all_bots_data = {}
    all_known_recipes = set()
    all_keys = await data_manager.get_all_assistant_keys()

    for key in all_keys:
        try:
            account_id = key.split(':')[-1]
            learned_json = await data_manager.db.hget(key, "learned_recipes")
            inv_json = await data_manager.db.hget(key, "inventory")
            learned = set(json.loads(learned_json) if learned_json else [])
            inv = json.loads(inv_json) if inv_json else {}
            all_bots_data[account_id] = {'learned': learned, 'inventory': inv}
            all_known_recipes.update(learned)
        except (json.JSONDecodeError, TypeError):
            continue

    blacklist = set(settings.AUTO_KNOWLEDGE_SHARING.get('blacklist', []))
    
    for student_id, student_data in all_bots_data.items():
        needed_recipes = (all_known_recipes - student_data['learned']) - blacklist
        if not needed_recipes:
            continue
        
        for recipe_item in needed_recipes:
            teacher_id = None
            recipe_to_get = None

            possible_recipe_names = [f"{recipe_item}丹方", f"{recipe_item}图纸"]
            for tid, tdata in all_bots_data.items():
                if tid == student_id: continue
                for name in possible_recipe_names:
                    if tdata['inventory'].get(name, 0) > 0:
                        teacher_id = tid
                        recipe_to_get = name
                        break
                if teacher_id:
                    break
            
            if teacher_id and recipe_to_get:
                format_and_log(LogType.TASK, "知识共享", { 
                    '决策': '派遣求购任务', 
                    '学生': f'...{student_id[-4:]}',
                    '老师': f'...{teacher_id[-4:]}', 
                    '知识': recipe_to_get 
                })
                
                # [核心修改] 任务发给学生，让他去求购
                task = {
                    "task_type": "request_recipe_from_teacher",
                    "target_account_id": student_id,
                    "payload": {
                        "teacher_id": teacher_id,
                        "recipe_to_request": recipe_to_get
                    }
                }
                await trade_logic.publish_task(task)
                await asyncio.sleep(random.uniform(15, 30))
                break 

async def handle_request_recipe_task(app, data):
    """
    [v3.0 新增]
    由“学生”执行，负责上架求购单，并通知“老师”来完成交易。
    """
    payload = data.get("payload", {})
    teacher_id = payload.get("teacher_id")
    recipe_to_request = payload.get("recipe_to_request")
    if not teacher_id or not recipe_to_request:
        return
        
    client = app.client
    format_and_log(LogType.TASK, "知识共享-求购", {'阶段': '开始', '老师': f'...{teacher_id[-4:]}', '物品': recipe_to_request})

    try:
        # 学生上架1灵石，求购配方
        list_command = game_adaptor.list_item("灵石", 1, recipe_to_request, 1)
        _sent, reply = await client.send_game_command_request_response(list_command)

        match = re.search(r"挂单ID\D+(\d+)", reply.text)
        if "上架成功" in reply.text and match:
            listing_id = match.group(1)
            # 通知老师来完成交易
            fulfill_task = {
                "task_type": "fulfill_recipe_request",
                "target_account_id": teacher_id,
                "payload": {"listing_id": listing_id}
            }
            await trade_logic.publish_task(fulfill_task)
            format_and_log(LogType.TASK, "知识共享-求购", {'阶段': '成功', '挂单ID': listing_id, '通知': '已发送给老师'})
        else:
            format_and_log(LogType.ERROR, "知识共享-求购", {'阶段': '失败', '原因': '上架求购单失败', '回复': reply.text})

    except Exception as e:
        format_and_log(LogType.ERROR, "知识共享-求购异常", {'错误': str(e)})


async def handle_fulfill_recipe_request_task(app, data):
    """
    [v3.0 新增]
    由“老师”执行，负责购买“学生”的求购单，完成配方交接。
    """
    payload = data.get("payload", {})
    listing_id = payload.get("listing_id")
    if not listing_id:
        return

    client = app.client
    format_and_log(LogType.TASK, "知识共享-交接", {'阶段': '开始完成交易', '挂单ID': listing_id})

    try:
        # 老师购买学生的求购单
        buy_command = game_adaptor.buy_item(listing_id)
        _sent, reply = await client.send_game_command_request_response(buy_command)

        if "交易成功" in reply.text:
            format_and_log(LogType.TASK, "知识共享-交接", {'阶段': '成功', '挂单ID': listing_id})
        else:
            format_and_log(LogType.ERROR, "知识共享-交接", {'阶段': '失败', '原因': '完成交易失败', '回复': reply.text})
    except Exception as e:
        format_and_log(LogType.ERROR, "知识共享-交接异常", {'错误': str(e)})

async def _cmd_trigger_knowledge_sharing(event, parts):
    app = get_application()
    client = app.client

    if str(client.me.id) != str(settings.ADMIN_USER_ID):
        return
    
    async with progress_manager(event, "⏳ 正在手动触发“知识共享”扫描...") as progress:
        await _execute_knowledge_sharing_logic()
        await progress.update("✅ **知识共享扫描已完成。**\n\n如果发现了可共享的配方，相关教学任务已在后台分派。")

def initialize(app):
    app.register_command(
        name="知识共享",
        handler=_cmd_trigger_knowledge_sharing,
        help_text="🤝 [管理员] 手动触发一次知识共享。",
        category="协同",
        aliases=["共享知识"],
        usage=HELP_TEXT_KNOWLEDGE_SHARING
    )
    
    if settings.AUTO_KNOWLEDGE_SHARING.get('enabled'):
        interval = settings.AUTO_KNOWLEDGE_SHARING.get('interval_minutes', 240)
        scheduler.add_job(_execute_knowledge_sharing_logic, 'interval', minutes=interval, id=TASK_ID_AUTO_KNOWLEDGE, replace_existing=True)
