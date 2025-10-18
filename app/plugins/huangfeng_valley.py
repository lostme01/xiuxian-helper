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

    matured_plots_exist = any(s == '已成熟' for s in initial_status.values())
    empty_plots_exist = any(s == '空闲' for s in initial_status.values())
    sowing_needed = empty_plots_exist # 初始时，只要有空地就需要播种

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

    if matured_plots_exist:
        format_and_log(LogType.TASK, "小药园", {'阶段': '执行采药', '原因': '发现已成熟地块'})
        _sent_harvest, reply_harvest = await client.send_game_command_request_response(game_adaptor.huangfeng_harvest())

        if "一键采药完成" in reply_harvest.text:
            format_and_log(LogType.TASK, "小药园", {'阶段': '采药成功'})
            sowing_needed = True # 采药后肯定需要播种
        else:
            format_and_log(LogType.WARNING, "小药园", {'阶段': '采药失败', '返回': reply_harvest.text})
            # 如果采药失败，可能无法播种，但我们仍然尝试（万一只是部分失败）
            sowing_needed = True

    if sowing_needed:
        # [V_逻辑简化] 不再传递地块列表
        await _sow_seeds(client)
    else:
        format_and_log(LogType.TASK, "小药园", {'阶段': '播种跳过', '原因': '没有空闲或刚收获的地块。'})

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
    # 只需要判断地块状态是否存在，不需要具体ID了，但保留解析逻辑以备后用
    matches = list(re.finditer(r'(\d+)号灵田', text))
    if not matches: return {}
    for i, match in enumerate(matches):
        try:
            plot_id = int(match.group(1))
            start_pos = match.start()
            end_pos = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            chunk = text[start_pos:end_pos]
            plot_status = next((s for s in GARDEN_STATUS_KEYWORDS if s in chunk), '未知')
            status[plot_id] = plot_status # 仍然保留ID->状态的映射
        except (ValueError, IndexError): continue
    # 返回状态列表，方便检查是否存在某种状态
    return status # 返回字典 {1: '空闲', 2: '生长中'...}

async def _try_to_buy_seeds(client, seed_name: str, quantity: int) -> bool:
    if quantity <= 0: return True
    format_and_log(LogType.TASK, "小药园-补种", {'阶段': '尝试兑换种子', '物品': seed_name, '数量': quantity})
    command = game_adaptor.sect_exchange(seed_name, quantity)
    try:
        _sent, reply = await client.send_game_command_request_response(command)
        if "**兑换成功！**" in reply.text:
            format_and_log(LogType.TASK, "小药园-补种", {'阶段': '兑换成功'})
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
    except Exception as e_buy:
        format_and_log(LogType.ERROR, "小药园-补种", {'阶段': '兑换异常', '错误': repr(e_buy)})
        return False

