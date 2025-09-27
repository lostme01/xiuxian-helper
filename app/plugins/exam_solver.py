# -*- coding: utf-8 -*-
import logging
import re
import asyncio
import google.generativeai as genai
from telethon import events
from config import settings
from app.logger import format_and_log
from app.utils import read_json_state, write_json_state

# --- 常量定义 ---
QA_DATABASE_PATH = f"{settings.DATA_DIR}/qa_database.json"
EXAM_KEYWORDS = ["神念直入脑海", "提问", "苍老的声音"]

# --- 模块级变量 ---
client = None
me = None
model = None

def initialize_plugin(tg_client):
    """初始化并注册插件"""
    global client, me, model
    
    if not settings.EXAM_SOLVER_CONFIG.get('enabled'):
        format_and_log("SYSTEM", "插件跳过", {'模块': '玄骨校考作答', '原因': '功能未启用'})
        return
    if not settings.EXAM_SOLVER_CONFIG.get('gemini_api_key'):
        format_and_log("SYSTEM", "插件跳过", {'模块': '玄骨校考作答', '原因': 'Gemini API Key未配置'}, level=logging.WARNING)
        return

    client = tg_client
    me = client.me
    
    try:
        genai.configure(api_key=settings.EXAM_SOLVER_CONFIG['gemini_api_key'])
        model = genai.GenerativeModel('gemini-pro')
        format_and_log("SYSTEM", "插件加载", {'模块': '玄骨校考作答', '状态': 'Gemini AI 初始化成功'})
    except Exception as e:
        format_and_log("SYSTEM", "插件加载", {'模块': '玄骨校考作答', '状态': f'Gemini AI 初始化失败: {e}'}, level=logging.ERROR)
        return

    client.client.on(events.NewMessage(chats=settings.GAME_GROUP_ID))(exam_handler)

def _parse_exam_message(text: str):
    """从消息中解析出问题和选项"""
    question_match = re.search(r'“([^”]+)”', text)
    if not question_match: return None, None
    
    question = question_match.group(1)
    options = {}
    
    option_pattern = re.compile(r'\*\*(A|B|C|D)\.\*\*\s*(.+)')
    for line in text.split('\n'):
        if match := option_pattern.search(line):
            options[match.group(1)] = match.group(2).strip()
            
    return question, options if len(options) == 4 else None

async def _ask_gemini(question: str, options: dict) -> str | None:
    """使用 Gemini AI 回答问题"""
    prompt = f"""
    你是一个知识渊博的学者，请根据以下单项选择题，仅返回正确答案的字母（A, B, C, D）。
    不要解释，不要说任何其他话，只需要一个字母。

    问题：{question}
    A. {options['A']}
    B. {options['B']}
    C. {options['C']}
    D. {options['D']}
    """
    try:
        response = await model.generate_content_async(prompt)
        answer = re.sub(r'[^A-D]', '', response.text)
        return answer if answer in options else None
    except Exception as e:
        format_and_log("TASK", "AI作答失败", {'问题': question, '错误': str(e)}, level=logging.ERROR)
        return None

def _find_answer_in_db(question: str, options: dict) -> str | None:
    """在本地知识库中查找答案"""
    qa_db = read_json_state(QA_DATABASE_PATH) or {}
    if stored_answer_text := qa_db.get(question):
        for letter, text in options.items():
            if text == stored_answer_text:
                return letter
    return None

def _save_answer_to_db(question: str, answer_text: str):
    """将新的问答对保存到知识库"""
    qa_db = read_json_state(QA_DATABASE_PATH) or {}
    qa_db[question] = answer_text
    write_json_state(QA_DATABASE_PATH, qa_db)
    format_and_log("TASK", "知识库更新", {'来源': '玄骨校考', '问题': question, '答案': answer_text})

async def exam_handler(event):
    """消息处理器，用于检测、学习并回答玄骨校考"""
    text = event.message.text
    
    # 1. 初步检查：是否为考题消息
    if not all(keyword in text for keyword in EXAM_KEYWORDS):
        return
        
    # 2. 身份识别：判断是否轮到自己作答
    is_our_turn = f"@{me.username}" in text
    
    # 3. 解析题目
    question, options = _parse_exam_message(text)
    if not (question and options):
        return

    # 4. 无论是否轮到自己，都开始解题流程以充实题库
    format_and_log("TASK", "玄骨校考", {'状态': '检测到题目', '是否轮到我': is_our_turn})
    
    answer_letter = _find_answer_in_db(question, options)
    source = "本地知识库"
    
    # 如果本地题库没有，则求助AI
    if not answer_letter:
        source = "Gemini AI"
        answer_letter = await _ask_gemini(question, options)
        # 如果AI给出了答案，则更新题库
        if answer_letter:
            _save_answer_to_db(question, options[answer_letter])

    # 5. 决策与行动：只有轮到自己，并且成功获取到答案时，才公开回复
    if is_our_turn and answer_letter:
        format_and_log("TASK", "答案已确定", {'来源': '玄骨校考', '答案': f"{answer_letter} ({options[answer_letter]})", '来源': source})
        await asyncio.sleep(random.randint(5, 15))
        await event.message.reply(f".作答 {answer_letter}")
    elif is_our_turn and not answer_letter:
        format_and_log("TASK", "作答失败", {'来源': '玄骨校考', '原因': '无法从任何来源获取答案'}, level=logging.ERROR)
    # 如果不是轮到自己，则在后台学习完毕后静默结束
