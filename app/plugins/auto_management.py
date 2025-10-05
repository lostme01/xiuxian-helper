# -*- coding: utf-8 -*-
import asyncio
import json
import re
import time
from asteval import Interpreter
from app.context import get_application
from app.logger import format_and_log
from config import settings
from app.task_scheduler import scheduler
from app.plugins.logic import trade_logic
from app.telegram_client import CommandTimeoutError

# [重构] 知识共享任务状态的 Redis Key
KNOWLEDGE_SESSIONS_KEY = "knowledge_sessions"


# --- 智能资源管理逻辑 (保持不变) ---
async def _execute_resource_management():
    if not settings.AUTO_RESOURCE_MANAGEMENT.get('enabled'):
        return

    app = get_application()
    my_id = str(app.client.me.id)
    
    if my_id != str(settings.ADMIN_USER_ID):
        return

    format_and_log("TASK", "智能资源管理", {'阶段': '开始检查规则'})
    
    rules = settings.AUTO_RESOURCE_MANAGEMENT.get('rules', [])
    if not rules:
        return

    all_states = {}
    keys_found = [key async for key in app.redis_db.scan_iter("tg_helper:task_states:*")]
    for key in keys_found:
        account_id = key.split(':')[-1]
        all_states[account_id] = await app.redis_db.hgetall(key)

    for account_id, state in all_states.items():
        inv = json.loads(state.get("inventory", "{}"))
        treasury = json.loads(state.get("sect_treasury", "{}"))
        contrib = treasury.get("contribution", 0)

        for rule in rules:
            try:
                item_name = rule.get("item")
                item_count = inv.get(item_name, 0)
                
                aeval = Interpreter(usersyms={"contribution": contrib, "item": item_count})
                
                condition_met = False
                if 'condition' in rule:
                    condition_met = aeval.eval(rule['condition'])
                elif 'threshold' in rule:
                    condition_met = item_count > rule['threshold']
                
                if condition_met:
                    action = rule.get("action")
                    amount = rule.get("amount")
                    
                    if action == "donate":
                        if isinstance(amount, int):
                            command = f".宗门捐献 {item_name} {amount}"
                            task = {"task_type": "execute_game_command", "target_account_id": account_id, "command": command}
                            await trade_logic.publish_task(task)
                            format_and_log("TASK", "智能资源管理", {'决策': '执行捐献', '账户': f'...{account_id[-4:]}', '指令': command})
                            break 

                    elif action == "exchange":
                        if isinstance(amount, int):
                            command = f".兑换 {item_name} {amount}"
                            task = {"task_type": "execute_game_command", "target_account_id": account_id, "command": command}
                            await trade_logic.publish_task(task)
                            format_and_log("TASK", "智能资源管理", {'决策': '执行兑换', '账户': f'...{account_id[-4:]}', '指令': command})
                            break
            except Exception as e:
                format_and_log("ERROR", "智能资源管理", {'阶段': '规则执行异常', '规则': str(rule), '错误': str(e)})


