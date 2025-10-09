# -*- coding: utf-8 -*-
import asyncio
import random
from telethon import events
from telethon.utils import get_display_name
from config import settings
from app.logging_service import LogType, format_and_log
from app import game_adaptor

def initialize(app):
    """初始化插件，在客户端登录成功后调用"""
    if not settings.TASK_SWITCHES.get('mojun_arrival', False):
        return

    client = app.client
    client.client.on(events.NewMessage(incoming=True, chats=settings.GAME_GROUP_IDS))(
        lambda event: mojun_handler(event, client)
    )

async def mojun_handler(event, client):
    """处理“魔君降临”事件的消息"""
    me = client.me
    if not me: return
    
    text = event.message.text
    if not text: return

    EVENT_KEYWORDS = ["无法抗拒的意志锁定了你的神魂", "让老夫看看你的成"]
    if not all(keyword in text for keyword in EVENT_KEYWORDS):
        return
    
    my_display_name = get_display_name(me)
    is_our_turn = f"@{me.username}" in text or f"@{my_display_name}" in text
    
    if is_our_turn:
        REPLY_MESSAGE = game_adaptor.mojun_hide_presence()
        delay = random.randint(5, 10)
        await asyncio.sleep(delay)
        await event.message.reply(REPLY_MESSAGE)
