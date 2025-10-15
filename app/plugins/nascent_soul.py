# -*- coding: utf-8 -*-
import logging
import random
import re
import pytz
import json
from datetime import datetime, timedelta

from app import game_adaptor
from app.constants import (STATE_KEY_NASCENT_SOUL, TASK_ID_NASCENT_SOUL, STATE_KEY_PROFILE)
from app.context import get_application
from app.data_manager import data_manager
from app.logging_service import LogType, format_and_log
from app.task_scheduler import scheduler
from app.telegram_client import CommandTimeoutError
from app.utils import resilient_task
from config import settings

def _parse_countdown_from_text(text: str) -> timedelta | None:
    """从元婴状态文本中解析归来倒计时"""
    # [BUG 修正] 使用更健壮的正则表达式，兼容带或不带 ** 的情况
    countdown_match = re.search(r"\*?\*?归来倒计时\*?\*?\s*:\s*(.*)", text)
    if not countdown_match:
        return None
    
    time_str = countdown_match.group(1).strip()
    
    pattern = r'(\d+)\s*(小时|时|分钟|分|秒)'
    matches = re.findall(pattern, time_str)
    if not matches:
        return None

    total_seconds = 0
    for value_str, unit in matches:
        value = int(value_str)
        if unit in ['小时', '时']:
            total_seconds += value * 3600
        elif unit in ['分钟', '分']:
            total_seconds += value * 60
        elif unit == '秒':
            total_seconds += value
            
    return timedelta(seconds=total_seconds) if total_seconds > 0 else None

def _parse_nascent_soul_status(text: str) -> dict:
    """解析元婴状态的完整回复"""
    result = {'state': '未知', 'cooldown': None, 'raw': text}
    
    # [BUG 修正] 使用更健壮的正则表达式，兼容带或不带 ** 的情况
    state_match = re.search(r"\*?\*?状态\*?\*?\s*:\s*(.*)", text)
    if not state_match:
        return result

    state = state_match.group(1).strip()
    result['state'] = state

    if state == '元神出窍':
        result['cooldown'] = _parse_countdown_from_text(text)
        
    return result

async def _schedule_next_run(next_run_time: datetime, current_status: dict = None):
    """辅助函数，用于调度和持久化下一次运行时间及当前状态"""
    scheduler.add_job(trigger_nascent_soul_egress, 'date', run_date=next_run_time, id=TASK_ID_NASCENT_SOUL, replace_existing=True)
    
    # [新增] 将状态和下次运行时间一并存入数据库
    state_to_save = {
        "next_run_iso": next_run_time.isoformat(),
        "status": current_status
    }
    await data_manager.save_value(STATE_KEY_NASCENT_SOUL, state_to_save)
    format_and_log(LogType.TASK, "元婴出窍", {'阶段': '任务完成', '下次调度时间': next_run_time.strftime('%Y-%m-%d %H:%M:%S')})


