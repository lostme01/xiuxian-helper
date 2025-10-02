# -*- coding: utf-8 -*-
import logging
import random
import pytz
import asyncio
import re
from datetime import datetime, timedelta
from app.state_manager import get_state, set_state
from config import settings
from app.logger import format_and_log
from app.task_scheduler import scheduler
from app.telegram_client import CommandTimeoutError
from app.context import get_application

TASK_ID_LEARN_RECIPES = 'learn_recipes_task'
STATE_KEY_LEARNED = "learned_recipes"
STATE_KEY_INVENTORY = "inventory"

async def trigger_learn_recipes(force_run=False):
    client = get_application().client
    format_and_log("TASK", "自动学习", {'阶段': '任务开始', '强制执行': force_run})

    try:
        _sent_msg, reply = await client.send_game_command_request_response(".炼制")
    except CommandTimeoutError:
        format_and_log("TASK", "自动学习", {'阶段': '任务失败', '原因': '获取已学列表超时'}, level=logging.ERROR)
        return
    
    learned_recipes = re.findall(r'\(来自:\s*([^)]*(?:图纸|丹方))\)', reply.raw_text)
    await set_state(STATE_KEY_LEARNED, learned_recipes)
    format_and_log("TASK", "自动学习", {'阶段': '解析已学列表', '数量': len(learned_recipes), '列表': str(learned_recipes)})
    
    inventory = await get_state(STATE_KEY_INVENTORY, is_json=True, default={})
    if not inventory:
        format_and_log("TASK", "自动学习", {'阶段': '任务跳过', '原因': '背包缓存为空'})
        return
    
    recipes_to_learn = [item for item in inventory if item.endswith(("图纸", "丹方")) and item not in learned_recipes]
    
    if not recipes_to_learn:
        format_and_log("TASK", "自动学习", {'阶段': '任务完成', '详情': '没有需要新学习的图纸或丹方。'})
        return
        
    format_and_log("TASK", "自动学习", {'阶段': '开始学习', '待学列表': str(recipes_to_learn)})

    jitter_config = settings.TASK_JITTER['learn_recipes']
    for recipe in recipes_to_learn:
        try:
            format_and_log("TASK", "自动学习", {'阶段': '发送学习指令', '物品': recipe})
            await client.send_game_command_request_response(f".学习 {recipe}", timeout=10)
        except CommandTimeoutError:
            format_and_log("TASK", "自动学习", {'阶段': '学习失败', '原因': '等待回复超时', '物品': recipe}, level=logging.WARNING)
            continue
        finally:
            delay = random.uniform(jitter_config['min'], jitter_config['max'])
            await asyncio.sleep(delay)
    
    format_and_log("TASK", "自动学习", {'阶段': '任务完成', '详情': '所有可学物品均已尝试。'})

async def check_learn_recipes_startup():
    if settings.TASK_SWITCHES.get('learn_recipes') and not scheduler.get_job(TASK_ID_LEARN_RECIPES):
        scheduler.add_job(
            trigger_learn_recipes, 
            'interval', 
            hours=random.randint(4, 6), 
            id=TASK_ID_LEARN_RECIPES, 
            next_run_time=datetime.now(pytz.timezone(settings.TZ)) + timedelta(minutes=5)
        )

def initialize(app):
    app.register_task(
        task_key="learn_recipes",
        function=trigger_learn_recipes,
        command_name="立即学习",
        help_text="立即检查并学习背包中的图纸和丹方。"
    )
    app.startup_checks.append(check_learn_recipes_startup)
