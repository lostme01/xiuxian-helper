# -*- coding: utf-8 -*-
import pytz
import asyncio
from config import settings
from app.task_scheduler import scheduler
from app.utils import LOG_TYPE_MAP_ZH_TO_EN
from app.config_manager import update_setting
from app.context import get_application

# --- 指令函数定义 ---

async def _cmd_task_list(client, event, parts):
    jobs = scheduler.get_jobs()
    if not jobs:
        await event.reply("当前没有正在计划中的任务。")
        return
    job_map = {'biguan_xiulian_task': '闭关修炼', 'heartbeat_check_task': '被动心跳', 'active_status_heartbeat_task': '主动心跳', 'zongmen_dianmao_task': '宗门点卯', 'taiyi_yindao_task': '太一门·引道', 'huangfeng_garden_task': '黄枫谷·小药园', 'inventory_refresh_task': '刷新背包', 'learn_recipes_task': '学习图纸丹方', 'chuang_ta_task_1': '自动闯塔 (1)', 'chuang_ta_task_2': '自动闯塔 (2)'}
    beijing_tz = pytz.timezone(settings.TZ)
    reply_text = "🗓️ **当前计划任务列表**:\n"
    for job in jobs:
        if job.id.startswith('delete_msg_'): continue
        job_name = job_map.get(job.id, job.id)
        if job.next_run_time:
            next_run = job.next_run_time.astimezone(beijing_tz).strftime('%Y-%m-%d %H:%M:%S')
            reply_text += f"\n- **{job_name}**\n  `下次运行:` {next_run}"
    await event.reply(reply_text, parse_mode='md')

async def _cmd_toggle_log(client, event, parts):
    if len(parts) < 2:
        status_text = "**各模块日志开关状态**:\n"
        en_to_zh_map = {v: k for k, v in LOG_TYPE_MAP_ZH_TO_EN.items()}
        for key_en, value in settings.LOGGING_SWITCHES.items():
            key_zh = en_to_zh_map.get(key_en, key_en)
            status_text += f"- **{key_zh}**: **{'开启' if value else '关闭'}**\n"
        await event.reply(status_text, parse_mode='md')
        return
    if len(parts) != 3 or parts[2] not in ["开", "关"]:
        await event.reply(f"用法: `{settings.COMMAND_PREFIXES[0]}日志开关 <类型> <开|关>`", parse_mode='md')
        return
    log_type, switch = parts[1], parts[2]
    log_type_en = LOG_TYPE_MAP_ZH_TO_EN.get(log_type)
    if not log_type_en:
        await event.reply(f"❌ 错误: 未知的日志类型 '{log_type}'。")
        return
    new_status = (switch == "开")
    response_msg = update_setting(root_key='logging_switches', sub_key=log_type_en, value=new_status, success_message=f"**{log_type}** 日志已 **{switch}**")
    await event.reply(response_msg, parse_mode='md')

async def _generic_task_trigger(client, event, parts, task_map):
    command_name = parts[0]
    task_key = task_map.get(command_name)
    app = get_application()
    if task_key and (task_func := app.client.task_plugins.get(task_key)):
        progress_message = await event.reply(f"⏳ 好的，正在手动执行 **[{command_name}]** 任务...", parse_mode='md')
        try:
            await task_func(force_run=True)
            await progress_message.edit(f"✅ **[{command_name}]** 任务已成功执行完毕。")
        except Exception as e:
            await progress_message.edit(f"❌ **[{command_name}]** 任务在执行过程中发生错误: `{e}`")
    else:
        await event.reply(f"❌ 错误: 未找到与 `{command_name}` 关联的任务。")

async def _cmd_trigger_common_task(client, event, parts):
    task_map = {"立即闭关": "biguan", "立即点卯": "dianmao", "立即闯塔": "chuang_ta", "立即刷新背包": "update_inventory"}
    await _generic_task_trigger(client, event, parts, task_map)

async def _cmd_trigger_learning_task(client, event, parts):
    task_map = {"立即学习": "learn_recipes"}
    await _generic_task_trigger(client, event, parts, task_map)

async def _cmd_trigger_sect_task(client, event, parts):
    task_map = {"立即药园": "xiaoyaoyuan", "立即引道": "yindao"}
    await _generic_task_trigger(client, event, parts, task_map)

