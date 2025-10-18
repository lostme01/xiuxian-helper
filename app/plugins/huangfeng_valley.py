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
# [V_修正] 移除不再需要的 update_inventory_cache 导入
# from app.plugins.common_tasks import update_inventory_cache

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
    plots_to_sow = set(empty_plots) # plots_to_sow 现在是一个包含地块ID的集合

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
            plots_to_sow.update(matured_plots) # 将采药后的地块也加入待播种集合
        else:
            format_and_log(LogType.WARNING, "小药园", {'阶段': '采药失败', '返回': reply_harvest.text})

    if plots_to_sow:
        # [V_修正] 传递地块ID的列表给 _sow_seeds
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
    format_and_log(LogType.TASK, "小药园-补种", {'阶段': '尝试兑换种子', '物品': seed_name, '数量': quantity})
    command = game_adaptor.sect_exchange(seed_name, quantity)
    try:
        _sent, reply = await client.send_game_command_request_response(command)
        if "**兑换成功！**" in reply.text:
            format_and_log(LogType.TASK, "小药园-补种", {'阶段': '兑换成功'})
            # [V_修正] 兑换成功后，主动更新缓存
            await inventory_manager.add_item(seed_name, quantity)
            await asyncio.sleep(random.uniform(1.5, 2.5)) # 稍作等待
            return True
        elif "你的宗门贡献不足！" in reply.text:
            format_and_log(LogType.WARNING, "小药园-补种", {'阶段': '兑换失败', '原因': '宗门贡献不足'})
            return False
        else:
            format_and_log(LogType.WARNING, "小药园-补种", {'阶段': '兑换失败', '原因': '未知回复', '返回': reply.text.strip()})
            return False
    except CommandTimeoutError:
        format_and_log(LogType.WARNING, "小药园-补种", {'阶段': '兑换失败', '原因': '指令超时'})
        return False

# [V_修正] 重构 _sow_seeds 以实现新的逻辑
async def _sow_seeds(client, plots_to_sow: list):
    if not plots_to_sow: return

    seed_to_sow = settings.HUANGFENG_VALLEY_CONFIG.get('garden_sow_seed')
    if not seed_to_sow:
        format_and_log(LogType.WARNING, "小药园-播种", {'阶段': '中止', '原因': '未配置 garden_sow_seed'})
        return

    needed_seeds_count = len(plots_to_sow)
    format_and_log(LogType.TASK, "小药园-播种", {'阶段': '任务开始', '空闲地块数': needed_seeds_count, '种子': seed_to_sow})

    # --- 第一次尝试播种 ---
    try:
        command = game_adaptor.huangfeng_sow(seed_to_sow)
        _sent, reply = await client.send_game_command_request_response(command)
        reply_text = reply.text

        # 场景1: 第一次播种成功
        if "**播种成功！**" in reply_text:
            format_and_log(LogType.TASK, "小药园-播种", {'阶段': '首次尝试成功'})
            # 假设一键播种会消耗掉所有需要的种子
            await inventory_manager.remove_item(seed_to_sow, needed_seeds_count)
            return # 任务完成

        # 场景2: 第一次播种失败 - 种子不足
        elif f"你的【{seed_to_sow}】数量不足！" in reply_text:
            format_and_log(LogType.WARNING, "小药园-播种", {'阶段': '首次尝试失败', '原因': '种子不足'})

            # 解析实际拥有和需要的数量
            needed_match = re.search(r"需要:\s*(\d+)", reply_text)
            owned_match = re.search(r"拥有:\s*(\d+)", reply_text)

            if needed_match and owned_match:
                needed_from_reply = int(needed_match.group(1))
                owned_actual = int(owned_match.group(1))

                format_and_log(LogType.INFO, "小药园-播种-修正", {
                    '状态': '解析到实际库存',
                    '需要': needed_from_reply,
                    '实际拥有': owned_actual
                })

                # 用实际拥有的数量校准缓存
                current_inventory = await inventory_manager.get_inventory()
                current_inventory[seed_to_sow] = owned_actual
                await inventory_manager.set_inventory(current_inventory)
                format_and_log(LogType.INFO, "小药园-播种-修正", {'状态': '缓存已校准'})

                seeds_to_buy = needed_from_reply - owned_actual
                if seeds_to_buy > 0:
                    format_and_log(LogType.INFO, "小药园-播种", {'阶段': '尝试购买缺失种子', '数量': seeds_to_buy})
                    buy_success = await _try_to_buy_seeds(client, seed_to_sow, seeds_to_buy)

                    if buy_success:
                        format_and_log(LogType.INFO, "小药园-播种", {'阶段': '购买成功，准备再次尝试播种'})
                        # --- 第二次尝试播种 ---
                        await asyncio.sleep(random.uniform(1.5, 2.5)) # 等待一下
                        command_retry = game_adaptor.huangfeng_sow(seed_to_sow)
                        _sent_retry, reply_retry = await client.send_game_command_request_response(command_retry)

                        if "**播种成功！**" in reply_retry.text:
                            format_and_log(LogType.TASK, "小药园-播种", {'阶段': '二次尝试成功'})
                            # 假设第二次播种消耗了补购后足够数量的种子
                            # ( owned_actual + seeds_to_buy ) - needed_seeds_count 理论上是0或正数
                            # 但为了简单和防止计算错误，直接移除本次需要的数量
                            await inventory_manager.remove_item(seed_to_sow, needed_seeds_count)
                            return # 任务完成
                        else:
                            format_and_log(LogType.WARNING, "小药园-播种", {'阶段': '二次尝试失败', '返回': reply_retry.text.strip()})
                    else:
                        format_and_log(LogType.WARNING, "小药园-播种", {'阶段': '任务中止', '原因': '购买缺失种子失败'})
                else:
                    # 如果计算出不需要购买 (可能是解析错误或特殊情况)，也中止
                    format_and_log(LogType.WARNING, "小药园-播种", {'阶段': '任务中止', '原因': '计算出无需购买种子，但首次播种失败'})
            else:
                # 如果无法解析数量，按旧逻辑处理：强制同步并中止
                format_and_log(LogType.ERROR, "小药园-播种-修正", {'状态': '无法解析不足提示中的数量', '原始回复': reply_text})
                # 旧的修正逻辑：强制刷新缓存并等待下一周期
                # await update_inventory_cache(force_run=True) # 移除强制刷新
                format_and_log(LogType.TASK, "小药园-播种", {'阶段': '任务中止', '原因': '无法解析数量，等待下个周期'})

        # 场景3: 其他播种失败原因
        else:
            format_and_log(LogType.WARNING, "小药园-播种", {'阶段': '首次尝试失败', '原因': '未知', '返回': reply_text.strip()})

    except CommandTimeoutError:
        format_and_log(LogType.WARNING, "小药园-播种", {'阶段': '异常', '原因': '指令超时'})
    except Exception as e:
        format_and_log(LogType.ERROR, "小药园-播种", {'阶段': '严重异常', '错误': str(e)}, level=logging.ERROR)

