# -*- coding: utf-8 -*-
import logging
import random
import pytz
import asyncio
import re
from datetime import datetime, timedelta
from config import settings
from app.logger import format_and_log
from app.utils import read_json_state, write_json_state, parse_inventory_text
from app.task_scheduler import scheduler

client = None
TASK_ID_GARDEN = 'huangfeng_garden_task'
TASK_ID_INVENTORY_REFRESH = 'inventory_refresh_task'
INVENTORY_FILE_PATH = f"{settings.DATA_DIR}/inventory.json"
GARDEN_STATUS_KEYWORDS = ['空闲', '已成熟', '灵气干涸', '害虫侵扰', '杂草横生', '生长中']

def initialize_tasks(tg_client):
    global client
    client = tg_client
    client.register_task('xiaoyaoyuan', trigger_garden_check)
    client.register_task('update_inventory', update_inventory_cache)
    return [check_garden_startup, check_inventory_refresh_startup]

async def check_garden_startup():
    if not settings.TASK_SWITCHES.get('garden_check'):
        format_and_log("SYSTEM", "任务跳过", {'任务名': '自动药园', '原因': '配置中已禁用'})
        return
    if not scheduler.get_job(TASK_ID_GARDEN):
        minutes = random.randint(30, 60)
        scheduler.add_job(trigger_garden_check, 'interval', minutes=minutes, id=TASK_ID_GARDEN, 
                          next_run_time=datetime.now(pytz.timezone(settings.TZ)) + timedelta(minutes=1))

async def check_inventory_refresh_startup():
    if not settings.TASK_SWITCHES.get('inventory_refresh'):
        format_and_log("SYSTEM", "任务跳过", {'任务名': '自动刷新背包', '原因': '配置中已禁用'})
        return
    if not scheduler.get_job(TASK_ID_INVENTORY_REFRESH):
        scheduler.add_job(update_inventory_cache, 'interval', hours=6, jitter=3600, id=TASK_ID_INVENTORY_REFRESH)

# ... 其他任务函数如 _parse_garden_status, trigger_garden_check 等保持不变 ...
def _parse_garden_status(reply_text: str) -> dict:
    garden_status = {}
    pattern = re.compile(r'\**(\d+)\s*号灵田\**\s*[:：\s]\s*(.+)')
    for line in reply_text.split('\n'):
        if match := pattern.search(line):
            plot_id = int(match.group(1))
            details = match.group(2).strip()
            status = next((s for s in GARDEN_STATUS_KEYWORDS if s in details), '未知')
            garden_status[plot_id] = status
    return garden_status
async def _handle_garden_problems(status: dict) -> dict | None:
    commands = {'已成熟': ".采药", '灵气干涸': ".浇水", '害虫侵扰': ".除虫", '杂草横生': ".除草"}
    for st, cmd in commands.items():
        if st in set(status.values()):
            await client.send_command(cmd)
            await asyncio.sleep(random.uniform(5, 15))
    await asyncio.sleep(random.uniform(20, 30))
    _sent, reply = await client.send_and_wait(".小药园")
    return _parse_garden_status(reply.text) if reply else None
def _find_seed_to_sow(inventory: dict) -> str | None:
    preferred = settings.GARDEN_SOW_SEED
    if preferred and inventory.get(preferred, 0) > 0: return preferred
    for item, quantity in inventory.items():
        if "种子" in item and quantity > 0: return item
    return None
async def _sow_seeds(garden_status: dict):
    sow_plots = [pid for pid, s in garden_status.items() if s == '空闲']
    if not sow_plots: return
    inventory = read_json_state(INVENTORY_FILE_PATH) or {}
    if not inventory: return
    for plot_id in sow_plots:
        seed = _find_seed_to_sow(inventory)
        if not seed: break
        _sent, reply = await client.send_and_wait(f".播种 {plot_id} {seed}")
        if reply and "成功" in reply.text:
            inventory[seed] = inventory.get(seed, 1) - 1
            write_json_state(INVENTORY_FILE_PATH, inventory)
async def trigger_garden_check():
    _sent_msg, reply = await client.send_and_wait(".小药园")
    if not reply: return
    garden_status = _parse_garden_status(reply.text)
    if not garden_status: return
    if any(s in garden_status.values() for s in ['已成熟', '灵气干涸', '害虫侵扰', '杂草横生']):
        garden_status = await _handle_garden_problems(garden_status)
        if not garden_status: return
    await _sow_seeds(garden_status)
async def update_inventory_cache():
    _sent, reply = await client.send_and_wait(".储物袋")
    if reply and (inventory := parse_inventory_text(reply.text)):
        write_json_state(INVENTORY_FILE_PATH, inventory)
