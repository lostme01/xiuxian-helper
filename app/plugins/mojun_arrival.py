# -*- coding: utf-8 -*-
import asyncio
import random
from telethon import events
from telethon.utils import get_display_name
from config import settings
from app.logger import format_and_log

# --- 模块级变量 ---
client = None
me = None

# --- 核心配置 ---
EVENT_KEYWORDS = ["无法抗拒的意志锁定了你的神魂", "让老夫看看你的成"]
REPLY_MESSAGE = ".收敛气息"

def initialize_plugin(tg_client):
    """初始化插件，在客户端登录成功后调用"""
    global client, me
    
    if not settings.TASK_SWITCHES.get('mojun_arrival', False):
        return

    client = tg_client
    me = client.me
    
    # 插件独立向 Telethon 注册自己的事件处理器
    client.client.on(events.NewMessage(incoming=True, chats=settings.GAME_GROUP_IDS))(mojun_handler)
    format_and_log("SYSTEM", "插件加载", {'模块': '魔君降临', '状态': '已启用'})


async def mojun_handler(event: events.NewMessage.Event):
    """处理“魔君降临”事件的消息"""
    if not me: return
    
    text = event.message.text
    if not text: return

    if not all(keyword in text for keyword in EVENT_KEYWORDS):
        return
    
    format_and_log("TASK", "流程启动: 魔君降临", {'状态': '关键词匹配成功', '消息ID': event.id})

    my_display_name = get_display_name(me)
    is_our_turn = f"@{me.username}" in text or f"@{my_display_name}" in text
    
    if is_our_turn:
        format_and_log("TASK", "流程步骤: 确认目标", {'模块': '魔君降临', '详情': '事件目标为本机，准备回复'})
        
        delay = random.randint(5, 10)
        await asyncio.sleep(delay)
        
        await event.message.reply(REPLY_MESSAGE)
        
        format_and_log("TASK", "流程完成: 魔君降临", {'状态': '已发送回复', '内容': REPLY_MESSAGE})
    else:
        format_and_log("TASK", "流程完成: 魔君降临", {'状态': '无需作答', '原因': '未@本机'})

