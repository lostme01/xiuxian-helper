# -*- coding: utf-8 -*-
import logging
import random
import pytz
import asyncio
import re
from datetime import datetime, timedelta
from telethon.tl.types import Message
from config import settings
from app.logging_service import LogType, format_and_log
from app.task_scheduler import scheduler
from app.telegram_client import CommandTimeoutError
from app.context import get_application
from app.inventory_manager import inventory_manager
from app.utils import resilient_task
from app import game_adaptor
from app.plugins.common_tasks import update_inventory_cache

__plugin_sect__ = '黄枫谷'
TASK_ID_GARDEN = 'huangfeng_garden_task'

@resilient_task()
async def trigger_garden_check(force_run=False):
    if settings.SECT_NAME != __plugin_sect__:
        format_and_log(LogType.TASK, "小药园", {'阶段': '任务中止', '原因': f'宗门不匹配 (当前: {settings.SECT_NAME}, 需要: {__plugin_sect__})'})
        if scheduler.get_job(TASK_ID_GARDEN):
            scheduler.remove_job(TASK_ID_GARDEN)
        return

    client = get_application().client
    format_and_log(LogType.TASK, "小药园", {'阶段': '任务开始', '强制执行': force_run})

    _sent, initial_reply = await client.send_game_command_request_response(game_adaptor.huangfeng_garden())
    format_and_log(LogType.TASK, "小药园", {'阶段': '获取初始状态成功', '原始返回': initial_reply.text.replace('\n', ' ')})

    initial_status = _parse_garden_status(initial_reply)
    if not initial_status:
        format_and_log(LogType.TASK, "小药园", {'阶段': '任务失败', '原因': '未能解析出任何地块信息'}, level=logging.WARNING)
        return

    format_and_log(LogType.TASK, "小药园", {'阶段': '解析初始状态', '解析结果': str(initial_status)})

    matured_plots = {pid for pid, s in initial_status.items() if s == '已成熟'}
    empty_plots = {pid for pid, s in initial_status.items() if s == '空闲'}
    plots_to_sow = set(empty_plots)

    problems_to_handle = {
        '灵气干涸': game_adaptor.huangfeng_water(),
        '害虫侵扰': game_adaptor.huangfeng_remove_pests(),
        '杂草横生': game_adaptor.huangfeng_weed()
    }

    jitter_config = settings.TASK_JITTER['huangfeng_garden']
    for status, command in problems_to_handle.items():
        if status in initial_status.values():
            format_and_log(LogType.TASK, "小药园", {'阶段': '处理非阻塞问题', '指令': command})
            await client.send_game_command_fire_and_forget(command)
            await asyncio.sleep(random.uniform(jitter_config['min'], jitter_config['max']))

    if matured_plots:
        format_and_log(LogType.TASK, "小药园", {'阶段': '执行采药', '目标地块': str(matured_plots)})
        _sent_harvest, reply_harvest = await client.send_game_command_request_response(game_adaptor.huangfeng_harvest())
        
        if "一键采药完成" in reply_harvest.text:
            format_and_log(LogType.TASK, "小药园", {'阶段': '采药成功'})
            plots_to_sow.update(matured_plots)
        else:
            format_and_log(LogType.WARNING, "小药园", {'阶段': '采药失败', '返回': reply_harvest.text})

    if plots_to_sow:
        await _sow_seeds(client, list(plots_to_sow))
    else:
        format_and_log(LogType.TASK, "小药园", {'阶段': '播种跳过', '原因': '没有需要播种的地块。'})
        
    format_and_log(LogType.TASK, "小药园", {'阶段': '任务完成'})