# [V_逻辑简化] 不再接收 plots_to_sow 列表
async def _sow_seeds(client):
    seed_to_sow = settings.HUANGFENG_VALLEY_CONFIG.get('garden_sow_seed')
    if not seed_to_sow:
        format_and_log(LogType.WARNING, "小药园-播种", {'阶段': '中止', '原因': '未配置 garden_sow_seed'})
        return

    # [V_逻辑简化] 移除旧的 needed_seeds_count 计算
    format_and_log(LogType.TASK, "小药园-播种", {'阶段': '任务开始', '种子': seed_to_sow})

    # --- 第一次尝试播种 ---
    try:
        command = game_adaptor.huangfeng_sow(seed_to_sow)
        _sent, reply = await client.send_game_command_request_response(command)
        reply_text = reply.text

        # 场景1: 第一次播种成功
        if "**播种成功！**" in reply_text:
            format_and_log(LogType.TASK, "小药园-播种", {'阶段': '首次尝试成功'})
            # [V_新逻辑] 解析成功信息，计算播种数量并更新缓存
            sown_plots_match = re.search(r"在 \*\*([\d, ]+)\*\* 号灵田上种下了", reply_text)
            if sown_plots_match:
                try:
                    plot_numbers_str = sown_plots_match.group(1)
                    # 分割字符串并去除可能的空格，然后转换为整数列表
                    sown_plot_ids = [int(p.strip()) for p in plot_numbers_str.split(',')]
                    sown_count = len(sown_plot_ids)
                    if sown_count > 0:
                        format_and_log(LogType.INFO, "小药园-播种-库存", {'状态': '解析成功', '播种地块数': sown_count, '地块': str(sown_plot_ids)})
                        await inventory_manager.remove_item(seed_to_sow, sown_count)
                    else:
                        format_and_log(LogType.WARNING, "小药园-播种-库存", {'状态': '解析播种数量为0', '原始地块字串': plot_numbers_str})
                except Exception as parse_e:
                    format_and_log(LogType.ERROR, "小药园-播种-库存", {'状态': '解析成功地块时出错', '错误': repr(parse_e), '原始回复': reply_text})
            else:
                 format_and_log(LogType.WARNING, "小药园-播种-库存", {'状态': '成功但无法解析播种地块', '原始回复': reply_text})
            return # 任务完成

        # 场景2: 第一次播种失败 - 种子不足
        elif f"你的【{seed_to_sow}】数量不足！" in reply_text:
            format_and_log(LogType.WARNING, "小药园-播种", {'阶段': '首次尝试失败', '原因': '种子不足'})

            needed_match = re.search(r"[需|要|要]:\s*([\d,]+)", reply_text)
            owned_match = re.search(r"[拥|有|有]:\s*([\d,]+)", reply_text)

            if needed_match and owned_match:
                try:
                    needed_from_reply = int(needed_match.group(1).replace(',', ''))
                    owned_actual = int(owned_match.group(1).replace(',', ''))

                    format_and_log(LogType.INFO, "小药园-播种-修正", {
                        '状态': '解析到实际库存',
                        '需要': needed_from_reply,
                        '实际拥有': owned_actual
                    })

                    current_inventory = await inventory_manager.get_inventory()
                    # [V_修复] 确保即使键不存在也能正确设置
                    current_inventory[seed_to_sow] = owned_actual
                    await inventory_manager.set_inventory(current_inventory)
                    format_and_log(LogType.INFO, "小药园-播种-修正", {'状态': '缓存已校准'})

                    seeds_to_buy = needed_from_reply - owned_actual
                    if seeds_to_buy > 0:
                        format_and_log(LogType.INFO, "小药园-播种", {'阶段': '尝试购买缺失种子', '数量': seeds_to_buy})
                        buy_success = await _try_to_buy_seeds(client, seed_to_sow, seeds_to_buy)

                        if buy_success:
                            format_and_log(LogType.INFO, "小药园-播种", {'阶段': '购买成功，准备再次尝试播种'})
                            await asyncio.sleep(random.uniform(1.5, 2.5)) # 等待一下
                            command_retry = game_adaptor.huangfeng_sow(seed_to_sow)
                            _sent_retry, reply_retry = await client.send_game_command_request_response(command_retry)

                            if "**播种成功！**" in reply_retry.text:
                                format_and_log(LogType.TASK, "小药园-播种", {'阶段': '二次尝试成功'})
                                # [V_新逻辑] 解析成功信息，计算播种数量并更新缓存
                                sown_plots_match_retry = re.search(r"在 \*\*([\d, ]+)\*\* 号灵田上种下了", reply_retry.text)
                                if sown_plots_match_retry:
                                    try:
                                        plot_numbers_str_retry = sown_plots_match_retry.group(1)
                                        sown_plot_ids_retry = [int(p.strip()) for p in plot_numbers_str_retry.split(',')]
                                        sown_count_retry = len(sown_plot_ids_retry)
                                        if sown_count_retry > 0:
                                            format_and_log(LogType.INFO, "小药园-播种-库存", {'状态': '二次尝试解析成功', '播种地块数': sown_count_retry, '地块': str(sown_plot_ids_retry)})
                                            # 注意：这里减去的是第二次尝试实际播种的数量
                                            await inventory_manager.remove_item(seed_to_sow, sown_count_retry)
                                        else:
                                             format_and_log(LogType.WARNING, "小药园-播种-库存", {'状态': '二次尝试解析播种数量为0', '原始地块字串': plot_numbers_str_retry})
                                    except Exception as parse_e_retry:
                                        format_and_log(LogType.ERROR, "小药园-播种-库存", {'状态': '二次尝试解析成功地块时出错', '错误': repr(parse_e_retry), '原始回复': reply_retry.text})
                                else:
                                    format_and_log(LogType.WARNING, "小药园-播种-库存", {'状态': '二次尝试成功但无法解析播种地块', '原始回复': reply_retry.text})
                                return # 任务完成
                            else:
                                format_and_log(LogType.WARNING, "小药园-播种", {'阶段': '二次尝试失败', '返回': reply_retry.text.strip()})
                        else:
                            format_and_log(LogType.WARNING, "小药园-播种", {'阶段': '任务中止', '原因': '购买缺失种子失败'})
                    else:
                        format_and_log(LogType.WARNING, "小药园-播种", {'阶段': '任务中止', '原因': f'计算出无需购买种子(需{needed_from_reply},有{owned_actual})，但首次播种失败'})
                except (ValueError, TypeError) as parse_err:
                    format_and_log(LogType.ERROR, "小药园-播种-修正", {'状态': '解析数量时出错', '错误': repr(parse_err), '原始回复': reply_text}, level=logging.ERROR) # 使用 repr
                    format_and_log(LogType.TASK, "小药园-播种", {'阶段': '任务中止', '原因': '无法解析数量，等待下个周期'}, level=logging.WARNING) # 避免触发外层异常
            else:
                format_and_log(LogType.ERROR, "小药园-播种-修正", {'状态': '无法从回复中提取数量', '原始回复': reply_text}, level=logging.ERROR)
                format_and_log(LogType.TASK, "小药园-播种", {'阶段': '任务中止', '原因': '无法解析数量，等待下个周期'}, level=logging.WARNING) # 避免触发外层异常

        # 场景3: 其他播种失败原因
        else:
            format_and_log(LogType.WARNING, "小药园-播种", {'阶段': '首次尝试失败', '原因': '未知', '返回': reply_text.strip()})

    except CommandTimeoutError:
        format_and_log(LogType.WARNING, "小药园-播种", {'阶段': '异常', '原因': '指令超时'})
    except Exception as e:
        # [V_修复] 使用 repr(e) 记录更详细的错误
        format_and_log(LogType.ERROR, "小药园-播种", {'阶段': '严重异常', '错误': repr(e)}, level=logging.ERROR)
