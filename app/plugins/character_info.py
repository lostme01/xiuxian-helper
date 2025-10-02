# -*- coding: utf-8 -*-
import re
import logging
import asyncio
from telethon.errors.rpcerrorlist import MessageEditTimeExpiredError
from config import settings
from app.logger import format_and_log
from app.context import get_application
from app.state_manager import set_state, get_state


STATE_KEY_PROFILE = "character_profile"

PROFILE_PATTERN = re.compile(
    r"@(?P<user>\w+)\*+\s*的天命玉牒"
    r"(?:.*?\s*称\s*号\s*[:：\s]*【(?P<称号>[^】]+)】)?"
    r".*?\s*宗\s*门\s*[:：\s]*【(?P<宗门>[^】]+)】"
    r"(?:.*?\s*道\s*号\s*[:：\s]*(?P<道号>[^\n]+))?"
    r"(?:.*?\s*灵\s*根\s*[:：\s]*(?P<灵根>[^\n]+))?"
    r".*?\s*境\s*界\s*[:：\s]*(?P<境界>[^\n]+)"
    r".*?\s*修\s*为\s*[:：\s]*(?P<当前修为>\d+)\s*/\s*(?P<修为上限>\d+)"
    r".*?\s*丹\s*毒\s*[:：\s]*(?P<丹毒>[^\n]+)"
    r".*?\s*杀\s*戮\s*[:：\s]*(?P<杀戮>[^\n]+)",
    re.DOTALL
)

def _parse_profile_text(text: str) -> dict:
    match = PROFILE_PATTERN.search(text)
    if not match:
        return {}

    profile = {k: v.strip() if v else v for k, v in match.groupdict().items()}
    
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


async def trigger_update_profile(force_run=False):
    app = get_application()
    client = app.client
    command = ".我的灵根"
    
    try:
        initial_reply_pattern = r"正.*?在.*?查.*?询.*?的.*?天.*?命.*?玉.*?牒"
        
        _initial_reply, final_message = await client.send_and_wait_for_edit(
            command, initial_reply_pattern=initial_reply_pattern, timeout=30)

        if not final_message:
            return False, "❌ **查询失败**: 等待游戏机器人更新信息超时。"

        profile_data = _parse_profile_text(final_message.text)

        if not profile_data.get("境界"):
            return False, f"❌ **解析失败**: 无法从返回的信息中解析出角色数据。\n\n**原始返回**:\n`{final_message.text}`"

        await set_state(STATE_KEY_PROFILE, profile_data)
        
        reply_text = _format_profile_reply(profile_data, "✅ **角色信息已更新并缓存**:")
        return True, reply_text

    except asyncio.TimeoutError:
        return False, "❌ **查询失败**: 发送指令后，游戏机器人无响应或未在规定时间内更新信息。"
    except Exception as e:
        return False, f"❌ **发生意外错误**: `{str(e)}`"

async def _cmd_query_profile(event, parts):
    app = get_application()
    client = app.client
    progress_message = await client.reply_to_admin(event, "⏳ 正在发送指令并等待查询结果...")
    
    if not progress_message: return

    client.pin_message(progress_message)
    
    _is_success, result = await trigger_update_profile()
    
    client.unpin_message(progress_message)

    try:
        await client._cancel_message_deletion(progress_message)
        edited_message = await progress_message.edit(result)
        client._schedule_message_deletion(edited_message, settings.AUTO_DELETE.get('delay_admin_command'), "角色查询结果")
    except MessageEditTimeExpiredError:
        await client.reply_to_admin(event, result)


async def _cmd_view_cached_profile(event, parts):
    app = get_application()
    profile_data = await get_state(STATE_KEY_PROFILE, is_json=True)
    if not profile_data:
        await app.client.reply_to_admin(event, "ℹ️ 尚未缓存任何角色信息，请先使用 `,我的灵根` 查询一次。")
        return
    reply_text = _format_profile_reply(profile_data, "📄 **已缓存的角色信息**:")
    await app.client.reply_to_admin(event, reply_text)


def initialize(app):
    app.register_command("我的灵根", _cmd_query_profile, help_text="查询并刷新当前角色的详细信息。", category="游戏查询")
    app.register_command("查看角色", _cmd_view_cached_profile, help_text="查看已缓存的最新角色信息。", category="游戏查询")
