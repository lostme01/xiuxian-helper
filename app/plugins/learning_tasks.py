# -*- coding: utf-8 -*-
import logging
import random
import pytz
import asyncio
import inspect
import re
from datetime import datetime, timedelta
from app.utils import read_json_state, write_json_state
from config import settings
from app.logger import format_and_log
from app.task_scheduler import scheduler

client = None
TASK_ID_LEARN_RECIPES = 'learn_recipes_task'
STATE_FILE_PATH_LEARNED = f"{settings.DATA_DIR}/learned_recipes.json"
INVENTORY_FILE_PATH = f"{settings.DATA_DIR}/inventory.json"

def initialize_tasks(tg_client):
    global client
    client = tg_client
    client.register_task("learn_recipes", trigger_learn_recipes)
    return [check_learn_recipes_startup]

async def check_learn_recipes_startup():
    if not settings.TASK_SWITCHES.get('learn_recipes'):
        format_and_log("SYSTEM", "任务跳过", {'任务名': '自动学习图纸', '原因': '配置中已禁用'})
        return
    if not scheduler.get_job(TASK_ID_LEARN_RECIPES):
        hours = random.randint(4, 6)
        minutes = random.randint(0, 59)
        scheduler.add_job(trigger_learn_recipes, 'interval', hours=hours, minutes=minutes, id=TASK_ID_LEARN_RECIPES, 
                          next_run_time=datetime.now(pytz.timezone(settings.TZ)) + timedelta(minutes=5))

# ... 其他任务函数如 _parse_learned_recipes, trigger_learn_recipes 等保持不变 ...
def _parse_learned_recipes(reply_text: str) -> list[str]:
    learned = []
    pattern = re.compile(r'\(来自:\s*([^)]*(?:图纸|丹方))\)')
    for line in reply_text.split('\n'):
        if match := pattern.search(line): learned.append(match.group(1).strip())
    return learned
async def trigger_learn_recipes():
    _sent_msg, reply = await client.send_and_wait(".炼制")
    if not reply: return
    learned_recipes = _parse_learned_recipes(reply.text)
    write_json_state(STATE_FILE_PATH_LEARNED, learned_recipes)
    inventory = read_json_state(INVENTORY_FILE_PATH) or {}
    if not inventory: return
    recipes_to_learn = []
    for item, quantity in inventory.items():
        if quantity > 0 and item.endswith(("图纸", "丹方")):
            if item not in learned_recipes: recipes_to_learn.append(item)
    if not recipes_to_learn: return
    for recipe in recipes_to_learn:
        _learn_sent, learn_reply = await client.send_and_wait(f".学习 {recipe}")
        if learn_reply and ("成功领悟" in learn_reply.text or "早已学会" in learn_reply.text):
            current_inventory = read_json_state(INVENTORY_FILE_PATH) or {}
            if recipe in current_inventory:
                current_inventory[recipe] -= 1
                if current_inventory[recipe] <= 0: del current_inventory[recipe]
                write_json_state(INVENTORY_FILE_PATH, current_inventory)
            current_learned = read_json_state(STATE_FILE_PATH_LEARNED) or []
            if recipe not in current_learned:
                current_learned.append(recipe)
                write_json_state(STATE_FILE_PATH_LEARNED, current_learned)
        elif learn_reply and "没有此物" in learn_reply.text:
            current_inventory = read_json_state(INVENTORY_FILE_PATH) or {}
            if recipe in current_inventory:
                del current_inventory[recipe]
                write_json_state(INVENTORY_FILE_PATH, current_inventory)
        await asyncio.sleep(random.uniform(3, 7))
