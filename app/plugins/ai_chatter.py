# -*- coding: utf-8 -*-
import asyncio
import random
import re
import time
from collections import deque
from telethon import events
from telethon.tl.functions.messages import SetTypingRequest
from telethon.tl.types import SendMessageTypingAction

from app.context import get_application
from app.logger import format_and_log
from config import settings
from app import gemini_client
from app.state_manager import get_state
from app.task_scheduler import scheduler

# --- 全局变量与常量 ---
human_chat_history = deque(maxlen=30) 
last_random_chat_time = 0
_assistant_ids_cache = None
_assistant_ids_cache_time = 0

MOOD_KEY = "ai_chatter:mood"
TOPIC_KEY = "ai_chatter:topic"
MOODS = {"happy": "心情不错", "neutral": "心情一般", "annoyed": "有点烦躁"}

async def _get_all_assistant_ids():
    """获取并缓存所有友方助手的ID列表"""
    global _assistant_ids_cache, _assistant_ids_cache_time
    now = time.time()
    if _assistant_ids_cache is None or (now - _assistant_ids_cache_time > 300):
        app = get_application()
        if not app.redis_db:
            _assistant_ids_cache = []
            return []
            
        keys_found = [key async for key in app.redis_db.scan_iter("tg_helper:task_states:*")]
        _assistant_ids_cache = [int(key.split(':')[-1]) for key in keys_found]
        _assistant_ids_cache_time = now
    return _assistant_ids_cache

async def summarize_topic_task():
    """定时任务，总结近期聊天话题"""
    if not settings.AI_CHATTER_CONFIG.get('topic_system_enabled'):
        return

    app = get_application()
    if not app.redis_db or len(human_chat_history) < 5:
        return

    format_and_log("TASK", "AI聊天-话题总结", {'状态': '开始'})
    context = "\n".join(human_chat_history)
    prompt = f"请用一句话高度概括以下聊天记录的核心主题。如果没有明确主题，就回答“闲聊”。\n\n{context}"

    try:
        response = await gemini_client.generate_content_with_rotation(prompt)
        topic = response.text.strip().replace('"', '')
        await app.redis_db.set(TOPIC_KEY, topic, ex=3600)
        format_and_log("TASK", "AI聊天-话题总结", {'状态': '成功', '话题': topic})
    except Exception as e:
        format_and_log("ERROR", "AI聊天-话题总结", {'状态': '异常', '错误': str(e)})


def initialize(app):
    """初始化AI聊天插件"""
    if not settings.AI_CHATTER_CONFIG.get('enabled'):
        return

    client = app.client
    client.client.on(events.NewMessage(incoming=True, chats=settings.GAME_GROUP_IDS))(
        lambda event: ai_chat_handler(event)
    )
    
    if settings.AI_CHATTER_CONFIG.get('topic_system_enabled'):
        scheduler.add_job(summarize_topic_task, 'interval', minutes=10, id='ai_chatter_topic_task', replace_existing=True)

    format_and_log("SYSTEM", "插件加载", {'模块': 'ai_chatter', '状态': '成功'})

