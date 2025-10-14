# -*- coding: utf-8 -*-
import logging
import random
import re
import pytz
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
    countdown_match = re.search(r"归来倒计时\s*:\s*(.*)", text)
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
    result = {'state': None, 'cooldown': None}
    state_match = re.search(r"状态\s*:\s*(.*)", text)
    if not state_match:
        return result

    state = state_match.group(1).strip()
    result['state'] = state

    if state == '元神出窍':
        result['cooldown'] = _parse_countdown_from_text(text)
        
    return result

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
        # 如果任务存在，则移除，避免不必要的执行
        if scheduler.get_job(TASK_ID_NASCENT_SOUL):
            scheduler.remove_job(TASK_ID_NASCENT_SOUL)
        return "❌ **[元婴出窍]** 任务执行失败：您的境界尚未达到元婴期。" if force_run else None

    beijing_tz = pytz.timezone(settings.TZ)
    # 默认重试时间
    next_run_time = datetime.now(beijing_tz) + timedelta(minutes=random.randint(15, 30))
    
    try:
        # 2. 查询当前元婴状态
        _sent_status, reply_status = await client.send_game_command_request_response(game_adaptor.get_nascent_soul_status())
        parsed_info = _parse_nascent_soul_status(reply_status.text)
        current_state = parsed_info.get('state')
        
        format_and_log(LogType.TASK, "元婴出窍", {'阶段': '查询状态成功', '当前状态': current_state})

        # 3. 根据状态决策
        if current_state == '元神出窍':
            cooldown = parsed_info.get('cooldown')
            if cooldown:
                # 在倒计时基础上增加5分钟冗余
                next_run_time = datetime.now(beijing_tz) + cooldown + timedelta(minutes=5)
                format_and_log(LogType.TASK, "元婴出窍", {'阶段': '决策', '详情': '元婴已出窍，等待归来', '预计归来时间': str(cooldown)})
                await client.send_admin_notification(f"✅ **元婴状态同步**\n\n元婴已出窍，下次检查时间已更新为 `{next_run_time.strftime('%H:%M:%S')}`。")
            else:
                # [BUG 修正] 异常重试时间从1小时改为30分钟
                next_run_time = datetime.now(beijing_tz) + timedelta(minutes=30)
                format_and_log(LogType.WARNING, "元婴出窍", {'阶段': '决策', '详情': '元婴已出窍，但无法解析倒计时，30分钟后重试'})
                await client.send_admin_notification(f"⚠️ **元婴任务警报**\n\n- **问题**: 元婴已出窍，但无法解析归来倒计时。\n- **操作**: 已安排在30分钟后重试。\n- **原始文本**:\n`{reply_status.text}`")


        elif current_state == '窍中温养':
            format_and_log(LogType.TASK, "元婴出窍", {'阶段': '决策', '详情': '元婴在窍，派遣出窍'})
            _sent_action, reply_action = await client.send_game_command_request_response(game_adaptor.send_nascent_soul_out())
            
            if "化作一道流光飞出" in reply_action.text:
                # 游戏固定8小时
                next_run_time = datetime.now(beijing_tz) + timedelta(hours=8, minutes=5)
                format_and_log(LogType.TASK, "元婴出窍", {'阶段': '执行成功', '详情': '已成功派遣元婴出窍'})
                await client.send_admin_notification(f"🚀 **元婴已成功派遣**\n\n下次自动检查时间已设定为 `{next_run_time.strftime('%H:%M:%S')}`。")
            else:
                # [BUG 修正] 异常重试时间从1小时改为30分钟
                next_run_time = datetime.now(beijing_tz) + timedelta(minutes=30)
                format_and_log(LogType.WARNING, "元婴出窍", {'阶段': '执行失败', '原因': '收到非预期的回复', '返回': reply_action.text})
                await client.send_admin_notification(f"⚠️ **元婴任务警报**\n\n- **问题**: 尝试派遣元婴，但收到了非预期的回复。\n- **操作**: 已安排在30分钟后重试。\n- **原始文本**:\n`{reply_action.text}`")
        
        else:
            # [BUG 修正] 异常重试时间从1小时改为30分钟
            next_run_time = datetime.now(beijing_tz) + timedelta(minutes=30)
            format_and_log(LogType.ERROR, "元婴出窍", {'阶段': '任务异常', '原因': '无法解析元婴状态', '原始文本': reply_status.text})
            await client.send_admin_notification(f"🔥 **元婴任务严重错误**\n\n- **问题**: 无法从游戏回复中解析出元婴的当前状态。\n- **操作**: 已安排在30分钟后重试。\n- **原始文本**:\n`{reply_status.text}`")


    except CommandTimeoutError:
        format_and_log(LogType.WARNING, "元婴出窍", {'阶段': '任务异常', '原因': '游戏指令超时'})
        # 超时后15分钟重试
        next_run_time = datetime.now(beijing_tz) + timedelta(minutes=15)
        await client.send_admin_notification(f"⚠️ **元婴任务警报**\n\n- **问题**: 与游戏机器人通信超时。\n- **操作**: 已安排在15分钟后重试。")
        
    finally:
        # 4. 调度下一次任务
        scheduler.add_job(trigger_nascent_soul_egress, 'date', run_date=next_run_time, id=TASK_ID_NASCENT_SOUL, replace_existing=True)
        await data_manager.save_value(STATE_KEY_NASCENT_SOUL, next_run_time.isoformat())
        format_and_log(LogType.TASK, "元婴出窍", {'阶段': '任务完成', '下次调度时间': next_run_time.strftime('%Y-%m-%d %H:%M:%S')})
        if force_run:
            return f"✅ **[立即出窍]** 任务已成功触发。下次自动检查时间: `{next_run_time.strftime('%H:%M:%S')}`"

async def check_nascent_soul_startup():
    """启动时检查并调度元婴出窍任务"""
    if not settings.TASK_SWITCHES.get('nascent_soul'):
        return

    if scheduler.get_job(TASK_ID_NASCENT_SOUL):
        return

    iso_str = await data_manager.get_value(STATE_KEY_NASCENT_SOUL)
    beijing_tz = pytz.timezone(settings.TZ)
    now = datetime.now(beijing_tz)
    
    state_time = None
    if iso_str:
        try:
            state_time = datetime.fromisoformat(iso_str).astimezone(beijing_tz)
        except ValueError:
            state_time = None
            
    # 如果有合法的未来执行时间，则使用它；否则，在1-2分钟内随机启动
    run_date = state_time if state_time and state_time > now else now + timedelta(seconds=random.randint(60, 120))
    
    scheduler.add_job(trigger_nascent_soul_egress, 'date', run_date=run_date, id=TASK_ID_NASCENT_SOUL, replace_existing=True)
    format_and_log(LogType.SYSTEM, "任务调度", {'任务': '自动元婴出窍', '状态': '已计划', '预计时间': run_date.strftime('%Y-%m-%d %H:%M:%S')})

def initialize(app):
    app.register_task(
        task_key="nascent_soul",
        function=trigger_nascent_soul_egress,
        command_name="立即出窍",
        help_text="立即执行一次元婴出窍的检查与派遣任务。"
    )
    app.startup_checks.append(check_nascent_soul_startup)
