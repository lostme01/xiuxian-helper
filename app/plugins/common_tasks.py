# -*- coding: utf-8 -*-
import logging
import random
import pytz
import asyncio
import inspect
from datetime import datetime, timedelta, date
from app.utils import parse_cooldown_time, read_state, write_state
from config import settings
from app.logger import format_and_log
from app.task_scheduler import scheduler

client = None

TASK_ID_BIGUAN = 'biguan_xiulian_task'
STATE_FILE_PATH_BIGUAN = f"{settings.DATA_DIR}/biguan.state"
TASK_ID_HEALTH_CHECK = 'bot_health_check_task'
HEALTH_CHECK_CMD = '.我的货摊'
TASK_ID_DIANMAO = 'zongmen_dianmao_task'
STATE_FILE_PATH_DIANMAO = f"{settings.DATA_DIR}/dianmao.state"

def initialize_tasks(tg_client):
    global client
    client = tg_client
    client.register_task("biguan", trigger_biguan_xiulian)
    client.register_task("dianmao", trigger_dianmao_chuangong)
    client.register_admin_command("闭关修炼", manual_trigger_wrapper, "强制触发一次闭关修炼任务。")
    client.register_admin_command("宗门点卯", manual_trigger_wrapper, "强制触发一次宗门点卯任务。")
    return [check_biguan_startup, check_dianmao_startup]

async def manual_trigger_wrapper(client, event, parts):
    command_map = {"闭关修炼": "biguan", "宗门点卯": "dianmao"}
    command_name = parts[0]
    task_key = command_map.get(command_name)
    if task_key and (task_func := client.task_plugins.get(task_key)):
        await event.reply(f"好的，已手动触发 **[{command_name}]** 任务。", parse_mode='md')
        task_params = inspect.signature(task_func).parameters
        if 'force_run' in task_params:
            format_and_log("TASK", "任务触发", {'任务名': command_name, '来源': '管理员强制触发'})
            asyncio.create_task(task_func(force_run=True))
        else:
            format_and_log("TASK", "任务触发", {'任务名': command_name, '来源': '管理员手动触发'})
            asyncio.create_task(task_func())

async def check_bot_health():
    format_and_log("TASK", "健康检查", {'状态': '开始检查机器人是否恢复...', '指令': HEALTH_CHECK_CMD})
    _sent, reply = await client.send_and_wait(HEALTH_CHECK_CMD)
    if reply is None:
        next_check_time = datetime.now(pytz.timezone(settings.TZ)) + timedelta(minutes=15)
        scheduler.add_job(check_bot_health, 'date', run_date=next_check_time, id=TASK_ID_HEALTH_CHECK, replace_existing=True)
        format_and_log("TASK", "健康检查", {'状态': '机器人仍未响应', '下次检查': next_check_time.strftime('%H:%M:%S')}, level=logging.WARNING)
    else:
        format_and_log("TASK", "健康检查", {'状态': '机器人已恢复，将立即恢复主任务'})
        asyncio.create_task(trigger_biguan_xiulian())

async def trigger_biguan_xiulian(force_run=False):
    format_and_log("TASK", "任务启动", {'任务名': '闭关修炼'})
    _sent_msg, reply = await client.send_and_wait(".闭关修炼")
    beijing_tz = pytz.timezone(settings.TZ)
    if reply is None:
        next_check_time = datetime.now(beijing_tz) + timedelta(minutes=15)
        scheduler.add_job(check_bot_health, 'date', run_date=next_check_time, id=TASK_ID_HEALTH_CHECK, replace_existing=True)
        format_and_log("TASK", "任务失败", {'任务名': '闭关修炼', '原因': '等待回复超时，转入健康检查模式'}, level=logging.ERROR)
        return

    cooldown = parse_cooldown_time(reply.text)
    next_run_time = datetime.now(beijing_tz)
    if cooldown is None:
        next_run_time += timedelta(hours=1)
        format_and_log("TASK", "任务警告", {'任务名': '闭关修炼', '原因': '未能解析冷却时间，1小时后重试'}, level=logging.WARNING)
    else:
        next_run_time += cooldown + timedelta(seconds=random.uniform(30, 90))
        format_and_log("TASK", "任务成功", {'任务名': '闭关修炼', '解析冷却': str(cooldown), '下次执行': next_run_time.strftime('%Y-%m-%d %H:%M:%S')})
    
    scheduler.add_job(trigger_biguan_xiulian, 'date', run_date=next_run_time, id=TASK_ID_BIGUAN, replace_existing=True)
    write_state(STATE_FILE_PATH_BIGUAN, next_run_time.isoformat())

