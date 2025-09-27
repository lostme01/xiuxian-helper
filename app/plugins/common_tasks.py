# -*- coding: utf-8 -*-
import logging
import random
import pytz
import asyncio
import inspect
from datetime import datetime, timedelta, date, time
from app.utils import (
    parse_cooldown_time, read_state, write_state, 
    read_json_state, write_json_state, parse_inventory_text
)
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
TASK_ID_CHUANG_TA_1 = 'chuang_ta_task_1'
TASK_ID_CHUANG_TA_2 = 'chuang_ta_task_2'
STATE_FILE_PATH_CHUANG_TA = f"{settings.DATA_DIR}/chuang_ta.json"
# *** 新增：刷新背包相关的常量移至此处 ***
TASK_ID_INVENTORY_REFRESH = 'inventory_refresh_task'
INVENTORY_FILE_PATH = f"{settings.DATA_DIR}/inventory.json"


def initialize_tasks(tg_client):
    global client
    client = tg_client
    # 注册后台任务
    client.register_task("biguan", trigger_biguan_xiulian)
    client.register_task("dianmao", trigger_dianmao_chuangong)
    client.register_task("chuang_ta", trigger_chuang_ta)
    client.register_task("update_inventory", update_inventory_cache) # *** 新增 ***
    
    # 注册管理员指令
    client.register_admin_command("闭关修炼", manual_trigger_wrapper, "强制触发一次闭关修炼任务。")
    client.register_admin_command("宗门点卯", manual_trigger_wrapper, "强制触发一次宗门点卯任务。")
    client.register_admin_command("闯塔", manual_trigger_wrapper, "手动触发一次闯塔任务。")
    client.register_admin_command("刷新背包", manual_trigger_wrapper, "强制查询并更新本地的储物袋物品缓存。") # *** 新增 ***

    return [check_biguan_startup, check_dianmao_startup, check_chuang_ta_startup, check_inventory_refresh_startup] # *** 新增 ***

async def manual_trigger_wrapper(client, event, parts):
    # *** 更新：增加对新指令的支持 ***
    command_map = {
        "闭关修炼": "biguan", 
        "宗门点卯": "dianmao", 
        "闯塔": "chuang_ta",
        "刷新背包": "update_inventory"
    }
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

# --- 新增：刷新背包功能 ---
async def update_inventory_cache():
    format_and_log("TASK", "任务启动", {'任务名': '刷新背包'})
    _sent, reply = await client.send_and_wait(".储物袋")
    if reply:
        inventory = parse_inventory_text(reply.text)
        format_and_log("TASK", "任务进度", {'任务名': '刷新背包', '详情': f"从回复中解析出 {len(inventory)} 种物品"})
        if inventory:
            write_json_state(INVENTORY_FILE_PATH, inventory)
            format_and_log("TASK", "任务成功", {'任务名': '刷新背包', '详情': '本地库存缓存已更新'})
    else:
        format_and_log("TASK", "任务失败", {'任务名': '刷新背包', '原因': '等待回复超时'}, level=logging.WARNING)

async def check_inventory_refresh_startup():
    if not settings.TASK_SWITCHES.get('inventory_refresh', True): # 默认为开启
        format_and_log("SYSTEM", "任务跳过", {'任务名': '自动刷新背包', '原因': '配置中已禁用'})
        return
    if not scheduler.get_job(TASK_ID_INVENTORY_REFRESH):
        scheduler.add_job(update_inventory_cache, 'interval', hours=6, jitter=3600, id=TASK_ID_INVENTORY_REFRESH)

# --- 其他任务 (闯塔, 闭关, 点卯, 健康检查等) 保持不变 ---
async def trigger_chuang_ta():
    format_and_log("TASK", "任务启动", {'任务名': '闯塔'})
    today_str = date.today().isoformat()
    state = read_json_state(STATE_FILE_PATH_CHUANG_TA) or {}
    if state.get("date") == today_str:
        state["count"] += 1
    else:
        state = {"date": today_str, "count": 1}
    write_json_state(STATE_FILE_PATH_CHUANG_TA, state)
    await client.send_command(".闯塔")
    format_and_log("TASK", "任务成功", {'任务名': '闯塔', '详情': f"已发送指令，这是今天的第 {state['count']} 次。"})

async def check_chuang_ta_startup():
    if not settings.TASK_SWITCHES.get('chuang_ta', True):
        format_and_log("SYSTEM", "任务跳过", {'任务名': '自动闯塔', '原因': '配置中已禁用'})
        return
    today_str = date.today().isoformat()
    state = read_json_state(STATE_FILE_PATH_CHUANG_TA) or {}
    job1_exists = scheduler.get_job(TASK_ID_CHUANG_TA_1)
    job2_exists = scheduler.get_job(TASK_ID_CHUANG_TA_2)
    if state.get("date") != today_str or not (job1_exists or job2_exists):
        if job1_exists: scheduler.remove_job(TASK_ID_CHUANG_TA_1)
        if job2_exists: scheduler.remove_job(TASK_ID_CHUANG_TA_2)
        beijing_tz = pytz.timezone(settings.TZ)
        now = datetime.now(beijing_tz)
        t1_hour = random.randint(8, 14)
        run_time1 = now.replace(hour=t1_hour, minute=random.randint(0, 59), second=random.randint(0, 59))
        t2_hour = random.randint(15, 23)
        run_time2 = now.replace(hour=t2_hour, minute=random.randint(0, 59), second=random.randint(0, 59))
        if run_time1 > now:
            scheduler.add_job(trigger_chuang_ta, 'date', run_date=run_time1, id=TASK_ID_CHUANG_TA_1)
        if run_time2 > now:
            scheduler.add_job(trigger_chuang_ta, 'date', run_date=run_time2, id=TASK_ID_CHUANG_TA_2)
        write_json_state(STATE_FILE_PATH_CHUANG_TA, {"date": today_str, "count": 0})

async def check_bot_health():
    _sent, reply = await client.send_and_wait(HEALTH_CHECK_CMD)
    if reply is None:
        scheduler.add_job(check_bot_health, 'date', run_date=datetime.now(pytz.timezone(settings.TZ)) + timedelta(minutes=15), id=TASK_ID_HEALTH_CHECK, replace_existing=True)
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
