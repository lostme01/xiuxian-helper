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

async def handle_auto_management_tasks(data):
    app = get_application()
    task_type = data.get("task_type")
    
    if task_type == "execute_game_command" and str(app.client.me.id) == data.get("target_account_id"):
        command = data.get("command")
        if command:
            await app.client.send_game_command_fire_and_forget(command, priority=2)
            return True
            
    return False

def initialize(app):
    if not hasattr(app, 'extra_redis_handlers'): app.extra_redis_handlers = []
    app.extra_redis_handlers.append(handle_auto_management_tasks)
    if settings.AUTO_RESOURCE_MANAGEMENT.get('enabled'):
        interval = settings.AUTO_RESOURCE_MANAGEMENT.get('interval_minutes', 120)
        scheduler.add_job(_execute_resource_management, 'interval', id='auto_resource_management_task', replace_existing=True)
    
    # [核心修改] 移除所有旧的知识共享相关调度
    if scheduler.get_job('auto_knowledge_sharing_task'):
        scheduler.remove_job('auto_knowledge_sharing_task')
    if scheduler.get_job('knowledge_timeout_checker_task'):
        scheduler.remove_job('knowledge_timeout_checker_task')
