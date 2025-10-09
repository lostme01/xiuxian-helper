# -*- coding: utf-8 -*-
import os
import importlib
import logging
from config import settings
from app.logging_service import LogType, format_and_log

def load_all_plugins(app):
    """
    [修复版]
    动态扫描并加载所有插件。
    - app: Application 的实例，传递给每个插件以便注册。
    """
    plugins_dir = os.path.dirname(__file__)
    # 确保有一个固定的加载顺序，例如按文件名
    for filename in sorted(os.listdir(plugins_dir)):
        if filename.endswith(".py") and not filename.startswith("__"):
            module_name = f"app.plugins.{filename[:-3]}"
            try:
                module = importlib.import_module(module_name)
                
                plugin_sect = getattr(module, '__plugin_sect__', None)
                if plugin_sect and plugin_sect != settings.SECT_NAME:
                    format_and_log(LogType.SYSTEM, "插件加载", {'模块': module_name, '状态': '已跳过', '原因': f'宗门不匹配 (需要 {plugin_sect}, 当前配置为 {settings.SECT_NAME})'})
                    continue

                if hasattr(module, "initialize") and callable(getattr(module, "initialize")):
                    module.initialize(app)
                    format_and_log(LogType.SYSTEM, "插件加载", {'模块': module_name, '状态': '成功'})
            
            except Exception as e:
                format_and_log(LogType.SYSTEM, "插件加载失败", {
                    '模块': module_name, 
                    '错误': str(e)
                }, level=logging.ERROR)