@resilient_task()
async def trigger_nascent_soul_egress(force_run=False):
    """
    自动元婴出窍的核心任务逻辑。
    """
    app = get_application()
    client = app.client
    format_and_log(LogType.TASK, "元婴出窍", {'阶段': '任务开始', '强制执行': force_run})
    
    # 1. 境界前置检查
    profile = await data_manager.get_value(STATE_KEY_PROFILE, is_json=True, default={})
    realm = profile.get('境界', '')
    if '元婴' not in realm:
        format_and_log(LogType.TASK, "元婴出窍", {'阶段': '任务中止', '原因': f'境界未达到元婴期 (当前: {realm})'})
        if scheduler.get_job(TASK_ID_NASCENT_SOUL):
            scheduler.remove_job(TASK_ID_NASCENT_SOUL)
        if force_run:
            return "❌ **[立即出窍]** 任务执行失败：您的境界尚未达到元婴期。"
        return

    beijing_tz = pytz.timezone(settings.TZ)
    manual_run_report = []

    try:
        # 2. 查询当前元婴状态
        _sent_status, reply_status = await client.send_game_command_request_response(game_adaptor.get_nascent_soul_status())
        parsed_info = _parse_nascent_soul_status(reply_status.text)
        current_state = parsed_info.get('state')
        
        format_and_log(LogType.TASK, "元婴出窍", {'阶段': '查询状态成功', '当前状态': current_state})
        if force_run:
            manual_run_report.append(f"- **查询状态**: 发现元婴当前为 `{current_state or '未知'}` 状态。")

        # 3. 根据状态决策
        if current_state == '元神出窍':
            cooldown = parsed_info.get('cooldown')
            if cooldown:
                next_run_time = datetime.now(beijing_tz) + cooldown + timedelta(minutes=5)
                format_and_log(LogType.TASK, "元婴出窍", {'阶段': '决策', '详情': '元婴已出窍，等待归来', '预计归来时间': str(cooldown)})
                await client.send_admin_notification(f"✅ **元婴状态同步**\n\n元婴已出窍，下次检查时间已更新为 `{next_run_time.strftime('%H:%M:%S')}`。")
                if force_run:
                    manual_run_report.append(f"- **执行操作**: 无需操作，等待元婴归来。")
            else:
                next_run_time = datetime.now(beijing_tz) + timedelta(minutes=30)
                format_and_log(LogType.WARNING, "元婴出窍", {'阶段': '决策', '详情': '元婴已出窍，但无法解析倒计时，30分钟后重试'})
                await client.send_admin_notification(f"⚠️ **元婴任务警报**\n\n- **问题**: 元婴已出窍，但无法解析归来倒计时。\n- **操作**: 已安排在30分钟后重试。\n- **原始文本**:\n`{reply_status.text}`")
            
            await _schedule_next_run(next_run_time, parsed_info)

        elif current_state == '窍中温养':
            format_and_log(LogType.TASK, "元婴出窍", {'阶段': '决策', '详情': '元婴在窍，派遣出窍'})
            if force_run:
                manual_run_report.append(f"- **执行操作**: 发送 `.元婴出窍` 指令。")
            _sent_action, reply_action = await client.send_game_command_request_response(game_adaptor.send_nascent_soul_out())
            
            if "化作一道流光飞出" in reply_action.text:
                next_run_time = datetime.now(beijing_tz) + timedelta(hours=8, minutes=5)
                format_and_log(LogType.TASK, "元婴出窍", {'阶段': '执行成功', '详情': '已成功派遣元婴出窍'})
                await client.send_admin_notification(f"🚀 **元婴已成功派遣**\n\n下次自动检查时间已设定为 `{next_run_time.strftime('%H:%M:%S')}`。")
                # [新增] 派遣成功后，立即更新状态为出窍，避免启动时误判
                success_status = {'state': '元神出窍', 'cooldown': timedelta(hours=8)}
                await _schedule_next_run(next_run_time, success_status)
            else:
                next_run_time = datetime.now(beijing_tz) + timedelta(minutes=30)
                format_and_log(LogType.WARNING, "元婴出窍", {'阶段': '执行失败', '原因': '收到非预期的回复', '返回': reply_action.text})
                await client.send_admin_notification(f"⚠️ **元婴任务警报**\n\n- **问题**: 尝试派遣元婴，但收到了非预期的回复。\n- **操作**: 已安排在30分钟后重试。\n- **原始文本**:\n`{reply_action.text}`")
                await _schedule_next_run(next_run_time, parsed_info)
        
        else: # 状态未知
            next_run_time = datetime.now(beijing_tz) + timedelta(minutes=30)
            format_and_log(LogType.ERROR, "元婴出窍", {'阶段': '任务异常', '原因': '无法解析元婴状态', '原始文本': reply_status.text})
            await client.send_admin_notification(f"🔥 **元婴任务严重错误**\n\n- **问题**: 无法从游戏回复中解析出元婴的当前状态。\n- **操作**: 已安排在30分钟后重试。\n- **原始文本**:\n`{reply_status.text}`")
            await _schedule_next_run(next_run_time, parsed_info)

        if force_run:
            report_header = "✅ **[立即出窍]** 任务已成功执行。\n\n**执行摘要**:\n"
            report_body = "\n".join(manual_run_report)
            report_footer = f"\n\n下次自动检查时间已规划在 `{next_run_time.strftime('%H:%M:%S')}` 左右。"
            return report_header + report_body + report_footer

    except CommandTimeoutError:
        format_and_log(LogType.WARNING, "元婴出窍", {'阶段': '任务异常', '原因': '游戏指令超时'})
        next_run_time = datetime.now(beijing_tz) + timedelta(minutes=15)
        await client.send_admin_notification(f"⚠️ **元婴任务警报**\n\n- **问题**: 与游戏机器人通信超时。\n- **操作**: 已安排在15分钟后重试。")
        await _schedule_next_run(next_run_time)
        if force_run:
            return "❌ **[立即出窍]** 任务失败：与游戏机器人通信超时。"

async def check_nascent_soul_startup():
    """启动时检查并调度元婴出窍任务"""
    if not settings.TASK_SWITCHES.get('nascent_soul'):
        return

    if scheduler.get_job(TASK_ID_NASCENT_SOUL):
        return

    state_data = await data_manager.get_value(STATE_KEY_NASCENT_SOUL, is_json=True, default={})
    iso_str = state_data.get("next_run_iso")
    
    beijing_tz = pytz.timezone(settings.TZ)
    now = datetime.now(beijing_tz)
    
    state_time = None
    if iso_str:
        try:
            state_time = datetime.fromisoformat(iso_str).astimezone(beijing_tz)
        except (ValueError, TypeError):
            state_time = None
            
    # [逻辑优化] 如果有合法的未来执行时间，则使用它；否则，立即执行一次检查
    if state_time and state_time > now:
        run_date = state_time
        scheduler.add_job(trigger_nascent_soul_egress, 'date', run_date=run_date, id=TASK_ID_NASCENT_SOUL, replace_existing=True)
        format_and_log(LogType.SYSTEM, "任务调度", {'任务': '自动元婴出窍', '状态': '已按计划恢复', '预计时间': run_date.strftime('%Y-%m-%d %H:%M:%S')})
    else:
        # 如果没有计划或计划已过期，则立即执行一次
        format_and_log(LogType.SYSTEM, "任务调度", {'任务': '自动元婴出窍', '状态': '启动时立即执行检查'})
        await trigger_nascent_soul_egress(force_run=True)


def initialize(app):
    app.register_task(
        task_key="nascent_soul",
        function=trigger_nascent_soul_egress,
        command_name="立即出窍",
        help_text="立即执行一次元婴出窍的检查与派遣任务。"
    )
    app.startup_checks.append(check_nascent_soul_startup)
