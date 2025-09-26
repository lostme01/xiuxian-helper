# -*- coding: utf-8 -*-
import logging
import random
import pytz
import asyncio
import inspect
from datetime import datetime, timedelta, date, time
from app.utils import parse_cooldown_time, read_state, write_state, read_json_state, write_json_state
from config import settings
from app.logger import format_and_log
from app.task_scheduler import scheduler

client = None

# --- 常量定义 ---
TASK_ID_BIGUAN = 'biguan_xiulian_task'
STATE_FILE_PATH_BIGUAN = f"{settings.DATA_DIR}/biguan.state"
TASK_ID_HEALTH_CHECK = 'bot_health_check_task'
HEALTH_CHECK_CMD = '.我的货摊'
TASK_ID_DIANMAO = 'zongmen_dianmao_task'
STATE_FILE_PATH_DIANMAO = f"{settings.DATA_DIR}/dianmao.state"
# *** 新增：闯塔任务的常量 ***
TASK_ID_CHUANG_TA_1 = 'chuang_ta_task_1'
TASK_ID_CHUANG_TA_2 = 'chuang_ta_task_2'
STATE_FILE_PATH_CHUANG_TA = f"{settings.DATA_DIR}/chuang_ta.json"


def initialize_tasks(tg_client):
    global client
    client = tg_client
    # 注册后台任务
    client.register_task("biguan", trigger_biguan_xiulian)
    client.register_task("dianmao", trigger_dianmao_chuangong)
    client.register_task("chuang_ta", trigger_chuang_ta) # *** 新增 ***
    
    # 注册管理员指令
    client.register_admin_command("闭关修炼", manual_trigger_wrapper, "强制触发一次闭关修炼任务。")
    client.register_admin_command("宗门点卯", manual_trigger_wrapper, "强制触发一次宗门点卯任务。")
    client.register_admin_command("闯塔", manual_trigger_wrapper, "手动触发一次闯塔任务。") # *** 新增 ***

    return [check_biguan_startup, check_dianmao_startup, check_chuang_ta_startup] # *** 新增 ***

async def manual_trigger_wrapper(client, event, parts):
    # *** 更新：增加对新指令的支持 ***
    command_map = {"闭关修炼": "biguan", "宗门点卯": "dianmao", "闯塔": "chuang_ta"}
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

# --- 新功能：自动闯塔 ---

async def trigger_chuang_ta():
    """执行闯塔任务的核心函数"""
    format_and_log("TASK", "任务启动", {'任务名': '闯塔'})
    
    # 1. 更新状态
    today_str = date.today().isoformat()
    state = read_json_state(STATE_FILE_PATH_CHUANG_TA) or {}
    if state.get("date") == today_str:
        state["count"] += 1
    else:
        state = {"date": today_str, "count": 1}
    write_json_state(STATE_FILE_PATH_CHUANG_TA, state)
    
    # 2. 发送指令
    await client.send_command(".闯塔")
    format_and_log("TASK", "任务成功", {'任务名': '闯塔', '详情': f"已发送指令，这是今天的第 {state['count']} 次。"})

async def check_chuang_ta_startup():
    """启动时检查并规划一整天的闯塔任务"""
    if not settings.TASK_SWITCHES.get('chuang_ta', True): # 默认为开启
        format_and_log("SYSTEM", "任务跳过", {'任务名': '自动闯塔', '原因': '配置中已禁用'})
        return
        
    today_str = date.today().isoformat()
    state = read_json_state(STATE_FILE_PATH_CHUANG_TA) or {}
    
    # 如果状态是昨天的，或者没有任何今天的任务计划，则重新规划
    job1_exists = scheduler.get_job(TASK_ID_CHUANG_TA_1)
    job2_exists = scheduler.get_job(TASK_ID_CHUANG_TA_2)
    
    if state.get("date") != today_str or not (job1_exists or job2_exists):
        format_and_log("SYSTEM", "任务规划", {'任务名': '自动闯塔', '详情': '开始为今天规划两次任务...'})
        
        # 清理旧的可能的任务
        if job1_exists: scheduler.remove_job(TASK_ID_CHUANG_TA_1)
        if job2_exists: scheduler.remove_job(TASK_ID_CHUANG_TA_2)
        
        # 生成两个有间隔的随机时间
        beijing_tz = pytz.timezone(settings.TZ)
        now = datetime.now(beijing_tz)
        
        # 上半天随机时间 (08:00 - 14:00)
        t1_hour = random.randint(8, 14)
        t1_minute = random.randint(0, 59)
        run_time1 = now.replace(hour=t1_hour, minute=t1_minute, second=random.randint(0, 59))
        
        # 下半天随机时间 (15:00 - 23:00)
        t2_hour = random.randint(15, 23)
        t2_minute = random.randint(0, 59)
        run_time2 = now.replace(hour=t2_hour, minute=t2_minute, second=random.randint(0, 59))
        
        # 如果生成的时间已经过去，就跳过该任务的规划
        if run_time1 > now:
            scheduler.add_job(trigger_chuang_ta, 'date', run_date=run_time1, id=TASK_ID_CHUANG_TA_1)
            format_and_log("SYSTEM", "任务规划", {'任务名': '自动闯塔', '详情': f"第1次已安排在 {run_time1.strftime('%H:%M:%S')}"})
        else:
             format_and_log("SYSTEM", "任务规划", {'任务名': '自动闯塔', '详情': f"第1次执行时间 {run_time1.strftime('%H:%M:%S')} 已过，跳过"})

        if run_time2 > now:
            scheduler.add_job(trigger_chuang_ta, 'date', run_date=run_time2, id=TASK_ID_CHUANG_TA_2)
            format_and_log("SYSTEM", "任务规划", {'任务名': '自动闯塔', '详情': f"第2次已安排在 {run_time2.strftime('%H:%M:%S')}"})
        else:
            format_and_log("SYSTEM", "任务规划", {'任务名': '自动闯塔', '详情': f"第2次执行时间 {run_time2.strftime('%H:%M:%S')} 已过，跳过"})
            
        # 重置当天的状态
        write_json_state(STATE_FILE_PATH_CHUANG_TA, {"date": today_str, "count": 0})

