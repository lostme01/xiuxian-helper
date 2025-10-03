# -*- coding: utf-8 -*-
import yaml
import logging
from config import settings
from app.logger import format_and_log

def _load_config() -> dict:
    """加载当前的YAML配置文件"""
    try:
        with open(settings.CONFIG_FILE_PATH, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    except Exception as e:
        format_and_log("SYSTEM", "配置加载失败", {'错误': str(e)}, level=logging.ERROR)
        return {}

def _save_config(config_data: dict):
    """将配置数据写回YAML文件"""
    try:
        with open(settings.CONFIG_FILE_PATH, 'w', encoding='utf-8') as f:
            yaml.dump(config_data, f, allow_unicode=True, sort_keys=False)
        return True
    except Exception as e:
        format_and_log("SYSTEM", "配置写入失败", {'错误': str(e)}, level=logging.ERROR)
        return False

def update_setting(root_key: str, value, sub_key: str = None, success_message: str = "配置更新成功") -> str:
    """
    [修复版]
    更新配置项并写回文件，同时正确更新内存中的settings。
    """
    full_config = _load_config()
    
    try:
        if sub_key:
            if root_key not in full_config or not isinstance(full_config.get(root_key), dict):
                full_config[root_key] = {}
            full_config[root_key][sub_key] = value
            
            # --- 核心修复：正确查找并更新内存中的配置对象 ---
            # 模仿 config_management.py 中的查找逻辑，尝试多种可能的变量名
            settings_attr = getattr(settings, root_key.upper(), None)
            if settings_attr is None:
                settings_attr = getattr(settings, f"{root_key.upper()}_CONFIG", None)

            if settings_attr is not None and isinstance(settings_attr, dict):
                settings_attr[sub_key] = value
            else:
                 # 作为最后的保障，直接在 settings 模块上设置属性
                setattr(settings, sub_key.upper(), value)

        else:
            full_config[root_key] = value
            setattr(settings, root_key.upper(), value)

        if _save_config(full_config):
            return f"✅ {success_message}。(已保存至文件，立即生效)"
        else:
            return f"✅ {success_message}。(仅本次运行生效)"
            
    except Exception as e:
        error_msg = f"❌ 更新配置时发生内部错误: {e}"
        format_and_log("SYSTEM", "配置更新失败", {'错误': str(e)}, level=logging.ERROR)
        return error_msg
