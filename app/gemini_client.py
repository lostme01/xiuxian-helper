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
    使用轮询和重试机制来生成内容，并增加了详细的错误日志。
    """
    if not _api_key_manager or _api_key_manager.key_count == 0:
        raise RuntimeError("Gemini Client 未成功初始化或未配置 API Keys。")

    format_and_log("DEBUG", "Gemini-请求", {'Prompt': prompt})

    keys_to_try = _api_key_manager.get_all_keys_with_start_index()

    for selected_key, current_index in keys_to_try:
        try:
            genai.configure(api_key=selected_key)
            model = genai.GenerativeModel(model_name=_model_name, tool_config=_tool_config)
            
            response = await asyncio.wait_for(
                model.generate_content_async(prompt),
                timeout=30.0
            )
            
            format_and_log("DEBUG", "Gemini-响应", {'Key索引': current_index, '原始返回': response.text})
            
            _api_key_manager._current_key_index = (current_index + 1) % _api_key_manager.key_count
            return response
        
        # [核心修改] 将所有异常都以ERROR级别详细记录
        except Exception as e:
            error_type = type(e).__name__
            error_detail = str(e)
            
            # 对常见的错误类型进行更友好的解释
            if "API key not valid" in error_detail:
                error_explanation = "API Key无效或不正确"
            elif "rate limit" in error_detail.lower():
                error_explanation = "已达到此Key的请求频率限制"
            elif isinstance(e, asyncio.TimeoutError):
                error_explanation = "API请求在30秒内未返回结果 (网络超时或Google服务器繁忙)"
            else:
                error_explanation = "未知错误"

            format_and_log(
                "ERROR", # 使用ERROR级别，确保日志一定会被打印
                "Gemini-单次调用失败", {
                    'Key索引': current_index,
                    '错误类型': error_type,
                    '错误详情': error_detail,
                    '可能原因': error_explanation,
                    '操作': '将自动尝试下一个Key...'
                }
            )
            await asyncio.sleep(1)

    format_and_log("ERROR", "Gemini-API调用失败", {'错误': '所有API Key均调用失败'})
    raise RuntimeError("所有API Key均调用失败。")
