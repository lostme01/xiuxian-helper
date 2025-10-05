# -*- coding: utf-8 -*-
import asyncio
import json
import re
from asteval import Interpreter
from app.context import get_application
from app.logger import format_and_log
from config import settings
from app.task_scheduler import scheduler
from app.plugins.logic import trade_logic
from app.telegram_client import CommandTimeoutError

# --- 智能资源管理逻辑 ---
async def _execute_resource_management():
    if not settings.AUTO_RESOURCE_MANAGEMENT.get('enabled'):
        return

    app = get_application()
    my_id = str(app.client.me.id)
    
    # 该任务只应在主控账号上运行以避免重复决策
    if my_id != str(settings.ADMIN_USER_ID):
        return

    format_and_log("TASK", "智能资源管理", {'阶段': '开始检查规则'})
    
    rules = settings.AUTO_RESOURCE_MANAGEMENT.get('rules', [])
    if not rules:
        return

    # 获取所有助手的当前状态
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
                
                # 创建一个安全的表达式求值器
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


# --- 自动化知识共享逻辑 ---
async def _execute_knowledge_sharing():
    if not settings.AUTO_KNOWLEDGE_SHARING.get('enabled'):
        return

    app = get_application()
    my_id = str(app.client.me.id)
    
    if my_id != str(settings.ADMIN_USER_ID):
        return

    format_and_log("TASK", "知识共享", {'阶段': '开始扫描'})

    # 1. 收集全网信息
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
    
    # 2. 寻找学习机会
    for student_id, student_data in all_bots_data.items():
        needed_recipes = (all_known_recipes - student_data['learned']) - blacklist
        
        if not needed_recipes:
            continue
            
        format_and_log("DEBUG", "知识共享", {'发现需求': f'账户 ...{student_id[-4:]} 需要 {len(needed_recipes)} 个配方'})

        for recipe in needed_recipes:
            # 3. 寻找老师
            teacher_id = None
            for tid, tdata in all_bots_data.items():
                if tid == student_id: continue
                if recipe in tdata['learned'] and tdata['inventory'].get(recipe, 0) > 0:
                    teacher_id = tid
                    break
            
            # 4. 发起求学交易
            if teacher_id:
                format_and_log("TASK", "知识共享", {
                    '决策': '发起知识转移',
                    '学生': f'...{student_id[-4:]}',
                    '老师': f'...{teacher_id[-4:]}',
                    '知识': recipe
                })
                task = {
                    "task_type": "initiate_p2p_receive", 
                    "target_account_id": student_id,
                    "payload": {
                        "item_name": recipe,
                        "quantity": 1,
                        "executor_id": teacher_id
                    }
                }
                await trade_logic.publish_task(task)
                return

# --- Redis 任务处理器扩展 ---
async def handle_auto_management_tasks(data):
    app = get_application()
    task_type = data.get("task_type")
    payload = data.get("payload", {})
    
    if task_type == "execute_game_command":
        command = data.get("command")
        if command:
            await app.client.send_game_command_fire_and_forget(command)
            return True
            
    if task_type == "initiate_p2p_receive":
        try:
            item_name = payload["item_name"]
            quantity = payload["quantity"]
            executor_id = payload["executor_id"]
            
            list_command = f".上架 灵石*1 换 {item_name}*{quantity}"
            _sent, reply = await app.client.send_game_command_request_response(list_command)
            
            match = re.search(r"挂单ID\D+(\d+)", reply.text)
            if "上架成功" in reply.text and match:
                item_id = match.group(1)
                await app.inventory_manager.remove_item("灵石", 1)
                
                purchase_task_payload = {
                    "item_id": item_id,
                    "cost": {"name": item_name, "quantity": quantity}
                }
                purchase_task = {
                    "task_type": "purchase_item", 
                    "target_account_id": executor_id, 
                    "payload": purchase_task_payload
                }
                await trade_logic.publish_task(purchase_task)
            else:
                raise RuntimeError(f"上架失败: {reply.text}")
        except Exception as e:
            await app.client.send_admin_notification(f"❌ 自动化知识共享失败: {e}")
        return True
    
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
