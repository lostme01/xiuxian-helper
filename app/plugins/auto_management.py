# -*- coding: utf-8 -*-
import asyncio
import json
import re
import time
import random
from asteval import Interpreter
from app.context import get_application
from app.logging_service import LogType, format_and_log
from config import settings
from app.task_scheduler import scheduler
from app.plugins.logic import trade_logic
from app.telegram_client import CommandTimeoutError
from app import game_adaptor
from app.data_manager import data_manager

KNOWLEDGE_SESSIONS_KEY = "knowledge_sessions"

async def _execute_resource_management():
    app = get_application()
    if not settings.AUTO_RESOURCE_MANAGEMENT.get('enabled') or not data_manager.db or not data_manager.db.is_connected:
        return

    my_id = str(app.client.me.id)
    if my_id != str(settings.ADMIN_USER_ID):
        return

    format_and_log(LogType.TASK, "智能资源管理", {'阶段': '开始检查规则'})
    rules = settings.AUTO_RESOURCE_MANAGEMENT.get('rules', [])
    if not rules:
        return

    all_keys = await data_manager.get_all_assistant_keys()
    for key in all_keys:
        account_id = key.split(':')[-1]
        
        try:
            inv_json = await data_manager.db.hget(key, "inventory")
            # This is not a direct value, need to get from sect_treasury, but for simplicity let's assume it's stored
            treasury_json = await data_manager.db.hget(key, "sect_treasury")
            treasury_data = json.loads(treasury_json) if treasury_json else {}
            contrib = treasury_data.get('contribution', 0)
            inv = json.loads(inv_json) if inv_json else {}
        except (json.JSONDecodeError, TypeError):
            continue

        for rule in rules:
            try:
                check_resource_name = rule.get("check_resource")
                action_item_name = rule.get("item")
                
                resource_value = 0
                if check_resource_name == "contribution":
                    resource_value = contrib
                elif check_resource_name:
                    resource_value = inv.get(check_resource_name, 0)

                aeval = Interpreter(usersyms={"resource": resource_value})
                condition_met = aeval.eval(rule.get('condition', 'False'))
                
                if condition_met:
                    action = rule.get("action")
                    amount = rule.get("amount")
                    
                    if not action_item_name:
                        format_and_log(LogType.ERROR, "智能资源管理", {'阶段': '规则跳过', '原因': '规则缺少 "item" 字段'})
                        continue

                    command = None
                    if action == "donate":
                        command = game_adaptor.sect_donate(action_item_name, amount)
                    elif action == "exchange":
                        command = game_adaptor.sect_exchange(action_item_name, amount)
                    
                    if command:
                        task = {"task_type": "execute_game_command", "target_account_id": account_id, "command": command}
                        await trade_logic.publish_task(task)
                        format_and_log(LogType.TASK, "智能资源管理", {'决策': f'执行{action}', '账户': f'...{account_id[-4:]}', '指令': command})
                        await asyncio.sleep(random.uniform(5, 10))
                        break 
            except Exception as e:
                format_and_log(LogType.ERROR, "智能资源管理", {'阶段': '规则执行异常', '规则': str(rule), '错误': str(e)})


async def _execute_knowledge_sharing():
    app = get_application()
    if not settings.AUTO_KNOWLEDGE_SHARING.get('enabled') or not data_manager.db or not data_manager.db.is_connected:
        return

    my_id = str(app.client.me.id)
    if my_id != str(settings.ADMIN_USER_ID):
        return

    format_and_log(LogType.TASK, "知识共享", {'阶段': '开始扫描'})

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
        
        for recipe in needed_recipes:
            teacher_id = None
            for tid, tdata in all_bots_data.items():
                if tid != student_id and recipe in tdata['learned'] and tdata['inventory'].get(recipe, 0) > 0:
                    teacher_id = tid
                    break
            
            if teacher_id:
                format_and_log(LogType.TASK, "知识共享", { '决策': '发送共享提议', '学生': f'...{student_id[-4:]}', '知识': recipe })
                # [核心修复] 发送“提议”任务，而不是直接命令
                task = {
                    "task_type": "propose_knowledge_share",
                    "target_account_id": student_id,
                    "payload": {
                        "recipe_name": recipe,
                        "teacher_id": teacher_id
                    }
                }
                await trade_logic.publish_task(task)
                await asyncio.sleep(random.uniform(10, 20))


async def _check_knowledge_session_timeouts():
    if not data_manager.db or not data_manager.db.is_connected: return
    if await data_manager.db.exists(KNOWLEDGE_SESSIONS_KEY):
        sessions = await data_manager.db.hgetall(KNOWLEDGE_SESSIONS_KEY)
        if not sessions: await data_manager.db.delete(KNOWLEDGE_SESSIONS_KEY); return
        now = time.time()
        for session_id, session_json in sessions.items():
            try:
                session_data = json.loads(session_json)
                if now - session_data.get("timestamp", 0) > 300:
                    format_and_log(LogType.TASK, "知识共享-超时检查", {'状态': '清理过时会话', '会话ID': session_id})
                    await data_manager.db.hdel(KNOWLEDGE_SESSIONS_KEY, session_id)
            except Exception:
                await data_manager.db.hdel(KNOWLEDGE_SESSIONS_KEY, session_id)


async def handle_auto_management_tasks(data):
    app = get_application()
    task_type = data.get("task_type")
    
    if task_type == "execute_game_command" and str(app.client.me.id) == data.get("target_account_id"):
        command = data.get("command")
        if command:
            # --- [核心修改] 为后台任务的指令设置低优先级 ---
            format_and_log(LogType.DEBUG, "后台任务执行", {'指令': command, '优先级': '低 (2)'})
            await app.client.send_game_command_fire_and_forget(command, priority=2)
            return True
            
    return False

def initialize(app):
    if not hasattr(app, 'extra_redis_handlers'): app.extra_redis_handlers = []
    app.extra_redis_handlers.append(handle_auto_management_tasks)
    if settings.AUTO_RESOURCE_MANAGEMENT.get('enabled'):
        interval = settings.AUTO_RESOURCE_MANAGEMENT.get('interval_minutes', 120)
        scheduler.add_job(_execute_resource_management, 'interval', minutes=interval, id='auto_resource_management_task', replace_existing=True)
    if settings.AUTO_KNOWLEDGE_SHARING.get('enabled'):
        interval = settings.AUTO_KNOWLEDGE_SHARING.get('interval_minutes', 240)
        scheduler.add_job(_execute_knowledge_sharing, 'interval', minutes=interval, id='auto_knowledge_sharing_task', replace_existing=True)
        scheduler.add_job(_check_knowledge_session_timeouts, 'interval', minutes=5, id='knowledge_timeout_checker_task', replace_existing=True)
