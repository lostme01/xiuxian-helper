# -*- coding: utf-8 -*-
import google.generativeai as genai
import asyncio
import random
import logging
from config import settings
from app.logger import format_and_log

# --- 优化：将 Key 管理封装到类中 ---
class ApiKeyManager:
    def __init__(self, keys):
        self._api_keys = keys
        self._current_key_index = 0
        if self._api_keys:
            self._current_key_index = random.randint(0, len(self._api_keys) - 1)

    def get_all_keys_with_start_index(self):
        if not self._api_keys:
            return []
        
        start_index = self._current_key_index
        # 生成一个从当前索引开始的轮询列表
        return [(self._api_keys[(start_index + i) % len(self._api_keys)], (start_index + i) % len(self._api_keys)) for i in range(len(self._api_keys))]

    @property
    def key_count(self):
        return len(self._api_keys)

# --- 模块级变量 ---
_api_key_manager = None
_model_name = None 
_tool_config = {"function_calling_config": {"mode": "none"}}

def initialize_gemini():
    """从配置加载API Keys并准备轮询"""
    global _api_key_manager, _model_name
    
    _model_name = settings.GEMINI_MODEL_NAME

    keys = settings.EXAM_SOLVER_CONFIG.get('gemini_api_keys', [])

    if not keys or not isinstance(keys, list):
        format_and_log("SYSTEM", "组件初始化", {'组件': 'Gemini Client', '状态': '已禁用，未在配置中找到 gemini_api_keys 列表'})
        return False
    
    _api_key_manager = ApiKeyManager(keys)
    
    format_and_log("SYSTEM", "组件初始化", {
        '组件': 'Gemini Client', 
        '状态': '初始化成功',
        '可用Key数量': _api_key_manager.key_count,
        '选用模型': _model_name
    })
    return True


async def generate_content_with_rotation(prompt: str):
    """
    使用轮询和重试机制来生成内容。
    在每次尝试时都创建新的模型实例。
    """
    if not _api_key_manager or _api_key_manager.key_count == 0:
        raise RuntimeError("Gemini Client 未成功初始化或未配置 API Keys。")

    # 获取从当前 key 开始的轮询列表
    keys_to_try = _api_key_manager.get_all_keys_with_start_index()

    for selected_key, current_index in keys_to_try:
        try:
            format_and_log("DEBUG", "AI请求", {'Key索引': current_index, 'Prompt': '正在构建请求...'})
            
            genai.configure(api_key=selected_key)
            
            model = genai.GenerativeModel(model_name=_model_name, tool_config=_tool_config)
            
            response = await model.generate_content_async(prompt)
            format_and_log("DEBUG", "AI响应", {'Key索引': current_index, 'Response': response.text})
            
            # 成功后，将下一个 key 设置为轮询起点
            _api_key_manager._current_key_index = (current_index + 1) % _api_key_manager.key_count
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

