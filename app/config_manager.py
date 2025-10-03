# -*- coding: utf-8 -*-
import yaml
import logging
from functools import reduce
import operator
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
    full_config = _load_config()
    try:
        if sub_key:
            if root_key not in full_config or not isinstance(full_config.get(root_key), dict):
                full_config[root_key] = {}
            full_config[root_key][sub_key] = value
            
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

def update_nested_setting(path: str, value) -> str:
    """
    [新功能]
    通过点分隔的路径，更新深层嵌套的配置项。
    """
    keys = path.split('.')
    if not keys:
        return "❌ 路径不能为空。"

    # 尝试转换值的类型
    try:
        processed_value = int(value)
    except ValueError:
        if value.lower() == 'true':
            processed_value = True
        elif value.lower() == 'false':
            processed_value = False
        else:
            processed_value = value # 保持为字符串

    # 更新 YAML 文件
    config = _load_config()
    d = config
    for key in keys[:-1]:
        d = d.setdefault(key, {})
    d[keys[-1]] = processed_value
    
    # 更新内存中的 settings 对象
    try:
        # settings 对象的属性通常是大写的，例如 auto_delete_strategies -> AUTO_DELETE_STRATEGIES
        # 我们需要找到顶层的属性
        top_level_attr = keys[0].upper()
        
        # 特殊处理 _config 后缀
        if hasattr(settings, f"{top_level_attr}_CONFIG"):
             top_level_attr = f"{top_level_attr}_CONFIG"

        attr = getattr(settings, top_level_attr)
        
        # 遍历更新嵌套的字典
        reduce(operator.getitem, keys[1:-1], attr)[keys[-1]] = processed_value
        format_and_log("SYSTEM", "配置热更新", {'状态': '成功', '路径': path, '新值': processed_value})
    except (AttributeError, KeyError) as e:
         return f"⚠️ 内存热更新失败: {e}。配置已写入文件，重启后生效。"
        
    if _save_config(config):
        return f"✅ 配置 **{path}** 已更新为 `{value}`。(已保存至文件，立即生效)"
    else:
        return f"⚠️ 配置 **{path}** 已更新为 `{value}`。(仅本次运行生效，文件写入失败)"
