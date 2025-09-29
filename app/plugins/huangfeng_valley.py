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
# --- 核心修复：从 context 导入，而不是 core ---
from app.context import get_application

INVENTORY_FILE_PATH = f"{settings.DATA_DIR}/inventory.json"
GARDEN_STATUS_KEYWORDS = ['空闲', '已成熟', '灵气干涸', '害虫侵扰', '杂草横生', '生长中']
TASK_ID_GARDEN = 'huangfeng_garden_task'

def initialize_tasks():
    app = get_application()
    app.client.register_task('xiaoyaoyuan', trigger_garden_check)
    return [check_garden_startup]

async def check_garden_startup():
    if not settings.TASK_SWITCHES.get('garden_check'): return
    if not scheduler.get_job(TASK_ID_GARDEN):
        minutes = random.randint(30, 60)
        scheduler.add_job(trigger_garden_check, 'interval', minutes=minutes, id=TASK_ID_GARDEN, 
                          next_run_time=datetime.now(pytz.timezone(settings.TZ)) + timedelta(minutes=1))

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

async def _handle_garden_problems(client, status: dict) -> dict | None:
    unique_statuses = set(status.values())
    commands_to_run = {st: cmd for st, cmd in {'已成熟': ".采药", '灵气干涸': ".浇水", '害虫侵扰': ".除虫", '杂草横生': ".除草"}.items() if st in unique_statuses}
    
    if commands_to_run:
        format_and_log("TASK", "任务进度", {'任务名': '小药园检查', '详情': f"发现问题: {', '.join(commands_to_run.keys())}。开始处理..."})
        for st, cmd in commands_to_run.items():
            await client.send_command(cmd)
            await asyncio.sleep(random.uniform(5, 15))
    
    await asyncio.sleep(random.uniform(20, 30))
    _sent, reply = await client.send_and_wait(".小药园")
    if not reply:
        format_and_log("TASK", "任务失败", {'任务名': '小药园检查', '原因': '处理问题后二次检查超时'}, level=logging.WARNING)
        return None
    return _parse_garden_status(reply.text)

def _find_seed_to_sow(inventory: dict) -> str | None:
    preferred = settings.HUANGFENG_VALLEY_CONFIG.get('garden_sow_seed')
    if preferred and inventory.get(preferred, 0) > 0:
        return preferred
    for item, quantity in inventory.items():
        if "种子" in item and quantity > 0:
            return item
    return None

async def _sow_seeds(client, garden_status: dict):
    sow_plots = [pid for pid, s in garden_status.items() if s == '空闲']
    if not sow_plots: return

    inventory = read_json_state(INVENTORY_FILE_PATH) or {}
    if not inventory: return
    
    seed_to_sow_initial = _find_seed_to_sow(inventory)
    if not seed_to_sow_initial:
        format_and_log("TASK", "任务进度", {'任务名': '播种', '详情': '背包中没有可用种子，终止播种'})
        return
        
    for plot_id in sow_plots:
        current_inventory = read_json_state(INVENTORY_FILE_PATH) or {}
        seed_to_sow = _find_seed_to_sow(current_inventory)
        if not seed_to_sow:
            format_and_log("TASK", "任务进度", {'任务名': '播种', '详情': '种子已用完，终止播种'})
            break
        
        _sent, reply = await client.send_and_wait(f".播种 {plot_id} {seed_to_sow}")
        if reply and "成功" in reply.text:
            current_inventory[seed_to_sow] = current_inventory.get(seed_to_sow, 1) - 1
            if current_inventory[seed_to_sow] <= 0:
                del current_inventory[seed_to_sow]
            write_json_state(INVENTORY_FILE_PATH, current_inventory)
            await asyncio.sleep(random.uniform(3, 7))

async def trigger_garden_check(force_run=False):
    client = get_application().client
    format_and_log("TASK", "任务启动", {'任务名': '小药园检查'})
    _sent_msg, reply = await client.send_and_wait(".小药园")
    if not reply:
        format_and_log("TASK", "任务失败", {'任务名': '小药园检查', '原因': '获取药园状态超时'}, level=logging.WARNING)
        return

    garden_status = _parse_garden_status(reply.text)
    if not garden_status: return

    if any(s in garden_status.values() for s in ['已成熟', '灵气干涸', '害虫侵扰', '杂草横生']):
        garden_status = await _handle_garden_problems(client, garden_status)
        if not garden_status: return
    
    await _sow_seeds(client, garden_status)
    format_and_log("TASK", "任务成功", {'任务名': '小药园检查', '详情': '所有流程执行完毕'})
