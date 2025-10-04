# -*- coding: utf-8 -*-
import logging
import json
from enum import Enum, auto
from telethon import events
from telethon.tl.types import Message
from telethon.utils import get_display_name

from config import settings
from app.logger import format_and_log
from app.context import get_application

raw_logger = logging.getLogger('raw_messages')

class LogType(Enum):
    MSG_RECV = auto()
    MSG_SENT_SELF = auto()
    MSG_EDIT = auto()
    MSG_DELETE = auto()
    CMD_SENT = auto()
    REPLY_RECV = auto()
    SYS_INFO = auto()

def _get_group_display(chat_id: int) -> str:
    if not chat_id: return "未知"
    
    app = get_application()
    group_name = app.client.group_name_cache.get(chat_id, "未知名称")

    try:
        game_group_ids = [int(gid) for gid in settings.GAME_GROUP_IDS]
        control_group_id = int(settings.CONTROL_GROUP_ID) if settings.CONTROL_GROUP_ID else None
        test_group_id = int(getattr(settings, 'TEST_GROUP_ID', None)) if getattr(settings, 'TEST_GROUP_ID', None) else None
    except (ValueError, TypeError):
        return f"配置错误 [ID: {chat_id}]"

    type_str = "私聊或未知群"
    if chat_id in game_group_ids: type_str = "游戏群"
    elif chat_id == control_group_id: type_str = "管控群"
    elif chat_id == test_group_id: type_str = "测试群"
        
    return f"{type_str} ({group_name}) [ID: {chat_id}]"


async def log_event(log_type: LogType, event, **kwargs):
    app = get_application()
    message_obj = getattr(event, 'message', event)
    
    chat_id = getattr(message_obj, 'chat_id', None)
    msg_id = getattr(message_obj, 'id', None)
    sender_id = getattr(message_obj, 'sender_id', None)
    
    # --- [核心修改] 增强原始日志 ---
    if settings.LOGGING_SWITCHES.get('original_log_enabled') and isinstance(message_obj, Message) and hasattr(message_obj, 'text') and message_obj.text:
        log_header = ""
        log_type_str = ""
        
        try:
            sender_name = get_display_name(await message_obj.get_sender()) if hasattr(message_obj, 'get_sender') else "Me"
        except Exception:
            sender_name = f"ID:{sender_id}"

        if log_type == LogType.MSG_RECV:
            log_type_str = "收到消息"
        elif log_type == LogType.MSG_SENT_SELF:
            log_type_str = "发送消息"
        elif log_type == LogType.MSG_EDIT:
            log_type_str = "消息编辑"
        elif log_type == LogType.REPLY_RECV:
            log_type_str = "收到回复"
        
        if log_type_str:
            reply_to_id = getattr(message_obj.reply_to, 'reply_to_msg_id', None)
            reply_str = f" (回复 to: {reply_to_id})" if reply_to_id else ""
            
            log_header = (f"--- [原始日志: {log_type_str}] ---\n"
                          f"  群组: {_get_group_display(chat_id)}\n"
                          f"  来源: {sender_name} (ID:{sender_id})\n"
                          f"  消息ID: {msg_id}{reply_str}\n"
                          f"----------------------------------")
            raw_logger.info(f"{log_header}\n{message_obj.text}\n{'-'*50}")


    # --- 原有逻辑保持不变 ---
    log_data, title = {}, ""
    
    sender_info = f"(ID: {sender_id})"
    if sender_id:
        try:
            sender = await event.get_sender() if not getattr(event, 'out', False) else get_application().client.me
            if sender: sender_info = f"{get_display_name(sender)} (ID: {sender_id})"
        except Exception:
            sender_info = f"<信息获取失败> (ID: {sender_id})"

    log_data["群组"] = _get_group_display(chat_id)
    
    text_content = getattr(message_obj, 'text', '')

    if log_type == LogType.MSG_RECV:
        title, log_data["发送者"], log_data["消息ID"], log_data["内容"] = "收到消息", sender_info, msg_id, text_content
    elif log_type == LogType.MSG_SENT_SELF:
        title, log_data["发送者"], log_data["消息ID"], log_data["内容"] = "发出消息", sender_info, msg_id, text_content
    elif log_type == LogType.MSG_EDIT:
        title, log_data["编辑者"], log_data["消息ID"], log_data["新内容"] = "消息被编辑", sender_info, msg_id, text_content
    elif log_type == LogType.MSG_DELETE:
        title = "消息被删除"
        log_data["被删ID"] = str(kwargs.get("deleted_ids", []))
    elif log_type == LogType.CMD_SENT:
        title, bot_me = "指令已发送", get_application().client.me
        log_data["发送者"], log_data["指令"], log_data["回复至"] = f"{get_display_name(bot_me)} (ID: {bot_me.id})", kwargs.get("command", ""), kwargs.get("reply_to") or "N/A"
    elif log_type == LogType.REPLY_RECV:
        title, log_data["回复者"], log_data["消息ID"], log_data["内容"] = "收到有效回复", sender_info, msg_id, text_content

    log_key_map = {
        LogType.MSG_RECV: "MSG_RECV", LogType.MSG_SENT_SELF: "MSG_RECV", 
        LogType.MSG_EDIT: "MSG_EDIT", LogType.MSG_DELETE: "MSG_DELETE", 
        LogType.CMD_SENT: "CMD_SENT", LogType.REPLY_RECV: "REPLY_RECV"
    }
    
    log_type_key = log_key_map.get(log_type)
    if log_type_key:
        from app.logger import format_and_log
        format_and_log(log_type_key, title, log_data)
