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

class BaseExamSolver:
    """
    答题插件的基类，封装了所有通用逻辑。
    """
    def __init__(self, tg_client, r_db, exam_config, redis_db_name, log_module_name, keywords):
        self.client = tg_client
        self.me = tg_client.me
        self.redis_db = r_db
        self.exam_config = exam_config
        self.redis_db_name = redis_db_name
        self.log_module_name = log_module_name
        self.keywords = keywords
        
        # 注册事件处理器
        if self.exam_config.get('enabled'):
            self.client.client.on(events.NewMessage(incoming=True, chats=settings.GAME_GROUP_IDS))(self.handler)

    def extract_question_options(self, text: str) -> dict:
        """
        子类必须实现这个方法来解析各自的题目格式。
        """
        raise NotImplementedError

    async def _ask_gemini(self, question: str, options: dict) -> str | None:
        prompt = f"请根据以下单项选择题，仅返回正确答案的字母（A, B, C, D）。不要解释。\n问题：{question}\nA. {options.get('A','')}\nB. {options.get('B','')}\nC. {options.get('C','')}\nD. {options.get('D','')}"
        try:
            response = await gemini_client.generate_content_with_rotation(prompt)
            answer = re.sub(r'[^A-D]', '', response.text.upper())
            return answer if answer in options else None
        except Exception as e:
            format_and_log("TASK", "AI作答失败", {'问题': question, '错误': str(e)}, level=logging.ERROR)
            return None

    def _find_answer_in_db(self, question: str, options: dict) -> str | None:
        format_and_log("TASK", "流程步骤: 数据库查询", {'模块': self.log_module_name, '问题': question})
        if stored_answer_text := get_qa_answer_from_redis(self.redis_db, self.redis_db_name, question):
            for letter, text in options.items():
                if text == stored_answer_text:
                    format_and_log("TASK", "流程步骤: 数据库命中", {'模块': self.log_module_name, '答案': f'{letter} ({text})'})
                    return letter
        format_and_log("TASK", "流程步骤: 数据库未命中", {'模块': self.log_module_name, '详情': '将使用AI进行作答'})
        return None

    def _save_answer_to_db(self, question: str, answer_text: str):
        save_qa_answer_to_redis(self.redis_db, self.redis_db_name, question, answer_text)
        format_and_log("TASK", "流程步骤: 答案入库", {'来源': self.log_module_name, '问题': question, '答案': answer_text})

    async def handler(self, event):
        if not self.me: return
        text = event.message.text
        if not text or not all(keyword in text for keyword in self.keywords):
            return
            
        format_and_log("TASK", f"流程启动: {self.log_module_name}", {'状态': '关键词匹配成功', '消息ID': event.id})
        
        my_display_name = get_display_name(self.me)
        is_our_turn = f"@{self.me.username}" in text or f"@{my_display_name}" in text
        
        parsed_data = self.extract_question_options(text)
        question = parsed_data.get("question")
        options = parsed_data.get("options")
        
        if not (question and options and len(options) >= 4):
            format_and_log("TASK", f"流程中止: {self.log_module_name}", {'原因': '未能解析出有效的题目和选项', '原始文本': text})
            await self.client.send_admin_notification(f"⚠️ **解析失败通知 ({self.log_module_name})**\n\n无法从此条消息中完整解析出题目和四个选项，请检查原文并优化解析函数：\n-----------------\n`{text}`")
            return
        
        format_and_log("TASK", "流程步骤: 题目解析", {'模块': self.log_module_name, '问题': question, '选项': str(options), '是否轮到我': is_our_turn})
        
        answer_letter = self._find_answer_in_db(question, options)
        source = "本地知识库"
        
        if not answer_letter:
            source = "Gemini AI"
            answer_letter = await self._ask_gemini(question, options)
            if answer_letter:
                self._save_answer_to_db(question, options[answer_letter])
            else:
                format_and_log("TASK", f"流程中止: {self.log_module_name}", {'原因': 'AI未能返回有效答案'})

        if is_our_turn and answer_letter:
            log_data = {'模块': self.log_module_name, '回复内容': f".作答 {answer_letter}", '答案来源': source}
            format_and_log("TASK", "流程步骤: 准备作答", log_data)
            await asyncio.sleep(random.randint(5, 15))
            await event.message.reply(f".作答 {answer_letter}")
            format_and_log("TASK", f"流程完成: {self.log_module_name}", {'状态': '已发送作答指令'})
        elif is_our_turn:
            format_and_log("TASK", f"流程完成: {self.log_module_name}", {'状态': '放弃作答', '原因': '无法确定最终答案'})
        else:
            format_and_log("TASK", f"流程完成: {self.log_module_name}", {'状态': '无需作答', '原因': '未@本机'})

