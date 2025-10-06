# -*- coding: utf-8 -*-
import re
import logging
import asyncio
import pytz
from datetime import datetime
from telethon.errors.rpcerrorlist import MessageEditTimeExpiredError
from config import settings
from app.logger import format_and_log
from app.context import get_application
from app.telegram_client import CommandTimeoutError
from app.utils import create_error_reply
from app import game_adaptor
from app.data_manager import data_manager

STATE_KEY_PROFILE = "character_profile"

PROFILE_PATTERN = re.compile(
    r"\*\*@([^\*]+)\*\*.*?天命玉牒.*?"
    r"(?:\*\*称号\*\*[:：]?\s*【?([^】\n]+)】?.*?)?"
    r"\*\*宗门\*\*[:：]?\s*[【]?([^】\n]+)[】]?\s*"
    r"\*\*道号\*\*[:：]?\s*([^\n]+)\s*"
    r"\*\*灵根\*\*[:：]?\s*([^\n]+)\s*"
    r"\*\*境界\*\*[:：]?\s*([^\n]+)\s*"
    r"\*\*修为\*\*[:：]?\s*(-?\d+)\s*/\s*(\d+)\s*"
    r"\*\*丹毒\*\*[:：]?\s*(-?\d+)\s*点.*?"
    r"(?:\*\*杀戮\*\*[:：]?\s*(\d+)\s*人.*?)?"
    , re.S | re.I
)

def _parse_profile_text(text: str) -> dict:
    match = PROFILE_PATTERN.search(text)
    format_and_log("DEBUG", "角色信息解析", {'正则表达式匹配成功': bool(match)})
    
    if not match:
        return {}
    
    groups = match.groups()
    
    profile_data = {
        "用户": groups[0], "称号": groups[1], "宗门": groups[2], "道号": groups[3],
        "灵根": groups[4], "境界": groups[5], "修为": int(groups[6]), "修为上限": int(groups[7]),
        "丹毒": int(groups[8]), "杀戮": int(groups[9]) if groups[9] else 0,
    }

    return {k: v.strip() if isinstance(v, str) else v for k, v in profile_data.items() if v is not None}


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
        _sent, final_message = await client.send_and_wait_for_edit(
            command,
            initial_reply_pattern=r"正在查询.*的天命玉牒"
        )

        profile_data = _parse_profile_text(final_message.text)

        if not profile_data.get("境界"):
            format_and_log("ERROR", "角色信息解析失败", {'原始文本': final_message.text})
            raise ValueError(f"无法从最终返回的信息中解析出角色数据: {getattr(final_message, 'text', '无最终消息')}")

        await data_manager.save_value(STATE_KEY_PROFILE, profile_data)
        
        if force_run:
            return _format_profile_reply(profile_data, "✅ **角色信息已更新并缓存**:")

    except (CommandTimeoutError, asyncio.TimeoutError) as e:
        error_msg = f"等待游戏机器人响应或更新信息超时(超过 {settings.COMMAND_TIMEOUT} 秒)。"
        if force_run:
            return create_error_reply("我的灵根", "游戏指令超时", details=error_msg)
        else:
            raise CommandTimeoutError(error_msg) from e
    except Exception as e:
        if force_run:
            return create_error_reply("我的灵根", "任务执行异常", details=str(e))
        else:
            raise e


async def _cmd_query_profile(event, parts):
    app = get_application()
    client = app.client
    progress_message = await client.reply_to_admin(event, "⏳ 正在发送指令并等待查询结果...")
    
    if not progress_message: return

    client.pin_message(progress_message)
    
    final_text = await trigger_update_profile(force_run=True)
    
    client.unpin_message(progress_message)
    try:
        await client._cancel_message_deletion(progress_message)
        await progress_message.edit(final_text)
    except MessageEditTimeExpiredError:
        await client.reply_to_admin(event, final_text)


async def _cmd_view_cached_profile(event, parts):
    profile_data = await data_manager.get_value(STATE_KEY_PROFILE, is_json=True)
    if not profile_data:
        await get_application().client.reply_to_admin(event, "ℹ️ 尚未缓存任何角色信息，请先使用 `,我的灵根` 查询一次。")
        return
    reply_text = _format_profile_reply(profile_data, "📄 **已缓存的角色信息**:")
    await get_application().client.reply_to_admin(event, reply_text)


def initialize(app):
    app.register_command("我的灵根", _cmd_query_profile, help_text="查询并刷新当前角色的详细信息。", category="查询")
    app.register_command("查看角色", _cmd_view_cached_profile, help_text="查看已缓存的最新角色信息。", category="数据查询")
