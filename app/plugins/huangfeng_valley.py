# -*- coding: utf-8 -*-
import logging
import random
import pytz
import asyncio
import re
import inspect
from datetime import datetime, timedelta
from config import settings
from app.logger import format_and_log
from app.utils import read_json_state, write_json_state, parse_inventory_text
from app.task_scheduler import scheduler

client = None
TASK_ID_GARDEN = 'huangfeng_garden_task'
INVENTORY_FILE_PATH = f"{settings.DATA_DIR}/inventory.json" # 仍然需要读取库存
GARDEN_STATUS_KEYWORDS = ['空闲', '已成熟', '灵气干涸', '害虫侵扰', '杂草横生', '生长中']

def initialize_tasks(tg_client):
    global client
    client = tg_client
    # 只注册与小药园直接相关的任务和指令
    client.register_task('xiaoyaoyuan', trigger_garden_check)
    client.register_admin_command("药园检查", manual_trigger_wrapper, "手动触发一次小药园检查。")
    return [check_garden_startup]

async def manual_trigger_wrapper(client, event, parts):
    """一个通用的手动触发包装器，用于此插件内的所有任务"""
    command_map = {
        "药园检查": "xiaoyaoyuan",
    }
    command_name = parts[0]
    task_key = command_map.get(command_name)
    
    if task_key and (task_func := client.task_plugins.get(task_key)):
        await event.reply(f"好的，已手动触发 **[{command_name}]** 任务。", parse_mode='md')
        format_and_log("TASK", "任务触发", {'任务名': command_name, '来源': '管理员手动触发'})
        asyncio.create_task(task_func())
    else:
        await event.reply(f"错误: [{command_name}] 任务未注册。")

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
    unique_statuses = set(status.values())
    commands_to_run = {st: cmd for st, cmd in {'已成熟': ".采药", '灵气干涸': ".浇水", '害虫侵扰': ".除虫", '杂草横生': ".除草"}.items() if st in unique_statuses}
    
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
    preferred = settings.GARDEN_SOW_SEED
    if preferred and inventory.get(preferred, 0) > 0:
        format_and_log("DEBUG", "种子选择", {'详情': f"找到优先种子: {preferred}"})
        return preferred
    for item, quantity in inventory.items():
        if "种子" in item and quantity > 0:
            format_and_log("DEBUG", "种子选择", {'详情': f"找到可用种子: {item}"})
            return item
    return None

async def _sow_seeds(garden_status: dict):
    sow_plots = [pid for pid, s in garden_status.items() if s == '空闲']
    if not sow_plots:
        format_and_log("TASK", "任务进度", {'任务名': '播种', '详情': '没有空闲地皮，跳过播种'})
        return

    inventory = read_json_state(INVENTORY_FILE_PATH) or {}
    if not inventory:
        format_and_log("TASK", "任务进度", {'任务名': '播种', '详情': '背包缓存为空，跳过播种'})
        return
    
    seed_to_sow = _find_seed_to_sow(inventory)
    if not seed_to_sow:
        format_and_log("TASK", "任务进度", {'任务名': '播种', '详情': '背包中没有可用种子，终止播种'})
        return
        
    format_and_log("TASK", "任务进度", {'任务名': '播种', '详情': f"发现 {len(sow_plots)} 块空闲地皮，准备播种 -> {seed_to_sow}"})
    for plot_id in sow_plots:
        current_seed = _find_seed_to_sow(inventory)
        if not current_seed:
            format_and_log("TASK", "任务进度", {'任务名': '播种', '详情': '种子已用完，终止播种'})
            break
        _sent, reply = await client.send_and_wait(f".播种 {plot_id} {current_seed}")
        if reply and "成功" in reply.text:
            inventory[current_seed] = inventory.get(current_seed, 1) - 1
            write_json_state(INVENTORY_FILE_PATH, inventory)
            format_and_log("DEBUG", "播种成功", {'地皮': plot_id, '消耗': current_seed})

async def trigger_garden_check():
    format_and_log("TASK", "任务启动", {'任务名': '小药园检查'})
    _sent_msg, reply = await client.send_and_wait(".小药园")
    if not reply:
        format_and_log("TASK", "任务失败", {'任务名': '小药园检查', '原因': '获取药园状态超时'}, level=logging.WARNING)
        return

    garden_status = _parse_garden_status(reply.text)
    format_and_log("TASK", "任务进度", {'任务名': '小药园检查', '详情': f"解析出 {len(garden_status)} 块地皮状态"})
    if not garden_status: return

    if any(s in garden_status.values() for s in ['已成熟', '灵气干涸', '害虫侵扰', '杂草横生']):
        garden_status = await _handle_garden_problems(garden_status)
        if not garden_status: return
    
    await _sow_seeds(garden_status)
    format_and_log("TASK", "任务成功", {'任务名': '小药园检查', '详情': '所有流程执行完毕'})

async def check_garden_startup():
    if not settings.TASK_SWITCHES.get('garden_check'):
        format_and_log("SYSTEM", "任务跳过", {'任务名': '自动药园', '原因': '配置中已禁用'})
        return
    if not scheduler.get_job(TASK_ID_GARDEN):
        minutes = random.randint(30, 60)
        scheduler.add_job(trigger_garden_check, 'interval', minutes=minutes, id=TASK_ID_GARDEN, 
                          next_run_time=datetime.now(pytz.timezone(settings.TZ)) + timedelta(minutes=1))