async def ai_chat_handler(event):
    """处理游戏群聊消息，决定AI是否以及如何回应"""
    app = get_application()
    my_info = app.client.me
    if not my_info: return

    sender = await event.get_sender()
    sender_id = event.sender_id
    sender_name = getattr(sender, 'first_name', f'未知用户({sender_id})')
    message_text = event.text.strip()
    
    format_and_log("DEBUG", "AI聊天-收到消息", {'来自': f"'{sender_name}'({sender_id})", '内容': message_text})

    # --- 过滤规则 ---
    if sender_id == my_info.id:
        format_and_log("DEBUG", "AI聊天-忽略", {'原因': '是自己发的消息'})
        return
    if not message_text:
        format_and_log("DEBUG", "AI聊天-忽略", {'原因': '消息内容为空'})
        return
    
    is_bot = hasattr(sender, 'bot') and sender.bot
    if is_bot:
        format_and_log("DEBUG", "AI聊天-忽略", {'原因': '发送者被标记为Bot'})
        return
        
    is_game_bot = sender_id in settings.GAME_BOT_IDS
    if is_game_bot:
        format_and_log("DEBUG", "AI聊天-处理", {'动作': '分析游戏事件情绪', '来源': sender_name})
        if settings.AI_CHATTER_CONFIG.get('mood_system_enabled'):
            await analyze_mood_from_game_event(message_text)
        return
        
    if message_text.startswith('.') or any(message_text.startswith(p) for p in settings.COMMAND_PREFIXES):
        format_and_log("DEBUG", "AI聊天-忽略", {'原因': '是指令消息'})
        return

    # 只有通过所有过滤的真人才会走到这里
    human_chat_history.append(f"{sender_name}: {message_text}")
    format_and_log("DEBUG", "AI聊天-学习", {'内容': f"{sender_name}: {message_text}"})
    
    # --- 触发决策 ---
    assistant_ids = await _get_all_assistant_ids()
    is_from_assistant = sender_id in assistant_ids

    mentioned_me = f"@{my_info.username}" in message_text if my_info.username else False
    replied_to_me = False
    if event.is_reply:
        reply_to_msg = await event.get_reply_message()
        if reply_to_msg and reply_to_msg.sender_id == my_info.id:
            replied_to_me = True

    should_trigger = False
    trigger_reason = ""

    if is_from_assistant:
        format_and_log("DEBUG", "AI聊天-决策", {'判断': '消息来自友方助手'})
        if mentioned_me or replied_to_me:
            inter_reply_prob = settings.AI_CHATTER_CONFIG.get('inter_assistant_reply_probability', 0.3)
            if random.random() < inter_reply_prob:
                should_trigger = True
                trigger_reason = "助手间互动"
            else:
                format_and_log("DEBUG", "AI聊天-忽略", {'原因': '未达到助手间互动概率'})
                return # [核心修复] 补上 return
    else: # 来自普通玩家
        format_and_log("DEBUG", "AI聊天-决策", {'判断': '消息来自普通玩家'})
        random_chat_prob = settings.AI_CHATTER_CONFIG.get('random_chat_probability', 0.05)
        should_random_chat = random.random() < random_chat_prob
        
        global last_random_chat_time
        is_cooled_down = (time.time() - last_random_chat_time) > 120

        if mentioned_me or replied_to_me:
            should_trigger = True
            trigger_reason = "被@或回复"
        elif should_random_chat and is_cooled_down:
            should_trigger = True
            trigger_reason = "随机闲聊"
            last_random_chat_time = time.time()
        elif not is_cooled_down:
             format_and_log("DEBUG", "AI聊天-忽略", {'原因': '随机闲聊冷却中'})
             return # [核心修复] 补上 return
        elif not should_random_chat:
             format_and_log("DEBUG", "AI聊天-忽略", {'原因': '未达到随机闲聊概率'})
             return # [核心修复] 补上 return

    if not should_trigger:
        return

    # --- 执行与出口拦截 ---
    try:
        blacklist = settings.AI_CHATTER_CONFIG.get('blacklist', [])
        if sender_id in blacklist:
            format_and_log("DEBUG", "AI聊天-回复中止", {'原因': f'消息来源({sender_id})在黑名单中'})
            return

        prompt = await build_prompt(my_info)
        
        format_and_log("TASK", "AI聊天-触发", {'原因': trigger_reason, '状态': '准备请求Gemini'})
        response = await gemini_client.generate_content_with_rotation(prompt)
        reply_text = response.text.strip().replace('"', '')

        if reply_text:
            await app.client.client(SetTypingRequest(peer=event.chat_id, action=SendMessageTypingAction()))
            await asyncio.sleep(random.uniform(2, 5))
            
            reply_ratio = settings.AI_CHATTER_CONFIG.get('reply_vs_send_ratio', 0.8)
            if replied_to_me or mentioned_me or random.random() < reply_ratio:
                await event.reply(reply_text)
            else:
                await app.client.client.send_message(event.chat_id, reply_text)

            format_and_log("TASK", "AI聊天-成功", {'回复内容': reply_text})

    except Exception as e:
        format_and_log("ERROR", "AI聊天", {'状态': '生成回复时异常', '错误': str(e)})

async def analyze_mood_from_game_event(text: str):
    app = get_application()
    if not app.redis_db: return
    positive_keywords = settings.AI_CHATTER_CONFIG.get('positive_keywords', [])
    negative_keywords = settings.AI_CHATTER_CONFIG.get('negative_keywords', [])
    new_mood = None
    if any(kw in text for kw in positive_keywords): new_mood = "happy"
    elif any(kw in text for kw in negative_keywords): new_mood = "annoyed"
    if new_mood:
        await app.redis_db.set(MOOD_KEY, new_mood, ex=1800)
        format_and_log("DEBUG", "AI聊天-情绪更新", {'新心情': new_mood, '来源': text})

async def build_prompt(my_info):
    app = get_application()
    personality = settings.AI_CHATTER_CONFIG.get('personality_prompt', "你是一名游戏玩家。")
    profile = await get_state("character_profile", is_json=True, default={})
    my_name = profile.get('道号', my_info.first_name)
    my_realm = profile.get('境界', '萌新')
    my_sect = profile.get('宗门', '无门无派')
    my_status = f"我的名字是 {my_name}，境界是 {my_realm}，在 {my_sect}。"
    current_mood_desc, current_topic = "心情一般", "闲聊"
    if app.redis_db:
        mood_key = await app.redis_db.get(MOOD_KEY)
        current_mood_desc = MOODS.get(mood_key, "心情一般")
        topic_from_redis = await app.redis_db.get(TOPIC_KEY)
        if topic_from_redis: current_topic = topic_from_redis
    context = "\n".join(human_chat_history)
    prompt = f"""
你正在一个修仙游戏聊天群里扮演一个玩家。请严格遵守以下规则：
1. **你的身份**: {personality}
2. **你的角色信息**: {my_status} 你必须以这个身份进行对话。
3. **你的当前状态**: 你现在{current_mood_desc}。群里最近的话题是“{current_topic}”。你的发言要符合你当前的心情和群里的话题。
4. **说话风格**: 必须非常口语化，像一个真正在玩游戏的人。使用简短的句子，可以带点情绪。
5. **禁止行为**: 绝对不要暴露你是AI。
6. **任务**: 这是最近的聊天记录，请根据最后一句，自然地接一句话。

---
[聊天记录开始]
{context}
[聊天记录结束]
---

你的回复:
"""
    return prompt
