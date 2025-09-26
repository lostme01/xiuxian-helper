# -*- coding: utf-8 -*-
import logging
import random
import pytz
import asyncio
import inspect
import re
from datetime import datetime, timedelta
from app.utils import read_json_state, write_json_state
from config import settings
from app.logger import format_and_log
from app.task_scheduler import scheduler

client = None

# --- 任务ID与状态文件路径 ---
TASK_ID_LEARN_RECIPES = 'learn_recipes_task'
STATE_FILE_PATH_LEARNED = f"{settings.DATA_DIR}/learned_recipes.json"
INVENTORY_FILE_PATH = f"{settings.DATA_DIR}/inventory.json"

def initialize_tasks(tg_client):
    """初始化学习任务插件"""
    global client
    client = tg_client
    client.register_task("learn_recipes", trigger_learn_recipes)
    client.register_admin_command("学习图纸", manual_trigger_learn_recipes, "手动触发一次图纸丹方学习检查。")
    return [check_learn_recipes_startup]

async def manual_trigger_learn_recipes(client, event, parts):
    """手动触发指令的处理函数"""
    format_and_log("TASK", "任务触发", {'任务名': '学习图纸', '来源': '管理员手动触发'})
    await event.reply("好的，已手动触发 **[学习图纸]** 任务。", parse_mode='md')
    asyncio.create_task(trigger_learn_recipes())

def _parse_learned_recipes(reply_text: str) -> list[str]:
    """
    优化：从 .炼制 回复中更精确地解析出已学习的图纸和丹方名称。
    例如，从 "- **增元丹** (来自: 增元丹丹方)" 中提取 "增元丹丹方"。
    """
    learned = []
    # 匹配 (来自: xxx图纸) 或 (来自: xxx丹方) 中的内容
    pattern = re.compile(r'\(来自:\s*([^)]*(?:图纸|丹方))\)')
    for line in reply_text.split('\n'):
        if match := pattern.search(line):
            learned.append(match.group(1).strip())
    return learned

async def trigger_learn_recipes():
    """核心任务：检查并学习新的图纸和丹方"""
    format_and_log("TASK", "任务启动", {'任务名': '学习图纸丹方'})
    
    # 1. 获取并更新已学习列表的缓存
    _sent_msg, reply = await client.send_and_wait(".炼制")
    if not reply:
        format_and_log("TASK", "任务失败", {'任务名': '学习图纸丹方', '原因': '获取已学习列表超时'}, level=logging.WARNING)
        return
        
    learned_recipes = _parse_learned_recipes(reply.text)
    write_json_state(STATE_FILE_PATH_LEARNED, learned_recipes)
    format_and_log("TASK", "任务进度", {'任务名': '学习图纸丹方', '详情': f"已更新缓存，当前已学习 {len(learned_recipes)} 种。"})

    # 2. 读取储物袋缓存
    inventory = read_json_state(INVENTORY_FILE_PATH) or {}
    if not inventory:
        format_and_log("TASK", "任务跳过", {'任务名': '学习图纸丹方', '原因': '储物袋缓存为空'})
        return
        
    # 3. 找出所有未学习的图纸和丹方
    recipes_to_learn = []
    for item, quantity in inventory.items():
        if quantity > 0 and item.endswith(("图纸", "丹方")):
            if item not in learned_recipes:
                recipes_to_learn.append(item)
    
    # 4. 执行学习指令
    if not recipes_to_learn:
        format_and_log("TASK", "任务成功", {'任务名': '学习图纸丹方', '详情': '无需学习新内容'})
        return
        
    format_and_log("TASK", "任务进度", {'任务名': '学习图纸丹方', '详情': f"发现 {len(recipes_to_learn)} 个新项目，开始学习..."})
    for recipe in recipes_to_learn:
        learn_command = f".学习 {recipe}"
        format_and_log("TASK", "执行学习", {'指令': learn_command})
        
        _learn_sent, learn_reply = await client.send_and_wait(learn_command)
        
        # 优化：更精确地判断学习结果
        if learn_reply and "成功领悟" in learn_reply.text:
            format_and_log("TASK", "学习成功", {'项目': recipe})
            # 更新背包缓存
            current_inventory = read_json_state(INVENTORY_FILE_PATH) or {}
            if recipe in current_inventory:
                current_inventory[recipe] -= 1
                if current_inventory[recipe] <= 0:
                    del current_inventory[recipe]
                write_json_state(INVENTORY_FILE_PATH, current_inventory)
            
            # 更新知识缓存
            current_learned = read_json_state(STATE_FILE_PATH_LEARNED) or []
            if recipe not in current_learned:
                current_learned.append(recipe)
                write_json_state(STATE_FILE_PATH_LEARNED, current_learned)
        
        elif learn_reply and "早已学会" in learn_reply.text:
             format_and_log("TASK", "学习跳过", {'项目': recipe, '原因': '机器人返回早已学会'})
             # 知识库可能不一致，更新知识库
             current_learned = read_json_state(STATE_FILE_PATH_LEARNED) or []
             if recipe not in current_learned:
                current_learned.append(recipe)
                write_json_state(STATE_FILE_PATH_LEARNED, current_learned)

        elif learn_reply and "没有此物" in learn_reply.text:
            format_and_log("TASK", "学习跳过", {'项目': recipe, '原因': '物品不存在，自动修正本地缓存'})
            # 自我修正：从背包缓存中移除该物品
            current_inventory = read_json_state(INVENTORY_FILE_PATH) or {}
            if recipe in current_inventory:
                del current_inventory[recipe]
                write_json_state(INVENTORY_FILE_PATH, current_inventory)
        else:
            format_and_log("TASK", "学习失败", {'项目': recipe, '原因': '未收到明确的成功或失败回复'}, level=logging.WARNING)
        
        await asyncio.sleep(random.uniform(3, 7))
        
    format_and_log("TASK", "任务成功", {'任务名': '学习图纸丹方', '详情': f"学习流程执行完毕"})

async def check_learn_recipes_startup():
    """启动时检查并创建周期性学习任务"""
    if not scheduler.get_job(TASK_ID_LEARN_RECIPES):
        hours = random.randint(4, 6)
        minutes = random.randint(0, 59)
        scheduler.add_job(trigger_learn_recipes, 'interval', hours=hours, minutes=minutes, id=TASK_ID_LEARN_RECIPES, 
                          next_run_time=datetime.now(pytz.timezone(settings.TZ)) + timedelta(minutes=5))
        format_and_log("SYSTEM", "启动检查", {'任务名': '学习图纸丹方', '状态': f'已安排周期性检查 (约{hours}小时{minutes}分钟/次)'})
