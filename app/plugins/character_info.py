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

STATE_KEY_PROFILE = "character_profile"

PROFILE_PATTERN = re.compile(
    r"@(?P<user>\w+)\**\s+的天命玉牒\s*"
    r"(?:[*\s]*称号[*\s]*: *【(?P<title>[^】]*)】)?\s*"
    r"[*\s]*宗门[*\s]*: *【(?P<sect>[^】]*)】\s*"
    r"(?:[*\s]*道号[*\s]*: *(?P<dao_name>.+?))?\s*"
    r"(?:[*\s]*灵根[*\s]*: *(?P<root>.+?))?\s*"
    r"[*\s]*境界[*\s]*: *(?P<realm>.+?)\s*"
    r"[*\s]*修为[*\s]*: *(?P<exp_cur>\d+) */ *(?P<exp_max>\d+)\s*"
    r"[*\s]*丹毒[*\s]*: *(-?\d+) *点\s*"
    r"[*\s]*杀戮[*\s]*: *(?P<kills>\d+) *人",
    re.S
)

def _parse_profile_text(text: str) -> dict:
    match = PROFILE_PATTERN.search(text)
    if not match:
        return {}

    raw_profile = {k: v.strip() if v else v for k, v in match.groupdict().items()}
    raw_profile['pill_poison'] = match.group(match.lastindex)
    
    profile = {
        "user": raw_profile.get("user"),
        "称号": raw_profile.get("title"),
        "宗门": raw_profile.get("sect"),
        "道号": raw_profile.get("dao_name"),
        "灵根": raw_profile.get("root"),
        "境界": raw_profile.get("realm"),
        "当前修为": raw_profile.get("exp_cur"),
        "修为上限": raw_profile.get("exp_max"),
        "丹毒": f"{raw_profile.get('pill_poison')} 点",
        "杀戮": f"{raw_profile.get('kills')} 人",
    }

    for key in ["当前修为", "修为上限"]:
        if profile.get(key):
            try:
                profile[key] = int(profile[key])
            except (ValueError, TypeError):
                pass
            
    return profile

def _format_profile_reply(profile_data: dict, title: str) -> str:
    display_map = {
        "user": "用户", "称号": "称号", "宗门": "宗门", "道号": "道号",
        "灵根": "灵根", "境界": "境界", "当前修为": "修为", "修为上限": "上限",
        "丹毒": "丹毒", "杀戮": "杀戮"
    }
    
    lines = [title]
    for key, display_name in display_map.items():
        if key in profile_data and profile_data[key] is not None:
            value = profile_data[key]
            if key == '当前修为':
                upper_limit = profile_data.get('修为上限', 'N/A')
                lines.append(f"- **{display_name}**：`{value} / {upper_limit}`")
            elif key != '修为上限':
                 lines.append(f"- **{display_name}**：`{value}`")

    return "\n".join(lines)


async def trigger_update_profile():
    app = get_application()
    client = app.client
    command = ".我的灵根"
    
    sent_message = None
    initial_reply = None
    final_message = None

    try:
        sent_message, initial_reply = await client.send_game_command_request_response(command)

        # [核心修改] 统一使用 .text
        profile_data = _parse_profile_text(initial_reply.text)

        if profile_data.get("境界"):
            final_message = initial_reply
        else:
            initial_reply_pattern = r"正.*?在.*?查.*?询.*?的.*?天.*?命.*?玉.*?牒"
            if re.search(initial_reply_pattern, initial_reply.text):
                edit_future = asyncio.Future()
                client.pending_edit_by_id[initial_reply.id] = edit_future
                
                remaining_timeout = settings.COMMAND_TIMEOUT - (datetime.now(pytz.utc) - sent_message.date).total_seconds()
                if remaining_timeout <= 0:
                    raise asyncio.TimeoutError("获取初始回复后没有剩余时间等待编辑。")
                
                final_message = await asyncio.wait_for(edit_future, timeout=remaining_timeout)
                # [核心修改] 统一使用 .text
                profile_data = _parse_profile_text(final_message.text)
            else:
                raise RuntimeError(f"游戏机器人返回的初始消息与预期不符: {initial_reply.text}")

        if not profile_data.get("境界"):
            raise ValueError(f"无法从最终返回的信息中解析出角色数据: {getattr(final_message, 'text', '无最终消息')}")

        await set_state(STATE_KEY_PROFILE, profile_data)
        return _format_profile_reply(profile_data, "✅ **角色信息已更新并缓存**:")

    except (CommandTimeoutError, asyncio.TimeoutError) as e:
        raise CommandTimeoutError(f"等待游戏机器人响应或更新信息超时(超过 {settings.COMMAND_TIMEOUT} 秒)。") from e
    except Exception as e:
        raise e
    finally:
        if initial_reply:
            client.pending_edit_by_id.pop(initial_reply.id, None)


async def _cmd_query_profile(event, parts):
    app = get_application()
    client = app.client
    progress_message = await client.reply_to_admin(event, "⏳ 正在发送指令并等待查询结果...")
    
    if not progress_message: return

    client.pin_message(progress_message)
    
    final_text = ""
    try:
        final_text = await trigger_update_profile()

    except CommandTimeoutError as e:
        final_text = create_error_reply(
            command_name="我的灵根",
            reason="等待游戏机器人响应超时",
            details=str(e)
        )
    except Exception as e:
        final_text = create_error_reply(
            command_name="我的灵根",
            reason="发生意外错误",
            details=str(e)
        )
    finally:
        client.unpin_message(progress_message)
        try:
            await client._cancel_message_deletion(progress_message)
            edited_message = await progress_message.edit(final_text)
            client._schedule_message_deletion(edited_message, settings.AUTO_DELETE.get('delay_admin_command'), "角色查询结果")
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
