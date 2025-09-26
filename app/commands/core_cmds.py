# -*- coding: utf-8 -*-
import sys
import pytz
from config import settings
from app.task_scheduler import scheduler

HELP_DETAILS = {
    "帮助": "获取指令帮助。\n用法: `,帮助 [指令名]`",
    "重启": "优雅地关闭并重启整个助手服务。",
    "任务列表": "查询当前所有正在计划中的定时任务。",
}

async def _cmd_help(client, event, parts):
    known_commands = sorted(list(client.admin_commands.keys()))
    prefix = settings.COMMAND_PREFIXES[0] if settings.COMMAND_PREFIXES else ','

    if len(parts) > 1:
        sub_command_match = [cmd for cmd in known_commands if cmd.startswith(parts[1])]
        if len(sub_command_match) == 1:
            sub_command = sub_command_match[0]
            detail = client.admin_commands[sub_command]['help']
            await event.reply(f"**指令详情: `{prefix}{sub_command}`**\n\n{detail}", parse_mode='md')
        else:
            await event.reply(f"找不到指令 `{parts[1]}` 的详细帮助。")
    else:
        groups = {"任务触发指令": [], "系统配置指令": []}
        # *** 更新：增加关键词 ***
        trigger_keywords = ["修炼", "点卯", "引道", "药园", "背包", "学习", "闯塔"]
        
        for cmd in known_commands:
            formatted_cmd = f"`{prefix}{cmd}`"
            if any(keyword in cmd for keyword in trigger_keywords):
                groups["任务触发指令"].append(formatted_cmd)
            else:
                groups["系统配置指令"].append(formatted_cmd)
        
        help_text = "*助手指令菜单*"
        for title, cmd_list in groups.items():
            if cmd_list:
                help_text += f"\n\n*{title}*\n{' '.join(cmd_list)}"
        
        await event.reply(help_text, parse_mode='md')

async def _cmd_restart(client, event, parts):
    await event.reply("好的，正在为您安排重启服务，请在10秒后查看日志确认。")
    sys.exit(0)

async def _cmd_task_list(client, event, parts):
    jobs = scheduler.get_jobs()
    if not jobs:
        await event.reply("当前没有正在计划中的任务。")
        return
    job_map = {
        'biguan_xiulian_task': '闭关修炼',
        'bot_health_check_task': '机器人健康检查',
        'zongmen_dianmao_task': '宗门点卯',
        'taiyi_yindao_task': '太一门·引道',
        'huangfeng_garden_task': '黄枫谷·小药园检查',
        'inventory_refresh_task': '黄枫谷·背包刷新',
        'learn_recipes_task': '学习图纸丹方',
        # *** 新增：闯塔任务的名称映射 ***
        'chuang_ta_task_1': '自动闯塔 (第1次)',
        'chuang_ta_task_2': '自动闯塔 (第2次)',
    }
    beijing_tz = pytz.timezone(settings.TZ)
    reply_text = "*当前计划任务列表:*\n"
    for job in jobs:
        if job.id.startswith('delete_msg_'): continue
        job_name = job_map.get(job.id, job.id)
        if job.next_run_time:
            next_run = job.next_run_time.astimezone(beijing_tz).strftime('%Y-%m-%d %H:%M:%S')
            reply_text += f"\n- *{job_name}*\n  `下次运行:` {next_run}"
    await event.reply(reply_text, parse_mode='md')

def initialize_commands(client):
    client.register_admin_command("帮助", _cmd_help, HELP_DETAILS["帮助"])
    client.register_admin_command("重启", _cmd_restart, HELP_DETAILS["重启"])
    client.register_admin_command("任务列表", _cmd_task_list, HELP_DETAILS["任务列表"])
