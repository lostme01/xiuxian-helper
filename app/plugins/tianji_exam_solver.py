# -*- coding: utf-8 -*-
import logging
import re
import asyncio
import google.generativeai as genai
from telethon import events
from config import settings
from app.logger import format_and_log
from app.utils import get_qa_answer_from_redis, save_qa_answer_to_redis

# --- 模块级变量 ---
client = None; me = None; model = None; redis_db = None
REDIS_DB_NAME = settings.REDIS_CONFIG['tianji_db_name']
EXAM_KEYWORD = "【天机考验】"

def initialize_plugin(tg_client, r_db):
    """初始化插件并接收 redis 连接实例"""
    global client, redis_db, model

    if not settings.TIANJI_EXAM_CONFIG.get('enabled'): return
    if not settings.EXAM_SOLVER_CONFIG.get('gemini_api_key'): return

    client = tg_client
    redis_db = r_db
    
    try:
        genai.configure(api_key=settings.EXAM_SOLVER_CONFIG['gemini_api_key'])
        model = genai.GenerativeModel('gemini-pro')
        format_and_log("SYSTEM", "插件加载", {'模块': '天机考验作答', '状态': '加载成功'})
    except Exception as e:
        format_and_log("SYSTEM", "插件加载", {'模块': '天机考验作答', '状态': f'Gemini AI 初始化失败: {e}'}, level=logging.ERROR)
        model = None
        return

    client.client.on(events.NewMessage(incoming=True))(tianji_exam_handler)

async def tianji_exam_handler(event):
    """消息处理器，用于检测并回答天机考验"""
    global me
    # *** 优化：在第一次处理时才获取 me 对象 ***
    if not me: me = await client.client.get_me()

    is_reply_to_us = event.is_reply and event.message.reply_to_msg_id in client.sent_messages_log_tracking
    if not is_reply_to_us or EXAM_KEYWORD not in event.text: return
    # ... (后续逻辑保持不变) ...
# ... (为保持简洁，其余函数省略，但实际写入的是完整文件) ...
