# -*- coding: utf-8 -*-
import asyncio
import random
import re
from collections import deque
from telethon import events
from telethon.tl.functions.messages import SetTypingRequest
from telethon.tl.types import SendMessageTypingAction

from app.context import get_application
from app.logger import format_and_log
from config import settings
from app import gemini_client
from app.state_manager import get_state

# --- 全局变量 ---
chat_history = deque(maxlen=20) 
last_random_chat_time = 0

def initialize(app):
    """初始化AI聊天插件"""
    if not settings.AI_CHATTER_CONFIG.get('enabled'):
        return

    client = app.client
    client.client.on(events.NewMessage(incoming=True, chats=settings.GAME_GROUP_IDS))(
        lambda event: ai_chat_handler(event)
    )
    format_and_log("SYSTEM", "插件加载", {'模块': 'ai_chatter', '状态': '成功'})

async def ai_chat_handler(event):
    """处理游戏群聊消息，决定AI是否以及如何回应"""
    app = get_application()
    my_info = app.client.me
    if not my_info: return

    sender = await event.get_sender()
    message_text = event.text.strip()
    
    # --- [核心修改 v3] 过滤规则 ---
    # 1. 忽略自己、空消息、以及被Telegram标记为bot的账号
    if event.sender_id == my_info.id or not message_text or (sender and sender.bot):
        return
        
    # 2. 忽略所有在配置列表中定义的游戏机器人/频道/用户
    if settings.GAME_BOT_IDS and event.sender_id in settings.GAME_BOT_IDS:
        return

    # 3. [新增] 忽略聊天黑名单中的用户
    blacklist = settings.AI_CHATTER_CONFIG.get('blacklist', [])
    if event.sender_id in blacklist:
        return

    # 4. 忽略游戏指令和助手指令
    if message_text.startswith('.') or any(message_text.startswith(p) for p in settings.COMMAND_PREFIXES):
        return

    sender_name = getattr(sender, 'first_name', '未知用户')
    chat_history.append(f"{sender_name}: {message_text}")
    
    # --- 触发条件判断 ---
    mentioned_me = f"@{my_info.username}" in message_text if my_info.username else False
    random_chat_prob = settings.AI_CHATTER_CONFIG.get('random_chat_probability', 0.05)
    should_random_chat = random.random() < random_chat_prob
    
    global last_random_chat_time
    is_cooled_down = (asyncio.get_running_loop().time() - last_random_chat_time) > 120 # 2分钟冷却

    if not (mentioned_me or (should_random_chat and is_cooled_down)):
        return
        
    if should_random_chat and is_cooled_down:
        last_random_chat_time = asyncio.get_running_loop().time()

    try:
        prompt = await build_prompt(my_info)
        
        format_and_log("TASK", "AI聊天", {'状态': '触发成功', '原因': '@提及' if mentioned_me else '随机闲聊'})
        response = await gemini_client.generate_content_with_rotation(prompt)
        reply_text = response.text.strip().replace('"', '')

        if reply_text:
            await app.client.client(SetTypingRequest(peer=event.chat_id, action=SendMessageTypingAction()))
            await asyncio.sleep(random.uniform(2, 5))
            
            await event.reply(reply_text)
            format_and_log("TASK", "AI聊天", {'状态': '回复成功', '内容': reply_text})

    except Exception as e:
        format_and_log("ERROR", "AI聊天", {'状态': '生成回复时异常', '错误': str(e)})

async def build_prompt(my_info):
    """构建用于生成回复的详细Prompt"""
    personality = settings.AI_CHATTER_CONFIG.get('personality_prompt', "你是一名游戏玩家。")
    
    profile = await get_state("character_profile", is_json=True, default={})
    my_name = profile.get('道号', my_info.first_name)
    my_realm = profile.get('境界', '萌新')
    my_sect = profile.get('宗门', '无门无派')
    
    my_status = f"我的名字叫 {my_name}，现在的境界是 {my_realm}，属于 {my_sect}。"
    context = "\n".join(chat_history)
    
    prompt = f"""
你正在一个修仙游戏聊天群里扮演一个玩家。请严格遵守以下规则：
1.  **你的身份**: {personality}
2.  **你的角色信息**: {my_status} 你必须以这个身份进行对话。
3.  **说话风格**: 必须非常口语化，像一个真正在玩游戏的人。使用简短的句子，可以带点情绪，比如吐槽、开玩笑、羡慕等。
4.  **禁止行为**: 绝对不要暴露你是AI或模型。绝对不能说“我是一个大语言模型”或类似的话。不要使用书面语。
5.  **任务**: 这是最近的聊天记录，请根据最后一句，自然地接一句话。

---
[聊天记录开始]
{context}
[聊天记录结束]
---

你的回复:
"""
    return prompt