# --- 现有通用任务 (保持不变) ---
async def check_bot_health():
    _sent, reply = await client.send_and_wait(HEALTH_CHECK_CMD)
    if reply is None:
        next_check_time = datetime.now(pytz.timezone(settings.TZ)) + timedelta(minutes=15)
        scheduler.add_job(check_bot_health, 'date', run_date=next_check_time, id=TASK_ID_HEALTH_CHECK, replace_existing=True)
    else: asyncio.create_task(trigger_biguan_xiulian())

async def trigger_biguan_xiulian(force_run=False):
    _sent_msg, reply = await client.send_and_wait(".闭关修炼")
    beijing_tz = pytz.timezone(settings.TZ)
    if reply is None:
        scheduler.add_job(check_bot_health, 'date', run_date=datetime.now(beijing_tz) + timedelta(minutes=15), id=TASK_ID_HEALTH_CHECK, replace_existing=True)
        return
    cooldown = parse_cooldown_time(reply.text)
    next_run_time = datetime.now(beijing_tz)
    if cooldown is None: next_run_time += timedelta(hours=1)
    else: next_run_time += cooldown + timedelta(seconds=random.uniform(30, 90))
    scheduler.add_job(trigger_biguan_xiulian, 'date', run_date=next_run_time, id=TASK_ID_BIGUAN, replace_existing=True)
    write_state(STATE_FILE_PATH_BIGUAN, next_run_time.isoformat())

async def trigger_dianmao_chuangong(force_run=False):
    beijing_tz = pytz.timezone(settings.TZ)
    today_str = date.today().isoformat()
    if not force_run and read_state(STATE_FILE_PATH_DIANMAO) == today_str: return
    sent_dianmao_msg, dianmao_reply = await client.send_and_wait(".宗门点卯")
    if dianmao_reply is None:
        scheduler.add_job(trigger_dianmao_chuangong, 'date', run_date=datetime.now(beijing_tz) + timedelta(hours=1), id=TASK_ID_DIANMAO, replace_existing=True)
        return
    if "已经点过卯" not in dianmao_reply.text:
        for i in range(3):
            await client.send_and_wait(".宗门传功", reply_to=sent_dianmao_msg.id)
            if i < 2: await asyncio.sleep(random.uniform(30, 50))
    write_state(STATE_FILE_PATH_DIANMAO, today_str)
    tomorrow = (datetime.now(beijing_tz) + timedelta(days=1)).date()
    run_time = beijing_tz.localize(datetime.combine(tomorrow, datetime.min.time())) + timedelta(hours=8, minutes=random.randint(0, 30))
    scheduler.add_job(trigger_dianmao_chuangong, 'date', run_date=run_time, id=TASK_ID_DIANMAO, replace_existing=True)

async def check_biguan_startup():
    if not settings.TASK_SWITCHES.get('biguan'): return
    if scheduler.get_job(TASK_ID_BIGUAN) or scheduler.get_job(TASK_ID_HEALTH_CHECK): return
    iso_str = read_state(STATE_FILE_PATH_BIGUAN)
    state_time = datetime.fromisoformat(iso_str).astimezone(pytz.timezone(settings.TZ)) if iso_str else None
    if state_time and state_time > datetime.now(pytz.timezone(settings.TZ)):
        scheduler.add_job(trigger_biguan_xiulian, 'date', run_date=state_time, id=TASK_ID_BIGUAN)
    else: asyncio.create_task(trigger_biguan_xiulian())

async def check_dianmao_startup():
    if not settings.TASK_SWITCHES.get('dianmao'): return
    if scheduler.get_job(TASK_ID_DIANMAO): return
    beijing_tz = pytz.timezone(settings.TZ)
    if read_state(STATE_FILE_PATH_DIANMAO) == date.today().isoformat():
        tomorrow = (datetime.now(beijing_tz) + timedelta(days=1)).date()
        run_time = beijing_tz.localize(datetime.combine(tomorrow, datetime.min.time())) + timedelta(hours=8, minutes=random.randint(0, 30))
        scheduler.add_job(trigger_dianmao_chuangong, 'date', run_date=run_time, id=TASK_ID_DIANMAO, replace_existing=True)
    else: asyncio.create_task(trigger_dianmao_chuangong())
