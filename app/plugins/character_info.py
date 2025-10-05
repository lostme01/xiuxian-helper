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
from app.state_manager import set_state, get_state
from app.telegram_client import CommandTimeoutError
from app.utils import create_error_reply
from app import game_adaptor

STATE_KEY_PROFILE = "character_profile"

PROFILE_PATTERN = re.compile(
    r"\*\*@(?P<user>[\w\d]+)\*\*\s*的天命玉牒\s*"
    r"(?:称号\s*:\s*【(?P<title>[^】]*)】\s*)?"
    r"宗门\s*:\s*【(?P<sect>[^】]*)】\s*"
    r"(?:道号\s*:\s*(?P<dao_name>.+?)\s*\n)?"
    r"(?:灵根\s*:\s*(?P<root>.+?)\s*\n)?"
    r"境界\s*:\s*(?P<realm>.+?)\s*"
    r"修为\s*:\s*(?P<exp_cur>\d+)\s*/\s*(?P<exp_max>\d+)\s*"
    r"丹毒\s*:\s*(?P<pill_poison>-?\d+)\s*点\s*"
    r"杀戮\s*:\s*(?P<kills>\d+)\s*人",
    re.S
)

def _parse_profile_text(text: str) -> dict:
    match = PROFILE_PATTERN.search(text)
    if not match:
        return {}

    profile = {k: v.strip() if v else v for k, v in match.groupdict().items()}
    
    # 将字符串数字转换为整数
    for key in ["当前修为", "修为上限", "丹毒", "杀戮"]:
        new_key = key.replace("当前", "")
        if profile.get(key):
            try:
                profile[new_key] = int(profile[key])
            except (ValueError, TypeError):
                pass
            del profile[key]

    return profile

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
            raise ValueError(f"无法从最终返回的信息中解析出角色数据: {getattr(final_message, 'text', '无最终消息')}")

        await set_state(STATE_KEY_PROFILE, profile_data)
        
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
    app = get_application()
    profile_data = await get_state(STATE_KEY_PROFILE, is_json=True)
    if not profile_data:
        await app.client.reply_to_admin(event, "ℹ️ 尚未缓存任何角色信息，请先使用 `,我的灵根` 查询一次。")
        return
    reply_text = _format_profile_reply(profile_data, "📄 **已缓存的角色信息**:")
    await app.client.reply_to_admin(event, reply_text)


def initialize(app):
    app.register_command("我的灵根", _cmd_query_profile, help_text="查询并刷新当前角色的详细信息。", category="查询")
    app.register_command("查看角色", _cmd_view_cached_profile, help_text="查看已缓存的最新角色信息。", category="查询")
