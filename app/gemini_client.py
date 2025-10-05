# -*- coding: utf-8 -*-
import google.generativeai as genai
import asyncio
import random
import logging
from config import settings
from app.logger import format_and_log

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
        return [(self._api_keys[(start_index + i) % len(self._api_keys)], (start_index + i) % len(self._api_keys)) for i in range(len(self._api_keys))]

    @property
    def key_count(self):
        return len(self._api_keys)

_api_key_manager = None
_default_model_name = None 
_tool_config = {"function_calling_config": {"mode": "none"}}

def initialize_gemini():
    """从配置加载API Keys并准备轮询"""
    global _api_key_manager, _default_model_name
    
    _default_model_name = settings.GEMINI_MODEL_NAME
    keys = settings.EXAM_SOLVER_CONFIG.get('gemini_api_keys', [])

    if not keys or not isinstance(keys, list):
        format_and_log("SYSTEM", "组件初始化", {'组件': 'Gemini Client', '状态': '已禁用，未在配置中找到 gemini_api_keys 列表'})
        return False
    
    _api_key_manager = ApiKeyManager(keys)
    
    format_and_log("SYSTEM", "组件初始化", {
        '组件': 'Gemini Client', 
        '状态': '初始化成功',
        '可用Key数量': _api_key_manager.key_count,
        '默认模型 (答题用)': _default_model_name
    })
    return True


async def generate_content_with_rotation(prompt: str, model_name: str = None):
    """
    [最终版]
    使用轮询和重试机制来生成内容，并允许动态指定模型。
    """
    if not _api_key_manager or _api_key_manager.key_count == 0:
        raise RuntimeError("Gemini Client 未成功初始化或未配置 API Keys。")

    final_model_name = model_name or _default_model_name
    format_and_log("DEBUG", "Gemini-请求", {'模型': final_model_name, 'Prompt': prompt})

    keys_to_try = _api_key_manager.get_all_keys_with_start_index()
    
    failed_reasons = []

    for selected_key, current_index in keys_to_try:
        try:
            genai.configure(api_key=selected_key)
            model = genai.GenerativeModel(model_name=final_model_name, tool_config=_tool_config)
            
            response = await asyncio.wait_for(
                model.generate_content_async(prompt),
                timeout=30.0
            )
            
            format_and_log("DEBUG", "Gemini-响应", {'Key索引': current_index, '原始返回': response.text})
            
            _api_key_manager._current_key_index = (current_index + 1) % _api_key_manager.key_count
            return response
        
        except Exception as e:
            error_repr = repr(e)
            failed_reasons.append(f"Key[{current_index}]: {error_repr}")

            format_and_log(
                "ERROR",
                "Gemini-单次调用失败", {
                    'Key索引': current_index,
                    '原始错误': error_repr,
                    '操作': '将自动尝试下一个Key...'
                }
            )
            await asyncio.sleep(1)

    all_errors = "\n".join(failed_reasons)
    raise RuntimeError(f"所有API Key均调用失败。\n\n详细原因:\n{all_errors}")
