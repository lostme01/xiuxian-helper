# -*- coding: utf-8 -*-
import logging
import random
import pytz
import asyncio
import re
from datetime import datetime, timedelta
from telethon.tl.types import Message
from config import settings
from app.logger import format_and_log
from app.state_manager import get_state, set_state
from app.task_scheduler import scheduler
from app.telegram_client import CommandTimeoutError
from app.context import get_application

__plugin_sect__ = '黄枫谷'
TASK_ID_GARDEN = 'huangfeng_garden_task'

async def trigger_garden_check(force_run=False):
    client = get_application().client
    format_and_log("TASK", "小药园", {'阶段': '任务开始', '强制执行': force_run})
    try:
        _sent, reply = await client.send_game_command_request_response(".小药园")
        format_and_log("TASK", "小药园", {'阶段': '获取状态成功', '原始返回': reply.raw_text.replace('\n', ' ')})
    except CommandTimeoutError:
        format_and_log("TASK", "小药园", {'阶段': '获取状态失败', '原因': '等待回复超时'}, level=logging.ERROR)
        return

    garden_status = _parse_garden_status(reply)
    if not garden_status:
        format_and_log("TASK", "小药园", {'阶段': '解析状态失败', '原因': '未能从返回中解析出任何地块信息'}, level=logging.WARNING)
        return

    format_and_log("TASK", "小药园", {'阶段': '解析状态完成', '解析结果': str(garden_status)})
    if any(s in garden_status.values() for s in ['已成熟', '灵气干涸', '害虫侵扰', '杂草横生']):
        garden_status = await _handle_garden_problems(client, garden_status)
        if not garden_status:
            format_and_log("TASK", "小药园", {'阶段': '任务中止', '原因': '处理地块问题后未能重新获取状态'}, level=logging.ERROR)
            return
            
    await _sow_seeds(client, garden_status)
    format_and_log("TASK", "小药园", {'阶段': '任务完成'})

async def check_garden_startup():
    if settings.TASK_SWITCHES.get('garden_check') and not scheduler.get_job(TASK_ID_GARDEN):
        scheduler.add_job(
            trigger_garden_check, 'interval', 
            minutes=random.randint(30, 60), 
            id=TASK_ID_GARDEN, 
            next_run_time=datetime.now(pytz.timezone(settings.TZ)) + timedelta(minutes=1)
        )

def initialize(app):
    app.register_task(
        task_key="xiaoyaoyuan",
        function=trigger_garden_check,
        command_name="立即药园",
        help_text="立即检查黄枫谷的小药园状态并进行处理。"
    )
    app.startup_checks.append(check_garden_startup)

def _parse_garden_status(message: Message):
    GARDEN_STATUS_KEYWORDS = ['空闲', '已成熟', '灵气干涸', '害虫侵扰', '杂草横生', '生长中']
    status = {}
    pattern = re.compile(r'\**(\d+)\s*号灵田\**\s*[:：\s]\s*(.+)')
    for line in message.raw_text.split('\n'):
        if match := pattern.search(line):
            status[int(match.group(1))] = next((s for s in GARDEN_STATUS_KEYWORDS if s in match.group(2)), '未知')
    return status

async def _handle_garden_problems(client, status) -> dict | None:
    problems = {st for st in ['已成熟', '灵气干涸', '害虫侵扰', '杂草横生'] if st in status.values()}
    if not problems: return status
    
    format_and_log("TASK", "小药园", {'阶段': '处理地块', '待办事项': str(problems)})
    jitter_config = settings.TASK_JITTER['huangfeng_garden']
    commands_to_send = {'已成熟': ".采药", '灵气干涸': ".浇水", '害虫侵扰': ".除虫", '杂草横生': ".除草"}
    
    for problem, command in commands_to_send.items():
        if problem in problems:
            await client.send_game_command_fire_and_forget(command)
            format_and_log("TASK", "小药园", {'阶段': '发送指令', '指令': command})
            await asyncio.sleep(random.uniform(jitter_config['min'], jitter_config['max']))
            
    format_and_log("TASK", "小药园", {'阶段': '处理完毕', '操作': '等待后重新获取状态...'})
    await asyncio.sleep(random.uniform(20, 30))
    try:
        _sent, reply = await client.send_game_command_request_response(".小药园")
        new_status = _parse_garden_status(reply)
        format_and_log("TASK", "小药园", {'阶段': '重新获取状态成功', '新状态': str(new_status)})
        return new_status
    except CommandTimeoutError:
        return None

def _find_seed_to_sow(inventory):
    preferred = settings.HUANGFENG_VALLEY_CONFIG.get('garden_sow_seed')
    if preferred and inventory.get(preferred, 0) > 0: return preferred
    return next((item for item, quantity in inventory.items() if "种子" in item and quantity > 0), None)

async def _sow_seeds(client, garden_status):
    sow_plots = [pid for pid, s in garden_status.items() if s == '空闲']
    if not sow_plots: return
    
    format_and_log("TASK", "小药园", {'阶段': '准备播种', '空闲地块': str(sow_plots)})
    inventory = await get_state("inventory", is_json=True)
    if not inventory:
        format_and_log("TASK", "小药园", {'阶段': '播种中止', '原因': '背包缓存为空'}, level=logging.WARNING)
        return
        
    jitter_config = settings.TASK_JITTER['huangfeng_garden']
    for plot_id in sow_plots:
        seed = _find_seed_to_sow(inventory)
        if not seed:
            format_and_log("TASK", "小药园", {'阶段': '播种中止', '原因': '在背包中找不到任何可用种子'})
            break
            
        format_and_log("TASK", "小药园", {'阶段': '执行播种', '地块': plot_id, '种子': seed})
        try:
            _sent, reply = await client.send_game_command_request_response(f".播种 {plot_id} {seed}")
            if "成功" in reply.text:
                inventory[seed] -= 1
                if inventory[seed] <= 0: del inventory[seed]
                await set_state("inventory", inventory)
                format_and_log("TASK", "小药园", {'阶段': '播种成功', '地块': plot_id, '种子': seed})
            else:
                 format_and_log("TASK", "小药园", {'阶段': '播种失败', '地块': plot_id, '返回': reply.raw_text}, level=logging.WARNING)
            await asyncio.sleep(random.uniform(jitter_config['min'], jitter_config['max']))
        except CommandTimeoutError:
            format_and_log("TASK", "小药园", {'阶段': '播种失败', '原因': '等待回复超时', '地块': plot_id}, level=logging.ERROR)
            continue
