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

# --- 核心修改：让函数返回字符串，而不是直接发送回复 ---
def update_setting(root_key: str, value, sub_key: str = None, success_message: str = "配置更新成功") -> str:
    """
    更新配置项并写回文件，同时更新内存中的settings。
    返回一个表示操作结果的字符串消息。
    """
    full_config = _load_config()
    
    try:
        if sub_key:
            # 更新嵌套配置 e.g., logging_switches: { system_activity: true }
            if root_key not in full_config or not isinstance(full_config.get(root_key), dict):
                full_config[root_key] = {}
            full_config[root_key][sub_key] = value
            # 更新内存中的配置
            settings_attr = getattr(settings, root_key.upper(), {})
            settings_attr[sub_key] = value
        else:
            # 更新顶级配置 e.g., sect_name: '黄枫谷'
            full_config[root_key] = value
            # 更新内存中的配置
            setattr(settings, root_key.upper(), value)

        if _save_config(full_config):
            return f"✅ {success_message}。(已保存至文件)"
        else:
            return f"✅ {success_message}。(仅本次运行生效)"
            
    except Exception as e:
        error_msg = f"❌ 更新配置时发生内部错误: {e}"
        format_and_log("SYSTEM", "配置更新失败", {'错误': str(e)}, level=logging.ERROR)
        return error_msg
