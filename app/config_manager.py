# -*- coding: utf-8 -*-
import yaml
import logging
from config import settings
from app.logger import format_and_log

def _load_config() -> dict:
    try:
        with open(settings.CONFIG_FILE_PATH, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    except Exception as e:
        format_and_log("SYSTEM", "配置加载失败", {'错误': str(e)}, level=logging.ERROR)
        return {}

def _save_config(config_data: dict):
    try:
        with open(settings.CONFIG_FILE_PATH, 'w', encoding='utf-8') as f:
            yaml.dump(config_data, f, allow_unicode=True, sort_keys=False)
        return True
    except Exception as e:
        format_and_log("SYSTEM", "配置写入失败", {'错误': str(e)}, level=logging.ERROR)
        return False

def _get_settings_object(root_key: str) -> dict | None:
    """
    一个健壮的函数，用于在settings模块中根据不同的命名模式查找配置对象。
    """
    if hasattr(settings, root_key.upper()):
        return getattr(settings, root_key.upper())
    if hasattr(settings, f"{root_key.upper()}_CONFIG"):
        return getattr(settings, f"{root_key.upper()}_CONFIG")
    if root_key.endswith('_solver'):
        base_name = root_key.replace('_solver', '')
        if hasattr(settings, f"{base_name.upper()}_CONFIG"):
            return getattr(settings, f"{base_name.upper()}_CONFIG")
    return None

def update_setting(root_key: str, value, sub_key: str = None, success_message: str = "配置更新成功") -> str:
    """
    [最终修复版]
    更新配置项并写回文件，同时正确更新内存中的settings，使修改即时生效。
    """
    full_config = _load_config()
    
    try:
        if sub_key:
            if root_key not in full_config or not isinstance(full_config.get(root_key), dict):
                full_config[root_key] = {}
            full_config[root_key][sub_key] = value
            
            # --- 核心修改：使用新的健壮的查找函数 ---
            settings_attr = _get_settings_object(root_key)

            if settings_attr is not None and isinstance(settings_attr, dict):
                settings_attr[sub_key] = value
                format_and_log("SYSTEM", "配置热更新", {'状态': '成功', '键': f"{root_key}.{sub_key}", '新值': value})
            else:
                setattr(settings, sub_key.upper(), value)
                format_and_log("SYSTEM", "配置热更新", {'状态': '成功 (直接设置)', '键': sub_key.upper(), '新值': value})

        else:
            full_config[root_key] = value
            setattr(settings, root_key.upper(), value)
            format_and_log("SYSTEM", "配置热更新", {'状态': '成功', '键': root_key.upper(), '新值': value})

        if _save_config(full_config):
            return f"✅ {success_message}。(已保存至文件，立即生效)"
        else:
            return f"✅ {success_message}。(仅本次运行生效，文件写入失败)"
            
    except Exception as e:
        error_msg = f"❌ 更新配置时发生内部错误: {e}"
        format_and_log("SYSTEM", "配置更新失败", {'错误': str(e)}, level=logging.ERROR)
        return error_msg
