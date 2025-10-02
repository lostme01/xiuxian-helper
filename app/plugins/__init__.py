# -*- coding: utf-8 -*-
import os
import importlib
import logging
from config import settings
from app.logger import format_and_log

def load_all_plugins(app):
    """
    动态扫描并加载所有插件。
    - app: Application 的实例，传递给每个插件以便注册。
    """
    plugins_dir = os.path.dirname(__file__)
    for filename in os.listdir(plugins_dir):
        if filename.endswith(".py") and not filename.startswith("__"):
            module_name = f"app.plugins.{filename[:-3]}"
            try:
                module = importlib.import_module(module_name)
                
                # --- 核心逻辑：检查宗门专属元数据 ---
                plugin_sect = getattr(module, '__plugin_sect__', None)
                if plugin_sect and plugin_sect != settings.SECT_NAME:
                    format_and_log("SYSTEM", "插件加载", {'模块': module_name, '状态': '已跳过', '原因': f'宗门不匹配 (需要 {plugin_sect})'})
                    continue # 跳过该插件的初始化

                if hasattr(module, "initialize") and callable(getattr(module, "initialize")):
                    module.initialize(app)
                    format_and_log("SYSTEM", "插件加载", {'模块': module_name, '状态': '成功'})
                # (对于没有 initialize 的组件文件，加载器现在会静默跳过，不再警告)
            
            except Exception as e:
                format_and_log("SYSTEM", "插件加载失败", {
                    '模块': module_name, 
                    '错误': str(e)
                }, level=logging.ERROR)
