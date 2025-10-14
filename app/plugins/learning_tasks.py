# -*- coding: utf-8 -*-
import logging
import random
import pytz
import asyncio
import re
from datetime import datetime, timedelta
from config import settings
from app.logging_service import LogType, format_and_log
from app.task_scheduler import scheduler
from app.telegram_client import CommandTimeoutError
from app.context import get_application
from app.utils import resilient_task
from app import game_adaptor
from app.data_manager import data_manager
from app.inventory_manager import inventory_manager
from app.constants import STATE_KEY_LEARNED_RECIPES
from app.plugins.common_tasks import update_inventory_cache

TASK_ID_LEARN_RECIPES = 'learn_recipes_task'

@resilient_task()
async def trigger_learn_recipes(force_run=False):
    """
    [v3.1 最终统一版]
    - 使用更健壮的正则表达式，正确解析 .炼制 指令的返回内容。
    - 严格遵循统一的命名标准。
    """
    app = get_application()
    client = app.client
    format_and_log(LogType.TASK, "自动学习", {'阶段': '任务开始', '强制执行': force_run})

    # --- 第一阶段：同步权威知识库 ---
    try:
        _sent_msg, reply = await client.send_game_command_request_response(game_adaptor.get_crafting_list())
        
        # [核心修复 v3.1] 使用新的正则表达式来匹配 "- **物品名** (来自: ...)" 格式
        # 这个表达式会查找以"- "开头，后跟两个星号，然后捕获直到下一个星号对的所有内容
        # [BUG 修正] 对解析出的每个名称进行 strip() 清理，防止因空格导致不匹配
        learned_from_command_raw = re.findall(r'-\s*\*\*([^\*]+)\*\*', reply.text)
        learned_from_command = {name.strip() for name in learned_from_command_raw}
        
        # 作为备用，如果上面的正则没匹配到，尝试旧的【】格式
        if not learned_from_command:
            learned_from_command_raw = re.findall(r'【([^】]+)】', reply.text)
            learned_from_command = {name.strip() for name in learned_from_command_raw}


    except (CommandTimeoutError, ValueError):
        format_and_log(LogType.ERROR, "自动学习", {'阶段': '任务中止', '原因': '无法从游戏获取或解析可炼制列表。'})
        return

    # 将权威的【物品名称】列表存入数据库
    await data_manager.save_value(STATE_KEY_LEARNED_RECIPES, sorted(list(learned_from_command)))
    format_and_log(LogType.TASK, "自动学习", {'阶段': '同步权威知识库', '当前已知配方总数': len(learned_from_command)})
    
    # --- 第二阶段：决策 ---
    inventory = await inventory_manager.get_inventory()
    if not inventory:
        format_and_log(LogType.TASK, "自动学习", {'阶段': '任务跳过', '原因': '背包缓存为空'})
        return
    
    recipes_to_learn = []
    for item in inventory:
        if item.endswith(("图纸", "丹方")):
            # 从图纸名推断出【物品名称】
            # [BUG 修正] 对推导出的基础物品名进行 strip() 清理
            base_item_name = item.replace("图纸", "").replace("丹方", "").strip()
            # 用【物品名称】去比对权威列表
            if base_item_name not in learned_from_command:
                recipes_to_learn.append(item)

    if not recipes_to_learn:
        format_and_log(LogType.TASK, "自动学习", {'阶段': '任务完成', '详情': '没有需要新学习的图纸或丹方。'})
        return
        
    format_and_log(LogType.TASK, "自动学习", {'阶段': '开始学习', '待学列表': str(recipes_to_learn)})

    # --- 第三阶段：执行与即时记录 ---
    jitter_config = settings.TASK_JITTER['learn_recipes']
    newly_learned_in_session = False
    
    for recipe in recipes_to_learn:
        try:
            format_and_log(LogType.TASK, "自动学习", {'阶段': '发送学习指令', '物品': recipe})
            # 发送学习指令时，使用【丹方/图纸全名】
            command = game_adaptor.learn_recipe(recipe)
            _sent_learn, reply_learn = await client.send_game_command_request_response(command, timeout=10)
            
            if "成功领悟了它的炼制之法" in reply_learn.text:
                # 学习成功后，将【物品名称】加入内存中的权威列表
                base_item_name = recipe.replace("图纸", "").replace("丹方", "").strip()
                format_and_log(LogType.TASK, "自动学习-知识库更新", {'阶段': '学习成功', '物品': base_item_name})
                learned_from_command.add(base_item_name)
                newly_learned_in_session = True
            
            elif "你的储物袋中没有此物可供学习" in reply_learn.text or f"你的储物袋中没有【{recipe}】" in reply_learn.text:
                format_and_log(LogType.WARNING, "自动学习", {'阶段': '缓存不一致', '问题': f"缓存显示有 {recipe}，但实际没有。"})
                await client.send_admin_notification(f"⚠️ **缓存不一致警告 (自动学习)**\n\n- **问题**: 缓存显示有`{recipe}`，但实际背包中没有。\n- **操作**: 正在触发一次背包强制同步以进行自我修正。")
                await update_inventory_cache(force_run=True)
                format_and_log(LogType.TASK, "自动学习", {'阶段': '任务中止', '原因': '已触发背包校准，等待下个周期。'})
                break

            else:
                 format_and_log(LogType.WARNING, "自动学习", {'阶段': '学习未成功或已学会', '物品': recipe, '返回': reply_learn.text.strip()})

        except CommandTimeoutError:
            format_and_log(LogType.TASK, "自动学习", {'阶段': '学习超时', '物品': recipe}, level=logging.WARNING)
            continue
        finally:
            delay = random.uniform(jitter_config['min'], jitter_config['max'])
            await asyncio.sleep(delay)
    
    if newly_learned_in_session:
        # 任务结束时，将更新后的权威列表存回数据库
        await data_manager.save_value(STATE_KEY_LEARNED_RECIPES, sorted(list(learned_from_command)))
        format_and_log(LogType.TASK, "自动学习", {'阶段': '任务完成', '详情': '已将新学配方持久化至知识库。'})
    else:
        format_and_log(LogType.TASK, "自动学习", {'阶段': '任务完成', '详情': '所有可学物品均已尝试或任务已中止。'})


async def check_learn_recipes_startup():
    if settings.TASK_SWITCHES.get('learn_recipes'):
        # 立即执行一次以清理旧数据
        await trigger_learn_recipes(force_run=True)
        scheduler.add_job(
            trigger_learn_recipes, 'interval', hours=random.randint(4, 6), 
            id=TASK_ID_LEARN_RECIPES, 
            next_run_time=datetime.now(pytz.timezone(settings.TZ)) + timedelta(minutes=5),
            replace_existing=True
        )

def initialize(app):
    app.register_task(
        task_key="learn_recipes",
        function=trigger_learn_recipes,
        command_name="立即学习",
        help_text="立即检查并学习背包中的图纸和丹方。"
    )
    app.startup_checks.append(check_learn_recipes_startup)
