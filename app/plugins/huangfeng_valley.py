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
    """
    [最终优化版]
    优化小药园任务流程，通过确认采药结果来避免二次查询。
    """
    client = get_application().client
    format_and_log("TASK", "小药园", {'阶段': '任务开始', '强制执行': force_run})

    # 1. 获取初始状态
    try:
        _sent, initial_reply = await client.send_game_command_request_response(".小药园")
        format_and_log("TASK", "小药园", {'阶段': '获取初始状态成功', '原始返回': initial_reply.raw_text.replace('\n', ' ')})
    except CommandTimeoutError:
        format_and_log("TASK", "小药园", {'阶段': '任务失败', '原因': '获取初始状态超时'}, level=logging.ERROR)
        return

    initial_status = _parse_garden_status(initial_reply)
    if not initial_status:
        format_and_log("TASK", "小药园", {'阶段': '任务失败', '原因': '未能解析出任何地块信息'}, level=logging.WARNING)
        return

    format_and_log("TASK", "小药园", {'阶段': '解析初始状态', '解析结果': str(initial_status)})

    # 2. 分类地块并处理非阻塞性问题
    matured_plots = {pid for pid, s in initial_status.items() if s == '已成熟'}
    empty_plots = {pid for pid, s in initial_status.items() if s == '空闲'}
    plots_to_sow = set(empty_plots) # 先将原本就空闲的地块加入待播种列表

    problems_to_handle = {
        '灵气干涸': '.浇水',
        '害虫侵扰': '.除虫',
        '杂草横生': '.除草'
    }

    jitter_config = settings.TASK_JITTER['huangfeng_garden']
    for status, command in problems_to_handle.items():
        if status in initial_status.values():
            format_and_log("TASK", "小药园", {'阶段': '处理非阻塞问题', '指令': command})
            await client.send_game_command_fire_and_forget(command)
            await asyncio.sleep(random.uniform(jitter_config['min'], jitter_config['max']))

    # 3. 处理关键操作：采药
    if matured_plots:
        format_and_log("TASK", "小药园", {'阶段': '执行采药', '目标地块': str(matured_plots)})
        try:
            _sent_harvest, reply_harvest = await client.send_game_command_request_response(".采药")
            # [核心优化] 检查采药是否成功
            if "一键采药完成" in reply_harvest.text:
                format_and_log("TASK", "小药园", {'阶段': '采药成功', '详情': '已成熟地块将加入待播种列表。'})
                # 将已成熟的地块也加入待播种列表
                plots_to_sow.update(matured_plots)
            else:
                format_and_log("TASK", "小药园", {'阶段': '采药失败', '原因': '未收到成功确认', '返回': reply_harvest.text}, level=logging.WARNING)
        except CommandTimeoutError:
            format_and_log("TASK", "小药园", {'阶段': '采药失败', '原因': '等待回复超时'}, level=logging.ERROR)

    # 4. 执行播种
    if plots_to_sow:
        await _sow_seeds(client, list(plots_to_sow))
    else:
        format_and_log("TASK", "小药园", {'阶段': '播种跳过', '原因': '没有需要播种的地块。'})
        
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

def _find_seed_to_sow(inventory):
    preferred = settings.HUANGFENG_VALLEY_CONFIG.get('garden_sow_seed')
    if preferred and inventory.get(preferred, 0) > 0: return preferred
    return next((item for item, quantity in inventory.items() if "种子" in item and quantity > 0), None)

async def _sow_seeds(client, plots_to_sow: list):
    if not plots_to_sow: return
    
    format_and_log("TASK", "小药园", {'阶段': '准备播种', '待播种地块': str(plots_to_sow)})
    inventory = await get_state("inventory", is_json=True)
    if not inventory:
        format_and_log("TASK", "小药园", {'阶段': '播种中止', '原因': '背包缓存为空'}, level=logging.WARNING)
        return
        
    jitter_config = settings.TASK_JITTER['huangfeng_garden']
    for plot_id in sorted(plots_to_sow): # 排序以保证播种顺序固定
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
                # 播种成功后立即更新背包缓存状态，避免后续循环中重复使用已耗尽的种子
                await set_state("inventory", inventory)
                format_and_log("TASK", "小药园", {'阶段': '播种成功', '地块': plot_id, '种子': seed})
            else:
                 format_and_log("TASK", "小药园", {'阶段': '播种失败', '地块': plot_id, '返回': reply.raw_text}, level=logging.WARNING)
            await asyncio.sleep(random.uniform(jitter_config['min'], jitter_config['max']))
        except CommandTimeoutError:
            format_and_log("TASK", "小药园", {'阶段': '播种失败', '原因': '等待回复超时', '地块': plot_id}, level=logging.ERROR)
            continue