async def check_garden_startup():
    if settings.TASK_SWITCHES.get('garden_check'):
        scheduler.add_job(
            trigger_garden_check, 'interval', 
            minutes=random.randint(30, 60), 
            id=TASK_ID_GARDEN, 
            next_run_time=datetime.now(pytz.timezone(settings.TZ)) + timedelta(minutes=1),
            replace_existing=True
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
    status = {}; text = message.text
    matches = list(re.finditer(r'(\d+)号灵田', text))
    if not matches: return {}
    for i, match in enumerate(matches):
        try:
            plot_id = int(match.group(1))
            start_pos = match.start()
            end_pos = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            chunk = text[start_pos:end_pos]
            plot_status = next((s for s in GARDEN_STATUS_KEYWORDS if s in chunk), '未知')
            status[plot_id] = plot_status
        except (ValueError, IndexError): continue
    return status

async def _try_to_buy_seeds(client, seed_name: str, quantity: int) -> bool:
    if quantity <= 0: return True
    format_and_log(LogType.TASK, "小药园-补种", {'阶段': '尝试兑换种子', '数量': quantity})
    command = game_adaptor.sect_exchange(seed_name, quantity)
    try:
        _sent, reply = await client.send_game_command_request_response(command)
        if "**兑换成功！**" in reply.text:
            format_and_log(LogType.TASK, "小药园-补种", {'阶段': '兑换成功'})
            await asyncio.sleep(3) 
            return True
        # [修复] 使用您提供的精确回复文本
        elif "你的宗门贡献不足！" in reply.text:
            format_and_log(LogType.WARNING, "小药园-补种", {'阶段': '兑换失败', '原因': '宗门贡献不足'})
            return False
        else:
            format_and_log(LogType.WARNING, "小药园-补种", {'阶段': '兑换失败', '原因': '未知回复', '返回': reply.text.strip()})
            return False
    except CommandTimeoutError:
        format_and_log(LogType.WARNING, "小药园-补种", {'阶段': '兑换失败', '原因': '指令超时'})
        return False

# [重构] 适配新版一键播种，并集成“信任-验证-修正”逻辑
async def _sow_seeds(client, plots_to_sow: list):
    if not plots_to_sow: return

    seed_to_sow = settings.HUANGFENG_VALLEY_CONFIG.get('garden_sow_seed')
    if not seed_to_sow:
        format_and_log(LogType.WARNING, "小药园-播种", {'阶段': '中止', '原因': '未配置 garden_sow_seed'})
        return

    format_and_log(LogType.TASK, "小药园-播种", {'阶段': '任务开始', '空闲地块数': len(plots_to_sow)})

    # 1. 信任缓存，进行预检查和预购买
    inventory = await inventory_manager.get_inventory()
    current_seeds = inventory.get(seed_to_sow, 0)
    needed_seeds = len(plots_to_sow)
    
    if current_seeds < needed_seeds:
        seeds_to_buy = needed_seeds - current_seeds
        if not await _try_to_buy_seeds(client, seed_to_sow, seeds_to_buy):
            format_and_log(LogType.WARNING, "小药园-播种", {'阶段': '预购失败，中止任务'})
            return

    # 2. 执行一次性的一键播种指令
    # 在发送指令前，我们先假设缓存是正确的，即我们至少有1个种子
    if (await inventory_manager.get_item_count(seed_to_sow)) > 0:
        command = game_adaptor.huangfeng_sow(seed_to_sow)
        _sent, reply = await client.send_game_command_request_response(command)

        # 3. 验证结果
        # [修复] 使用您提供的精确成功回复
        if "**播种成功！**" in reply.text:
            format_and_log(LogType.TASK, "小药园-播种", {'阶段': '一键播种成功'})
            # 播种成功后，事件总线会自动处理库存减少，无需手动操作

        # [修复] 使用您提供的精确失败回复
        elif f"你的储物袋中没有【{seed_to_sow}】" in reply.text:
            # “验证失败”的明确信号！
            format_and_log(LogType.WARNING, "小药园-播种-修正", {'状态': '缓存与实际不符，触发自我修正'})
            # a. 强制刷新库存以修正缓存
            await update_inventory_cache(force_run=True)
            # b. 中止当前任务，等待下个周期以全新状态执行
            format_and_log(LogType.TASK, "小药园-播种-修正", {'状态': '修正流程已执行，中止当前任务等待下周期'})
        else:
            format_and_log(LogType.WARNING, "小药园-播种", {'阶段': '播种失败', '返回': reply.text.strip()})
    else:
        format_and_log(LogType.WARNING, "小药园-播种", {'阶段': '中止', '原因': '即使在尝试购买后，缓存中的种子数仍为0'})

