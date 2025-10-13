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
KNOWLEDGE_LOCK_PREFIX = "knowledge_sharing:lock:"
HELP_TEXT_KNOWLEDGE_SHARING = """🤝 **知识共享 (v4.0 最终版)**
**说明**: [仅限管理员] 手动触发一次安全的知识共享扫描。引入任务锁机制，杜绝重复交易；实现闭环流程，确保学生购买后立即学习。
**用法**: `,知识共享`
"""

async def _execute_knowledge_sharing_logic():
    """
    [v4.0 最终修复版]
    引入Redis任务锁，并实现“老师通知 -> 学生学习”的闭环。
    """
    app = get_application()
    my_id = str(app.client.me.id)
    db = app.redis_db
    
    if my_id != str(settings.ADMIN_USER_ID) or not db:
        return

    format_and_log(LogType.TASK, "知识共享", {'阶段': '开始扫描 (v4.0)'})

    all_bots_data = {}
    all_known_recipes = set()
    all_keys = await data_manager.get_all_assistant_keys()

    for key in all_keys:
        try:
            account_id = key.split(':')[-1]
            learned_json = await db.hget(key, "learned_recipes")
            inv_json = await db.hget(key, "inventory")
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
            # 1. 检查任务锁
            lock_key = f"{KNOWLEDGE_LOCK_PREFIX}{student_id}:{recipe_item}"
            if await db.exists(lock_key):
                format_and_log(LogType.DEBUG, "知识共享", {'状态': '跳过', '原因': '任务正在进行中', '锁': lock_key})
                continue

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
                # 2. 设置任务锁，有效期5分钟
                await db.set(lock_key, teacher_id, ex=300)
                format_and_log(LogType.TASK, "知识共享", { 
                    '决策': '派遣求购任务', '学生': f'...{student_id[-4:]}',
                    '老师': f'...{teacher_id[-4:]}', '知识': recipe_to_get 
                })
                
                task = {
                    "task_type": "request_recipe_from_teacher",
                    "target_account_id": student_id,
                    "payload": {
                        "teacher_id": teacher_id,
                        "recipe_to_request": recipe_to_get,
                        "lock_key": lock_key
                    }
                }
                await trade_logic.publish_task(task)
                await asyncio.sleep(random.uniform(15, 30))
                break 

async def handle_request_recipe_task(app, data):
    payload = data.get("payload", {})
    teacher_id = payload.get("teacher_id")
    recipe_to_request = payload.get("recipe_to_request")
    lock_key = payload.get("lock_key")
    if not all([teacher_id, recipe_to_request, lock_key]):
        return
        
    client = app.client
    format_and_log(LogType.TASK, "知识共享-求购", {'阶段': '开始', '物品': recipe_to_request})

    try:
        list_command = game_adaptor.list_item("灵石", 1, recipe_to_request, 1)
        _sent, reply = await client.send_game_command_request_response(list_command)

        match = re.search(r"挂单ID\D+(\d+)", reply.text)
        if "上架成功" in reply.text and match:
            listing_id = match.group(1)
            fulfill_task = {
                "task_type": "fulfill_recipe_request",
                "target_account_id": teacher_id,
                "payload": {
                    "listing_id": listing_id,
                    "student_id": str(client.me.id),
                    "recipe_name": recipe_to_request,
                    "lock_key": lock_key
                }
            }
            await trade_logic.publish_task(fulfill_task)
            format_and_log(LogType.TASK, "知识共享-求购", {'阶段': '成功', '挂单ID': listing_id})
        else:
            format_and_log(LogType.ERROR, "知识共享-求购", {'阶段': '失败', '原因': '上架失败', '回复': reply.text})
            await app.redis_db.delete(lock_key) # 上架失败，释放锁

    except Exception as e:
        format_and_log(LogType.ERROR, "知识共享-求购异常", {'错误': str(e)})
        await app.redis_db.delete(lock_key) # 异常，释放锁

async def handle_fulfill_recipe_request_task(app, data):
    payload = data.get("payload", {})
    listing_id = payload.get("listing_id")
    student_id = payload.get("student_id")
    recipe_name = payload.get("recipe_name")
    lock_key = payload.get("lock_key")
    if not all([listing_id, student_id, recipe_name, lock_key]):
        return

    client = app.client
    format_and_log(LogType.TASK, "知识共享-交接", {'阶段': '开始', '挂单ID': listing_id})

    try:
        buy_command = game_adaptor.buy_item(listing_id)
        _sent, reply = await client.send_game_command_request_response(buy_command)

        if "交易成功" in reply.text:
            # [核心修复] 交易成功后，通知学生去学习
            learn_task = {
                "task_type": "learn_recipe_after_trade",
                "target_account_id": student_id,
                "payload": {"recipe_name": recipe_name, "lock_key": lock_key}
            }
            await trade_logic.publish_task(learn_task)
            format_and_log(LogType.TASK, "知识共享-交接", {'阶段': '成功，已通知学生学习', '挂单ID': listing_id})
        else:
            format_and_log(LogType.ERROR, "知识共享-交接", {'阶段': '失败', '回复': reply.text})
            await app.redis_db.delete(lock_key) # 交易失败，释放锁
    except Exception as e:
        format_and_log(LogType.ERROR, "知识共享-交接异常", {'错误': str(e)})
        await app.redis_db.delete(lock_key) # 异常，释放锁

async def handle_learn_recipe_task(app, data):
    """[v4.0 新增] 由学生执行，在交易成功后自动学习"""
    payload = data.get("payload", {})
    recipe_name = payload.get("recipe_name")
    lock_key = payload.get("lock_key")
    if not recipe_name:
        return

    client = app.client
    format_and_log(LogType.TASK, "知识共享-学习", {'阶段': '开始', '物品': recipe_name})

    try:
        # 等待几秒，确保游戏事件已更新背包缓存
        await asyncio.sleep(5) 
        
        learn_command = game_adaptor.learn_recipe(recipe_name)
        _sent, reply = await client.send_game_command_request_response(learn_command)

        if "成功领悟了它的炼制之法" in reply.text:
            format_and_log(LogType.TASK, "知识共享-学习", {'阶段': '成功', '物品': recipe_name})
        else:
            format_and_log(LogType.WARNING, "知识共享-学习", {'阶段': '失败或已学会', '回复': reply.text})
    except Exception as e:
        format_and_log(LogType.ERROR, "知识共享-学习异常", {'错误': str(e)})
    finally:
        # 无论成功失败，都释放锁
        if lock_key:
            await app.redis_db.delete(lock_key)


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
