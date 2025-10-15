# -*- coding: utf-8 -*-
import asyncio
import random
from datetime import time

import pytz
from telethon.errors.rpcerrorlist import MessageEditTimeExpiredError

from app import game_adaptor
from app.context import get_application
from app.data_manager import data_manager
from app.logging_service import LogType, format_and_log
from app.task_scheduler import scheduler
from app.telegram_client import CommandTimeoutError
from app.utils import create_error_reply, progress_manager
from config import settings

STATE_KEY_PROFILE = "character_profile"
# [新增] 为任务定义一个唯一的ID
TASK_ID_PROFILE_UPDATE = "profile_daily_update_task"

HELP_TEXT_QUERY_PROFILE = """ T T T T**查询角色信息**
**说明**: 主动向游戏机器人查询最新的角色信息，并更新本地缓存。
**用法**: `,查询角色`
"""

def _format_profile_reply(profile_data: dict, title: str) -> str:
    display_map = [
        ("称号", "称号"), ("道号", "道号"), ("宗门", "宗门"), 
        ("境界", "境界"), ("修为", "修为"), ("灵根", "灵根"),
        ("丹毒", "丹毒"), ("杀戮", "杀戮")
    ]
    
    lines = [title]
    for key, display_name in display_map:
        if key in profile_data and profile_data[key] is not None:
            value = profile_data[key]
            if key == '修为' and '修为上限' in profile_data:
                upper_limit = profile_data.get('修为上限', 'N/A')
                lines.append(f"- **{display_name}**: `{value} / {upper_limit}`")
            else:
                 lines.append(f"- **{display_name}**: `{value}`")

    return "\n".join(lines)


async def trigger_update_profile(force_run=False):
    app = get_application()
    client = app.client
    command = game_adaptor.get_profile()
    
    try:
        # [修改] 使用新的、健壮的等待函数
        _sent, final_message = await client.send_and_wait_for_mention_reply(
            command=command,
            final_pattern=r"\*\*境界\*\*",
        )

        profile_data = game_adaptor.parse_profile(final_message.text)

        if not profile_data or not profile_data.get("境界"):
            format_and_log(LogType.ERROR, "角色信息解析失败", {'原始文本': final_message.text})
            raise ValueError(f"无法从最终返回的信息中解析出角色数据: {getattr(final_message, 'text', '无最终消息')}")

        await data_manager.save_value(STATE_KEY_PROFILE, profile_data)
        
        if force_run:
            return _format_profile_reply(profile_data, "✅ **角色信息已更新并缓存**:")

    except (CommandTimeoutError, asyncio.TimeoutError) as e:
        error_msg = f"等待游戏机器人响应或更新信息超时。"
        if force_run:
            return create_error_reply("查询角色", "游戏指令超时", details=error_msg)
        else:
            raise CommandTimeoutError(error_msg) from e
    except Exception as e:
        if force_run:
            return create_error_reply("查询角色", "任务执行异常", details=str(e))
        else:
            raise e


async def _cmd_query_profile(event, parts):
    async with progress_manager(event, "⏳ 正在发送指令并等待查询结果...") as progress:
        final_text = await trigger_update_profile(force_run=True)
        await progress.update(final_text)


async def _cmd_view_cached_profile(event, parts):
    profile_data = await data_manager.get_value(STATE_KEY_PROFILE, is_json=True)
    if not profile_data:
        await get_application().client.reply_to_admin(event, "ℹ️ 尚未缓存任何角色信息，请先使用 `,查询角色` 查询一次。")
        return
    reply_text = _format_profile_reply(profile_data, "📄 **已缓存的角色信息**:")
    await get_application().client.reply_to_admin(event, reply_text)

async def check_profile_update_startup():
    """[调度优化] 每日基础数据：每天凌晨4-5点之间随机执行一次"""
    if not scheduler.get_job(TASK_ID_PROFILE_UPDATE):
        run_time = time(hour=4, minute=random.randint(0, 59), tzinfo=pytz.timezone(settings.TZ))
        scheduler.add_job(
            trigger_update_profile, 'cron', 
            hour=run_time.hour, minute=run_time.minute, 
            id=TASK_ID_PROFILE_UPDATE, 
            jitter=600 # 增加10分钟随机抖动
        )
        format_and_log(LogType.SYSTEM, "任务调度", {'任务': '自动查询角色 (每日)', '状态': '已计划', '预计时间': run_time.strftime('%H:%M')})


def initialize(app):
    app.register_command(
        name="查询角色", 
        handler=_cmd_query_profile, 
        help_text=" T T T T查询并刷新当前角色的详细信息。", 
        category="查询信息",
        aliases=["我的灵根"],
        usage=HELP_TEXT_QUERY_PROFILE
    )
    # 保持旧指令的入口，但指向新的缓存查看功能
    app.register_command(
        "查看角色", 
        _cmd_view_cached_profile, 
        help_text="📄 查看已缓存的最新角色信息。", 
        category="数据查询" # 这个指令将被主菜单隐藏
    )
    # [新增] 将新的启动检查函数添加到启动项
    app.startup_checks.append(check_profile_update_startup)
