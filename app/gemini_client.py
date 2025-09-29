# -*- coding: utf-8 -*-
import google.generativeai as genai
import asyncio
import random
import logging
from config import settings
from app.logger import format_and_log

# --- 模块级变量 ---
_api_keys = []
_current_key_index = 0
_model_name = None 
_tool_config = {"function_calling_config": {"mode": "none"}}

def initialize_gemini():
    """从配置加载API Keys并准备轮询"""
    global _api_keys, _current_key_index, _model_name
    
    # 在函数内部读取模型名称，确保 settings 已完全加载
    _model_name = settings.GEMINI_MODEL_NAME

    keys = settings.EXAM_SOLVER_CONFIG.get('gemini_api_keys', [])

    if not keys or not isinstance(keys, list):
        format_and_log("SYSTEM", "组件初始化", {'组件': 'Gemini Client', '状态': '已禁用，未在配置中找到 gemini_api_keys 列表'})
        return False
    
    _api_keys = keys
    _current_key_index = random.randint(0, len(_api_keys) - 1)
    
    format_and_log("SYSTEM", "组件初始化", {
        '组件': 'Gemini Client', 
        '状态': '初始化成功',
        '可用Key数量': len(_api_keys),
        '选用模型': _model_name
    })
    return True


async def generate_content_with_rotation(prompt: str):
    """
    使用轮询和重试机制来生成内容。
    在每次尝试时都创建新的模型实例。
    """
    global _current_key_index
    
    if not _api_keys:
        raise RuntimeError("Gemini Client 未成功初始化或未配置 API Keys。")

    start_index = _current_key_index
    for i in range(len(_api_keys)):
        current_index = (start_index + i) % len(_api_keys)
        selected_key = _api_keys[current_index]
        
        try:
            format_and_log("DEBUG", "AI请求", {'Key索引': current_index, 'Prompt': '正在构建请求...'})
            
            genai.configure(api_key=selected_key)
            
            model = genai.GenerativeModel(model_name=_model_name, tool_config=_tool_config)
            
            response = await model.generate_content_async(prompt)
            format_and_log("DEBUG", "AI响应", {'Key索引': current_index, 'Response': response.text})
            
            _current_key_index = (current_index + 1) % len(_api_keys)
            return response

        except Exception as e:
            format_and_log("SYSTEM", "API Key 调用失败", {
                'Key索引': current_index,
                '错误类型': type(e).__name__,
                '错误详情': str(e),
                '操作': '将自动尝试下一个Key...'
            }, level=logging.WARNING)
            await asyncio.sleep(1)

    format_and_log("SYSTEM", "API Key 调用失败", {'错误': '所有API Key均调用失败'}, level=logging.ERROR)
    raise RuntimeError("所有API Key均调用失败。")

