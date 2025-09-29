# -*- coding: utf-8 -*-
import logging
import re
import asyncio
import random
from telethon import events
from telethon.utils import get_display_name
from config import settings
from app.logger import format_and_log
from app.utils import get_qa_answer_from_redis, save_qa_answer_to_redis
from app import gemini_client

# --- 模块级变量 ---
client = None
me = None
redis_db = None
REDIS_DB_NAME = settings.REDIS_CONFIG['xuangu_db_name']
EXAM_KEYWORDS = ["神念直入脑海", "苍老的声音"]

def initialize_plugin(tg_client, r_db):
    """初始化插件"""
    global client, me, redis_db
    if not settings.EXAM_SOLVER_CONFIG.get('enabled'): return
    
    client = tg_client
    me = client.me
    redis_db = r_db
    
    client.client.on(events.NewMessage(incoming=True, chats=settings.GAME_GROUP_IDS))(exam_handler)

def extract_question_options(text: str) -> dict:
    """
    (全新重构) 根据您提供的 `题目.txt` 标准格式，重新实现的解析函数。
    """
    # --- 核心修复 1: 使用严格匹配 `**“...”**` 的正则表达式提取题目 ---
    question_match = re.search(r'\*\*(“.*?”)\*\*', text, re.DOTALL)
    question = question_match.group(1).strip() if question_match else None
    
    options_dict = {}
    # --- 核心修复 2: 使用严格匹配 `**A.** xxx` 的正则表达式提取选项 ---
    option_pattern = re.compile(r'^\s*\*\*(A|B|C|D)\.\*\*\s*(.*)', re.MULTILINE)
    
    for match in option_pattern.finditer(text):
        letter = match.group(1)
        answer_text = match.group(2).strip()
        options_dict[letter] = answer_text

    if question and len(options_dict) >= 4:
        return {"question": question, "options": options_dict}

    return {"question": None, "options": {}}


async def _ask_gemini(question: str, options: dict) -> str | None:
    """调用中央 gemini_client"""
    prompt = f"请根据以下单项选择题，仅返回正确答案的字母（A, B, C, D）。不要解释。\n问题：{question}\nA. {options.get('A','')}\nB. {options.get('B','')}\nC. {options.get('C','')}\nD. {options.get('D','')}"
    try:
        response = await gemini_client.generate_content_with_rotation(prompt)
        answer = re.sub(r'[^A-D]', '', response.text.upper())
        return answer if answer in options else None
    except Exception as e:
        format_and_log("TASK", "AI作答失败", {'问题': question, '错误': str(e)}, level=logging.ERROR)
        return None

def _find_answer_in_db(question: str, options: dict) -> str | None:
    format_and_log("TASK", "流程步骤: 数据库查询", {'模块': '玄骨校考作答', '问题': question})
    if stored_answer_text := get_qa_answer_from_redis(redis_db, REDIS_DB_NAME, question):
        for letter, text in options.items():
            if text == stored_answer_text:
                format_and_log("TASK", "流程步骤: 数据库命中", {'模块': '玄骨校考作答', '答案': f'{letter} ({text})'})
                return letter
    format_and_log("TASK", "流程步骤: 数据库未命中", {'模块': '玄骨校考作答', '详情': '将使用AI进行作答'})
    return None

def _save_answer_to_db(question: str, answer_text: str):
    save_qa_answer_to_redis(redis_db, REDIS_DB_NAME, question, answer_text)
    format_and_log("TASK", "流程步骤: 答案入库", {'来源': '玄骨校考', '问题': question, '答案': answer_text})

async def exam_handler(event):
    if not me: return
    text = event.message.text
    if not text or not all(keyword in text for keyword in EXAM_KEYWORDS): return
    format_and_log("TASK", "流程启动: 玄骨校考", {'状态': '关键词匹配成功', '消息ID': event.id})
    my_display_name = get_display_name(me)
    is_our_turn = f"@{me.username}" in text or f"@{my_display_name}" in text
    parsed_data = extract_question_options(text)
    question, options = parsed_data.get("question"), parsed_data.get("options")
    if not (question and options and len(options) >= 4):
        format_and_log("TASK", "流程中止: 玄骨校考", {'原因': '未能解析出有效的题目和选项', '原始文本': text})
        await client.send_admin_notification(f"⚠️ **解析失败通知 (玄骨校考)**\n\n无法从此条消息中完整解析出题目和四个选项，请检查原文并优化解析函数：\n-----------------\n`{text}`")
        return
    format_and_log("TASK", "流程步骤: 题目解析", {'模块': '玄骨校考作答', '问题': question, '选项': str(options), '是否轮到我': is_our_turn})
    answer_letter = _find_answer_in_db(question, options)
    source = "本地知识库"
    if not answer_letter:
        source = "Gemini AI"
        answer_letter = await _ask_gemini(question, options)
        if answer_letter: _save_answer_to_db(question, options[answer_letter])
        else: format_and_log("TASK", "流程中止: 玄骨校考", {'原因': 'AI未能返回有效答案'})
    if is_our_turn and answer_letter:
        log_data = {'模块': '玄骨校考作答', '回复内容': f".作答 {answer_letter}", '答案来源': source}
        format_and_log("TASK", "流程步骤: 准备作答", log_data)
        await asyncio.sleep(random.randint(5, 15))
        await event.message.reply(f".作答 {answer_letter}")
        format_and_log("TASK", "流程完成: 玄骨校考", {'状态': '已发送作答指令'})
    elif is_our_turn: format_and_log("TASK", "流程完成: 玄骨校考", {'状态': '放弃作答', '原因': '无法确定最终答案'})
    else: format_and_log("TASK", "流程完成: 玄骨校考", {'状态': '无需作答', '原因': '未@本机'})
