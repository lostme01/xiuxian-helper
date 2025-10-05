# -*- coding: utf-8 -*-
import re
from telethon.tl.types import Message
from config import settings
from app.components.base_solver import BaseExamSolver

def initialize(app):
    """初始化并创建玄骨考校求解器实例"""
    XuanguExamSolver(
        tg_client=app.client,
        r_db=app.redis_db,
        exam_config=settings.XUANGU_EXAM_CONFIG,
        redis_db_name=settings.REDIS_CONFIG['xuangu_db_name'],
        log_module_name="玄骨考校作答",
        keywords=["神念直入脑海", "苍老的声音"]
    )

class XuanguExamSolver(BaseExamSolver):
    """玄骨考校的具体实现，继承自通用求解器基类"""
    def extract_question_options(self, message: Message) -> dict:
        """实现玄骨考校的题目和选项解析逻辑"""
        # [核心修改] 统一使用 .text
        text = message.text
        
        # [核心修改] 修改正则表达式以适应无格式文本
        question_match = re.search(r'“(.*?)”', text, re.DOTALL)
        question = question_match.group(1).strip() if question_match else None
        
        options_dict = {}
        option_pattern = re.compile(r'^\s*(A|B|C|D)\.\s*(.*)', re.MULTILINE)
        for match in option_pattern.finditer(text):
            letter, answer_text = match.group(1), match.group(2).strip()
            options_dict[letter] = answer_text
            
        if question and len(options_dict) >= 4:
            return {"question": question, "options": options_dict}
        return {"question": None, "options": {}}
