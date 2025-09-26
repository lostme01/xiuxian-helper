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
QA_DATABASE_PATH = f"{settings.DATA_DIR}/tianji_qa.json"
EXAM_KEYWORD = "【天机考验】"

# --- 模块级变量 ---
client = None
me = None
model = None

def initialize_plugin(tg_client):
    """初始化并注册插件"""
    global client, me, model
    
    if not settings.TIANJI_EXAM_CONFIG.get('enabled'):
        format_and_log("SYSTEM", "插件跳过", {'模块': '天机考验作答', '原因': '功能未启用'})
        return
    if not settings.EXAM_SOLVER_CONFIG.get('gemini_api_key'):
        format_and_log("SYSTEM", "插件跳过", {'模块': '天机考验作答', '原因': 'Gemini API Key未配置'}, level=logging.WARNING)
        return

    client = tg_client
    me = client.me
    
    try:
        genai.configure(api_key=settings.EXAM_SOLVER_CONFIG['gemini_api_key'])
        model = genai.GenerativeModel('gemini-pro')
        format_and_log("SYSTEM", "插件加载", {'模块': '天机考验作答', '状态': 'Gemini AI 初始化成功'})
    except Exception as e:
        format_and_log("SYSTEM", "插件加载", {'模块': '天机考验作答', '状态': f'Gemini AI 初始化失败: {e}'}, level=logging.ERROR)
        return

    client.client.on(events.NewMessage(incoming=True))(tianji_exam_handler)

def _parse_multiple_choice(text: str):
    """解析选择题的问题和选项"""
    question_match = re.search(r'\n\n\*\*(.+?)\*\*\n A\.', text, re.DOTALL)
    if not question_match: return None, None
    
    question = question_match.group(1).strip()
    options = {}
    option_pattern = re.compile(r'([A-D])\.\s*(.+)')
    for line in text.split('\n'):
        if match := option_pattern.search(line):
            options[match.group(1)] = match.group(2).strip().replace('**', '')
            
    return question, options if len(options) == 4 else None

def _parse_command_question(text: str):
    """解析指令题的问题和指令"""
    # 改进正则表达式以更好地提取问题
    question_match = re.search(r'\n\n\*\*(.+?)\*\*\n\n回', text, re.DOTALL)
    command_match = re.search(r'回复指令 \*\*(.+?)\*\*', text)
    
    if question_match and command_match:
        question = question_match.group(1).strip()
        command = command_match.group(1).strip()
        return question, command
    return None, None

async def _ask_gemini(question: str, options: dict) -> str | None:
    """使用 Gemini AI 回答选择题"""
    prompt = f"请根据以下单项选择题，仅返回正确答案的字母（A, B, C, D）。不要解释。\n问题：{question}\nA. {options['A']}\nB. {options['B']}\nC. {options['C']}\nD. {options['D']}"
    try:
        response = await model.generate_content_async(prompt)
        answer = re.sub(r'[^A-D]', '', response.text)
        return answer if answer in options else None
    except Exception as e:
        format_and_log("TASK", "AI作答失败", {'来源': '天机考验', '错误': str(e)}, level=logging.ERROR)
        return None

async def tianji_exam_handler(event):
    """消息处理器，用于检测并回答天机考验"""
    is_reply_to_us = event.is_reply and event.message.reply_to_msg_id in client.sent_messages_log_tracking
    if not is_reply_to_us or EXAM_KEYWORD not in event.text:
        return
        
    format_and_log("TASK", "天机考验", {'状态': '检测到考验题目'})
    
    text = event.message.text
    qa_db = read_json_state(QA_DATABASE_PATH) or {}
    
    # 尝试作为选择题处理
    question, options = _parse_multiple_choice(text)
    if question and options:
        log_data = {'问题': question, '选项': ' | '.join(f"{k}:{v}" for k, v in options.items())}
        format_and_log("TASK", "题目解析", log_data)

        answer_letter = None
        source = "本地知识库"
        
        if (stored_answer_text := qa_db.get(question)):
            for letter, option_text in options.items():
                if option_text == stored_answer_text:
                    answer_letter = letter
                    break
        
        if not answer_letter:
            source = "Gemini AI"
            answer_letter = await _ask_gemini(question, options)
        
        if answer_letter:
            format_and_log("TASK", "答案已确定", {'答案': f"{answer_letter} ({options[answer_letter]})", '来源': source})
            await asyncio.sleep(random.randint(5, 15))
            await event.message.reply(answer_letter)
            if source == "Gemini AI":
                qa_db[question] = options[answer_letter]
                write_json_state(QA_DATABASE_PATH, qa_db)
        else:
            format_and_log("TASK", "作答失败", {'问题': question, '原因': '无法获取答案'}, level=logging.ERROR)
        return

    # 尝试作为指令题处理
    question, command = _parse_command_question(text)
    if question and command:
        format_and_log("TASK", "题目解析", {'问题': question, '指令': command})
        
        await asyncio.sleep(random.randint(5, 15))
        await event.message.reply(command)
        
        # *** 优化：移除指令题的缓存逻辑 ***
        # if not qa_db.get(question):
        #      qa_db[question] = command
        #      write_json_state(QA_DATABASE_PATH, qa_db)
        return
