# -*- coding: utf-8 -*-
import re
from config import settings
from .base_solver import BaseExamSolver

# --- 天机考验的专属配置 ---
EXAM_KEYWORD = "【天机考验】"
REDIS_DB_NAME = settings.REDIS_CONFIG['tianji_db_name']
LOG_MODULE_NAME = "天机考验作答"

class TianjiExamSolver(BaseExamSolver):
    """天机考验的具体实现"""
    
    def extract_question_options(self, text: str) -> dict:
        """
        实现天机考验的选择题解析逻辑。
        """
        question_match = re.search(r'\*\*(.+)\*\*', text, re.DOTALL)
        question = question_match.group(1).strip() if question_match else None

        options_dict = {}
        option_pattern = re.compile(r'^\s*(A|B|C|D)\.\s*(.*)', re.MULTILINE)
        for match in option_pattern.finditer(text):
            letter, answer_text = match.group(1), match.group(2).strip().strip('*').strip()
            options_dict[letter] = answer_text
        
        if question and len(options_dict) >= 4:
            return {"question": question, "options": options_dict}
            
        return {"question": None, "options": {}}

def initialize_plugin(tg_client, r_db):
    """初始化并创建天机考验求解器实例"""
    TianjiExamSolver(
        tg_client=tg_client,
        r_db=r_db,
        exam_config=settings.TIANJI_EXAM_CONFIG,
        redis_db_name=REDIS_DB_NAME,
        log_module_name=LOG_MODULE_NAME,
        keywords=[EXAM_KEYWORD]  # 基类需要一个列表
    )

