# -*- coding: utf-8 -*-
import asyncio
import logging
import random

import google.generativeai as genai

from app.logging_service import LogType, format_and_log
from config import settings


class ApiKeyManager:
    def __init__(self, keys):
        self._api_keys = keys if keys else []
        self._current_key_index = 0
        if self._api_keys:
            self._current_key_index = random.randint(0, len(self._api_keys) - 1)

    def get_all_keys_with_start_index(self):
        if not self._api_keys:
            return []

        start_index = self._current_key_index
        return [(self._api_keys[(start_index + i) % len(self._api_keys)], (start_index + i) % len(self._api_keys)) for i in
                range(len(self._api_keys))]

    @property
    def key_count(self):
        return len(self._api_keys)


_api_key_manager = None
_model_priority_list = []
_tool_config = {"function_calling_config": {"mode": "none"}}


def initialize_gemini():
    """从配置加载API Keys和模型列表并准备轮询"""
    global _api_key_manager, _model_priority_list

    _model_priority_list = settings.GEMINI_MODEL_NAMES
    keys = settings.EXAM_SOLVER_CONFIG.get('gemini_api_keys', [])

    if not keys or not isinstance(keys, list):
        format_and_log(LogType.SYSTEM, "组件初始化",
                       {'组件': 'Gemini Client', '状态': '已禁用，未在配置中找到 gemini_api_keys 列表'})
        return False

    _api_key_manager = ApiKeyManager(keys)

    format_and_log(LogType.SYSTEM, "组件初始化", {
        '组件': 'Gemini Client',
        '状态': '初始化成功',
        '可用Key数量': _api_key_manager.key_count,
        '答题模型优先级': ' -> '.join(_model_priority_list)
    })
    return True


async def generate_content(prompt: str):
    """
    使用模型优先级和API Key轮询来生成内容。
    """
    if not _api_key_manager or _api_key_manager.key_count == 0:
        raise RuntimeError("Gemini Client 未成功初始化或未配置 API Keys。")

    format_and_log(LogType.DEBUG, "Gemini-请求", {'Prompt': prompt})

    keys_to_try = _api_key_manager.get_all_keys_with_start_index()
    all_errors = []

    for model_name in _model_priority_list:
        model_errors = []
        format_and_log(LogType.DEBUG, "Gemini-模型尝试", {'模型': model_name})

        for selected_key, current_index in keys_to_try:
            try:
                genai.configure(api_key=selected_key)
                model = genai.GenerativeModel(model_name=model_name, tool_config=_tool_config)

                response = await asyncio.wait_for(
                    model.generate_content_async(prompt),
                    timeout=30.0
                )

                format_and_log(LogType.DEBUG, "Gemini-响应", {'模型': model_name, 'Key索引': current_index, '原始返回': response.text})

                _api_key_manager._current_key_index = (current_index + 1) % _api_key_manager.key_count
                return response

            except Exception as e:
                error_repr = repr(e)
                model_errors.append(f"Key[{current_index}]: {error_repr}")
                format_and_log(
                    LogType.WARNING,
                    "Gemini-单次调用失败", {
                        '模型': model_name,
                        'Key索引': current_index,
                        '原始错误': error_repr,
                        '操作': '将自动尝试下一个Key...'
                    }
                )
                await asyncio.sleep(1)

        all_errors.append(f"模型 [{model_name}] 失败:\n" + "\n".join(model_errors))

    final_error_report = "\n\n".join(all_errors)
    raise RuntimeError(f"所有模型和API Key均调用失败。\n\n详细原因:\n{final_error_report}")