async def _cmd_toggle_task(client, event, parts):
    task_map = {
        '玄骨': ('玄骨校考', 'exam_solver', 'enabled'),
        '天机': ('天机考验', 'tianji_exam_solver', 'enabled'),
        '闭关': ('闭关修炼', 'task_switches', 'biguan'),
        '点卯': ('宗门点卯', 'task_switches', 'dianmao'),
        '学习': ('自动学习', 'task_switches', 'learn_recipes'),
        '药园': ('自动药园', 'task_switches', 'garden_check'),
        '背包': ('自动刷新背包', 'task_switches', 'inventory_refresh'),
        '魔君': ('魔君降临事件', 'task_switches', 'mojun_arrival'),
        # --- 核心新增：添加“自动删除”插件的开关 ---
        '自动删除': ('消息自动删除', 'auto_delete', 'enabled'),
    }

    if len(parts) < 2:
        available_tasks = ' '.join([f"`{name}`" for name in sorted(task_map.keys())])
        help_text = (
            f"**用法**: `{settings.COMMAND_PREFIXES[0]}任务开关 <任务名> [<开|关>]`\n\n"
            "**`<任务名>` 可选项**:\n"
            f"{available_tasks}"
        )
        await event.reply(help_text, parse_mode='md')
        return

    task_name = parts[1]
    if task_name not in task_map:
        await event.reply(f"❌ 错误: 未知的任务名 '{task_name}'。")
        return
    
    friendly_name, root_key, sub_key = task_map[task_name]
    
    if len(parts) == 2:
        current_value = None
        # 根据 root_key 从不同的配置字典中获取值
        if root_key == 'task_switches': current_value = settings.TASK_SWITCHES.get(sub_key)
        elif root_key == 'exam_solver': current_value = settings.EXAM_SOLVER_CONFIG.get(sub_key)
        elif root_key == 'tianji_exam_solver': current_value = settings.TIANJI_EXAM_CONFIG.get(sub_key)
        elif root_key == 'auto_delete': current_value = settings.AUTO_DELETE.get(sub_key)
        
        status_str = "开启" if current_value else "关闭"
        await event.reply(f"当前 **{friendly_name}** 功能状态: **{status_str}**", parse_mode='md')
        return
        
    if len(parts) == 3 and parts[2] in ["开", "关"]:
        switch = parts[2]
        new_status = (switch == "开")
        response_msg = update_setting(root_key=root_key, sub_key=sub_key, value=new_status, success_message=f"**{friendly_name}** 功能已 **{switch}**")
        await event.reply(response_msg, parse_mode='md')
    else:
        await event.reply(f"用法: `{settings.COMMAND_PREFIXES[0]}任务开关 <任务名> <开|关>`", parse_mode='md')

# --- 指令注册中心 ---
def initialize_all_commands(client):
    """在此函数中注册所有游戏相关的指令"""
    client.register_admin_command("帮助", None, "ℹ️ 显示此帮助菜单。", category="系统管理", aliases=["help"])
    client.register_admin_command("任务列表", _cmd_task_list, "🗓️ 查询计划中的任务。", category="系统管理", aliases=["tasks"])
    client.register_admin_command("日志开关", _cmd_toggle_log, "📝 查看或设置日志模块开关。", category="系统管理")
    client.register_admin_command("任务开关", _cmd_toggle_task, "🔧 查看或设置后台任务开关。", category="系统管理")
    
    client.register_admin_command("立即闭关", _cmd_trigger_common_task, "立即执行一次闭关。", category="游戏任务")
    client.register_admin_command("立即点卯", _cmd_trigger_common_task, "立即执行一次宗门点卯。", category="游戏任务")
    client.register_admin_command("立即闯塔", _cmd_trigger_common_task, "立即执行一次闯塔。", category="游戏任务")
    client.register_admin_command("立即刷新背包", _cmd_trigger_common_task, "立即刷新背包缓存。", category="游戏任务")
    client.register_admin_command("立即学习", _cmd_trigger_learning_task, "立即执行学习图纸任务。", category="游戏任务")
    
    if settings.SECT_NAME == '黄枫谷':
        client.register_admin_command("立即药园", _cmd_trigger_sect_task, "立即检查药园 (黄枫谷)。", category="游戏任务")
    elif settings.SECT_NAME == '太一门':
        client.register_admin_command("立即引道", _cmd_trigger_sect_task, "立即执行引道 (太一门)。", category="游戏任务")
