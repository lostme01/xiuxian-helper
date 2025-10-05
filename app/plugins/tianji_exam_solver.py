# -*- coding: utf-8 -*-
import re
from telethon.tl.types import Message
from config import settings
from app.components.base_solver import BaseExamSolver

def initialize(app):
    """初始化并创建天机考验求解器实例"""
    TianjiExamSolver(
        tg_client=app.client,
        r_db=app.redis_db,
        exam_config=settings.TIANJI_EXAM_CONFIG,
        redis_db_name=settings.REDIS_CONFIG['tianji_db_name'],
        log_module_name="天机考验作答",
        keywords=["【天机考验】"]
    )

class TianjiExamSolver(BaseExamSolver):
    """天机考验的具体实现"""
    def extract_question_options(self, message: Message) -> dict:
        """实现天机考验的选择题解析逻辑"""
        # [核心修改] 统一使用 .text
        text = message.text
        
        # [核心修改] 修改正则表达式以适应无格式文本
        question_match = re.search(r'^(?!【天机考验】).+', text, re.MULTILINE)
        question = question_match.group(0).strip() if question_match else None

        options_dict = {}
        option_pattern = re.compile(r'^\s*(A|B|C|D)\.\s*(.*)', re.MULTILINE)
        for match in option_pattern.finditer(text):
            letter, answer_text = match.group(1), match.group(2).strip()
            options_dict[letter] = answer_text
        if question and len(options_dict) >= 4:
            return {"question": question, "options": options_dict}
        return {"question": None, "options": {}}