async def trigger_dianmao_chuangong(force_run=False):
    beijing_tz = pytz.timezone(settings.TZ)
    today_str = date.today().isoformat()
    if not force_run and read_state(STATE_FILE_PATH_DIANMAO) == today_str:
        format_and_log("TASK", "任务跳过", {'任务名': '宗门点卯', '原因': '今日已执行'}, level=logging.INFO)
        return

    format_and_log("TASK", "任务启动", {'任务名': '宗门点卯'})
    sent_dianmao_msg, dianmao_reply = await client.send_and_wait(".宗门点卯")
    if dianmao_reply is None:
        next_run_time = datetime.now(beijing_tz) + timedelta(hours=1)
        scheduler.add_job(trigger_dianmao_chuangong, 'date', run_date=next_run_time, id=TASK_ID_DIANMAO, replace_existing=True)
        format_and_log("TASK", "任务失败", {'任务名': '宗门点卯', '原因': '等待回复超时，1小时后重试'}, level=logging.WARNING)
        return

    if "已经点过卯" not in dianmao_reply.text and "今天已经点过卯" not in dianmao_reply.text:
        format_and_log("TASK", "任务进度", {'任务名': '宗门点卯', '详情': '点卯成功，开始传功...'})
        for i in range(3):
            await client.send_and_wait(".宗门传功", reply_to=sent_dianmao_msg.id)
            if i < 2: await asyncio.sleep(random.uniform(30, 50))
    
    write_state(STATE_FILE_PATH_DIANMAO, today_str)
    tomorrow = (datetime.now(beijing_tz) + timedelta(days=1)).date()
    run_time = beijing_tz.localize(datetime.combine(tomorrow, datetime.min.time())) + timedelta(hours=8, minutes=random.randint(0, 30))
    scheduler.add_job(trigger_dianmao_chuangong, 'date', run_date=run_time, id=TASK_ID_DIANMAO, replace_existing=True)
    format_and_log("TASK", "任务成功", {'任务名': '宗门点卯', '下次执行': run_time.strftime('%Y-%m-%d %H:%M:%S')})

async def check_biguan_startup():
    if scheduler.get_job(TASK_ID_BIGUAN) or scheduler.get_job(TASK_ID_HEALTH_CHECK): return
    iso_str = read_state(STATE_FILE_PATH_BIGUAN)
    state_time = datetime.fromisoformat(iso_str).astimezone(pytz.timezone(settings.TZ)) if iso_str else None
    if state_time and state_time > datetime.now(pytz.timezone(settings.TZ)):
        scheduler.add_job(trigger_biguan_xiulian, 'date', run_date=state_time, id=TASK_ID_BIGUAN)
    else: asyncio.create_task(trigger_biguan_xiulian())

async def check_dianmao_startup():
    if scheduler.get_job(TASK_ID_DIANMAO): return
    beijing_tz = pytz.timezone(settings.TZ)
    if read_state(STATE_FILE_PATH_DIANMAO) == date.today().isoformat():
        tomorrow = (datetime.now(beijing_tz) + timedelta(days=1)).date()
        run_time = beijing_tz.localize(datetime.combine(tomorrow, datetime.min.time())) + timedelta(hours=8, minutes=random.randint(0, 30))
        scheduler.add_job(trigger_dianmao_chuangong, 'date', run_date=run_time, id=TASK_ID_DIANMAO, replace_existing=True)
    else: asyncio.create_task(trigger_dianmao_chuangong())
