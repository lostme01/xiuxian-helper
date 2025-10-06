# -*- coding: utf-8 -*-
import logging
import random
import pytz
import asyncio
import re
from datetime import datetime, timedelta
from config import settings
from app.logger import format_and_log
from app.task_scheduler import scheduler
from app.telegram_client import CommandTimeoutError
from app.context import get_application
from app.utils import resilient_task
from app import game_adaptor
from app.data_manager import data_manager
from app.inventory_manager import inventory_manager

TASK_ID_LEARN_RECIPES = 'learn_recipes_task'
STATE_KEY_LEARNED = "learned_recipes"

@resilient_task()
async def trigger_learn_recipes(force_run=False):
    app = get_application()
    client = app.client
    format_and_log("TASK", "自动学习", {'阶段': '任务开始', '强制执行': force_run})

    # --- 第一阶段：同步与构建权威知识库 ---
    
    # 1. 获取游戏快照
    _sent_msg, reply = await client.send_game_command_request_response(game_adaptor.get_crafting_list())
    
    # 2. 严格解析
    learned_from_command = re.findall(r'\(来自:\s*([^)]*(?:图纸|丹方))\)', reply.text)
    
    # 3. 加载历史记录
    cached_learned = await data_manager.get_value(STATE_KEY_LEARNED, is_json=True, default=[])
    
    # 4. 合并与持久化
    current_learned_set = set(learned_from_command + cached_learned)
    await data_manager.save_value(STATE_KEY_LEARNED, sorted(list(current_learned_set)))
    
    format_and_log("TASK", "自动学习", {'阶段': '同步权威知识库', '当前已知配方总数': len(current_learned_set)})
    
    # --- 第二阶段：决策 ---

    inventory = await inventory_manager.get_inventory()
    if not inventory:
        format_and_log("TASK", "自动学习", {'阶段': '任务跳过', '原因': '背包缓存为空'})
        return
    
    recipes_to_learn = [item for item in inventory if item.endswith(("图纸", "丹方")) and item not in current_learned_set]
    
    if not recipes_to_learn:
        format_and_log("TASK", "自动学习", {'阶段': '任务完成', '详情': '没有需要新学习的图纸或丹方。'})
        return
        
    format_and_log("TASK", "自动学习", {'阶段': '开始学习', '待学列表': str(recipes_to_learn)})

    # --- 第三阶段：执行与即时记录 ---

    jitter_config = settings.TASK_JITTER['learn_recipes']
    newly_learned_in_session = False
    
    for recipe in recipes_to_learn:
        try:
            format_and_log("TASK", "自动学习", {'阶段': '发送学习指令', '物品': recipe})
            command = game_adaptor.learn_recipe(recipe)
            _sent_learn, reply_learn = await client.send_game_command_request_response(command, timeout=10)
            
            # 严格判断是否学习成功
            if "成功领悟了它的炼制之法" in reply_learn.text:
                format_and_log("TASK", "自动学习-知识库更新", {'阶段': '学习成功', '物品': recipe})
                current_learned_set.add(recipe)
                newly_learned_in_session = True
            
            # 对于其他所有返回（包括因游戏bug导致的伪成功），我们不做任何记录，
            # 这样在下一次运行时，如果该配方出现在.炼制列表中，它会被自动同步；
            # 如果没出现，我们也不会因为错误的反馈而污染我们的知识库。
            else:
                 format_and_log("WARNING", "自动学习", {'阶段': '学习未成功或已学会', '物品': recipe, '返回': reply_learn.text.strip()})

        except CommandTimeoutError:
            format_and_log("TASK", "自动学习", {'阶段': '学习超时', '物品': recipe}, level=logging.WARNING)
            continue
        finally:
            delay = random.uniform(jitter_config['min'], jitter_config['max'])
            await asyncio.sleep(delay)
    
    # 如果在本次会话中有任何新学习成功的配方，则在任务结束时，将最终的知识库再次持久化
    if newly_learned_in_session:
        await data_manager.save_value(STATE_KEY_LEARNED, sorted(list(current_learned_set)))
        format_and_log("TASK", "自动学习", {'阶段': '任务完成', '详情': '已将新学配方持久化至知识库。'})
    else:
        format_and_log("TASK", "自动学习", {'阶段': '任务完成', '详情': '所有可学物品均已尝试，无新配方学会。'})


async def check_learn_recipes_startup():
    if settings.TASK_SWITCHES.get('learn_recipes'):
        scheduler.add_job(
            trigger_learn_recipes, 'interval', hours=random.randint(4, 6), 
            id=TASK_ID_LEARN_RECIPES, 
            next_run_time=datetime.now(pytz.timezone(settings.TZ)) + timedelta(minutes=5),
            replace_existing=True
        )

def initialize(app):
    app.register_task(
        task_key="learn_recipes",
        function=trigger_learn_recipes,
        command_name="立即学习",
        help_text="立即检查并学习背包中的图纸和丹方。"
    )
    app.startup_checks.append(check_learn_recipes_startup)