# --- 自动化知识共享逻辑 (V2.0 - 事件驱动 & 状态机) ---
async def _execute_knowledge_sharing():
    if not settings.AUTO_KNOWLEDGE_SHARING.get('enabled'):
        return

    app = get_application()
    my_id = str(app.client.me.id)
    
    if my_id != str(settings.ADMIN_USER_ID):
        return

    # [重构] 检查是否有正在进行的知识共享任务，如果有，则本次跳过，避免并发
    if await app.redis_db.hlen(KNOWLEDGE_SESSIONS_KEY) > 0:
        format_and_log("TASK", "知识共享", {'阶段': '跳过', '原因': '已有正在进行的任务'})
        return

    format_and_log("TASK", "知识共享", {'阶段': '开始扫描'})

    all_bots_data = {}
    all_known_recipes = set()
    keys_found = [key async for key in app.redis_db.scan_iter("tg_helper:task_states:*")]

    for key in keys_found:
        account_id = key.split(':')[-1]
        state = await app.redis_db.hgetall(key)
        learned = set(json.loads(state.get("learned_recipes", "[]")))
        inv = json.loads(state.get("inventory", "{}"))
        
        all_bots_data[account_id] = {'learned': learned, 'inventory': inv}
        all_known_recipes.update(learned)

    blacklist = set(settings.AUTO_KNOWLEDGE_SHARING.get('blacklist', []))
    
    for student_id, student_data in all_bots_data.items():
        needed_recipes = (all_known_recipes - student_data['learned']) - blacklist
        
        if not needed_recipes:
            continue
            
        format_and_log("DEBUG", "知识共享", {'发现需求': f'账户 ...{student_id[-4:]} 需要 {len(needed_recipes)} 个配方'})

        for recipe in needed_recipes:
            teacher_id = None
            for tid, tdata in all_bots_data.items():
                if tid == student_id: continue
                if recipe in tdata['learned'] and tdata['inventory'].get(recipe, 0) > 0:
                    teacher_id = tid
                    break
            
            if teacher_id:
                format_and_log("TASK", "知识共享", {
                    '决策': '发起知识转移',
                    '学生': f'...{student_id[-4:]}',
                    '老师': f'...{teacher_id[-4:]}',
                    '知识': recipe
                })
                # [重构] 只向学生发布“发起请求”的任务，而不是直接撮合交易
                task = {
                    "task_type": "initiate_knowledge_request", 
                    "target_account_id": student_id,
                    "payload": {
                        "item_name": recipe,
                        "quantity": 1
                    }
                }
                await trade_logic.publish_task(task)
                # 每次只处理一个，避免并发冲突
                return


async def _check_knowledge_session_timeouts():
    """[新功能] 定时检查超时的知识共享任务"""
    app = get_application()
    if not app.redis_db: return

    sessions = await app.redis_db.hgetall(KNOWLEDGE_SESSIONS_KEY)
    now = time.time()
    for session_id, session_json in sessions.items():
        try:
            session_data = json.loads(session_json)
            # 超时设置为 5 分钟
            if now - session_data.get("timestamp", 0) > 300:
                format_and_log("TASK", "知识共享-超时检查", {'状态': '发现超时任务', '会话ID': session_id})
                cancel_task = {
                    "task_type": "cancel_knowledge_request",
                    "target_account_id": session_data["student_id"],
                    "payload": session_data
                }
                await trade_logic.publish_task(cancel_task)
                # 从 Redis 中删除，避免重复处理
                await app.redis_db.hdel(KNOWLEDGE_SESSIONS_KEY, session_id)
        except Exception as e:
            format_and_log("ERROR", "知识共享-超时检查", {'状态': '处理异常', '会话ID': session_id, '错误': str(e)})


# --- Redis 任务处理器扩展 ---
async def handle_auto_management_tasks(data):
    app = get_application()
    task_type = data.get("task_type")
    
    if task_type == "execute_game_command":
        command = data.get("command")
        if command:
            await app.client.send_game_command_fire_and_forget(command)
            return True
            
    # [重构] 移除旧的 initiate_p2p_receive 处理器逻辑
    
    return False

# --- 调度器与初始化 ---
def initialize(app):
    if not hasattr(app, 'extra_redis_handlers'):
        app.extra_redis_handlers = []
    app.extra_redis_handlers.append(handle_auto_management_tasks)

    if settings.AUTO_RESOURCE_MANAGEMENT.get('enabled'):
        interval = settings.AUTO_RESOURCE_MANAGEMENT.get('interval_minutes', 120)
        scheduler.add_job(
            _execute_resource_management, 
            'interval', 
            minutes=interval, 
            id='auto_resource_management_task',
            replace_existing=True
        )
    
    if settings.AUTO_KNOWLEDGE_SHARING.get('enabled'):
        interval = settings.AUTO_KNOWLEDGE_SHARING.get('interval_minutes', 240)
        scheduler.add_job(
            _execute_knowledge_sharing, 
            'interval', 
            minutes=interval, 
            id='auto_knowledge_sharing_task',
            replace_existing=True
        )
        # [新功能] 添加超时检查任务，每分钟运行一次
        scheduler.add_job(
            _check_knowledge_session_timeouts,
            'interval',
            minutes=1,
            id='knowledge_timeout_checker_task',
            replace_existing=True
        )
