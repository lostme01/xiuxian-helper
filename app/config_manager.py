# -*- coding: utf-8 -*-
import yaml
import logging
import os
from functools import reduce
import operator
from config import settings
from app.logger import format_and_log

def _get_settings_object(root_key: str):
    """
    [重构] [已修复]
    辅助函数，用于从全局 settings 对象中获取相应的配置字典。
    增加了对 exam_solver 类型配置的特殊处理。
    """
    # 尝试按大写形式匹配 (e.g., task_switches -> TASK_SWITCHES)
    if hasattr(settings, root_key.upper()):
        return getattr(settings, root_key.upper())
    
    # 尝试按 "_CONFIG" 后缀匹配 (e.g., taiyi_sect -> TAIYI_SECT_CONFIG)
    if hasattr(settings, f"{root_key.upper()}_CONFIG"):
        return getattr(settings, f"{root_key.upper()}_CONFIG")
        
    # [新增修复逻辑] 处理 exam_solver 的特殊命名
    # e.g., 'xuangu_exam_solver' -> 'XUANGU_EXAM_CONFIG'
    if root_key.endswith("_exam_solver"):
        var_name = root_key.replace("_solver", "").upper() + "_CONFIG"
        if hasattr(settings, var_name):
            return getattr(settings, var_name)

    # 兼容不带_CONFIG后缀的配置对象
    if hasattr(settings, root_key.upper().replace('_', '')):
        return getattr(settings, root_key.upper().replace('_', ''))
        
    return None

def _load_config() -> dict:
    """读取完整的 prod.yaml 文件内容。"""
    try:
        with open(settings.CONFIG_FILE_PATH, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    except Exception as e:
        format_and_log("SYSTEM", "配置加载失败", {'文件': settings.CONFIG_FILE_PATH, '错误': str(e)}, level=logging.ERROR)
        return None # 返回 None 表示加载失败

def _save_config(config_data: dict) -> bool:
    """
    [最终优化版]
    使用“写入临时文件并替换”的安全模式来保存配置。
    """
    temp_file_path = settings.CONFIG_FILE_PATH + ".tmp"
    try:
        with open(temp_file_path, 'w', encoding='utf-8') as f:
            yaml.dump(config_data, f, allow_unicode=True, sort_keys=False)
        
        # 原子操作，用新文件替换旧文件
        os.replace(temp_file_path, settings.CONFIG_FILE_PATH)
        return True
    except Exception as e:
        format_and_log("SYSTEM", "配置写入失败", {'文件': settings.CONFIG_FILE_PATH, '错误': str(e)}, level=logging.ERROR)
        if os.path.exists(temp_file_path):
            try: os.remove(temp_file_path)
            except OSError: pass
        return False

def update_setting(root_key: str, sub_key: str, value, success_message: str) -> str:
    """
    [最终优化版]
    一个健壮的函数，负责同时更新内存（热更新）和配置文件。
    """
    # 1. 更新内存中的实时配置
    try:
        settings_attr = _get_settings_object(root_key)
        if settings_attr is not None and isinstance(settings_attr, dict):
            settings_attr[sub_key] = value
            log_key = f"{root_key}.{sub_key}"
            format_and_log("SYSTEM", "配置热更新", {'状态': '成功', '键': log_key, '新值': value})
        else:
            raise AttributeError(f"在 settings 中未找到可修改的配置对象: {root_key}")
    except Exception as e:
        format_and_log("SYSTEM", "配置热更新失败", {'错误': str(e)}, level=logging.ERROR)
        return f"❌ **内存更新失败**: {e}"

    # 2. 更新配置文件
    full_config = _load_config()
    # 如果加载失败，则无法保存
    if full_config is None:
        return f"⚠️ **{success_message}**。\n(仅本次运行生效，因配置文件读取失败无法保存)"

    if root_key not in full_config or not isinstance(full_config.get(root_key), dict):
        full_config[root_key] = {}
    full_config[root_key][sub_key] = value

    if _save_config(full_config):
        return f"✅ **{success_message}**。\n(已保存至文件，重启后依然生效)"
    else:
        return f"⚠️ **{success_message}**。\n(仅本次运行生效，文件写入失败)"

def update_nested_setting(path: str, value) -> str:
    # (此函数保持不变，但为了文件完整性，一并提供)
    keys = path.split('.')
    if not keys:
        return "❌ 路径不能为空。"

    try:
        processed_value = int(value)
    except ValueError:
        if value.lower() == 'true':
            processed_value = True
        elif value.lower() == 'false':
            processed_value = False
        else:
            processed_value = value

    config = _load_config()
    if config is None:
        return f"❌ **修改失败**: 无法加载配置文件，请检查文件是否存在或格式是否正确。"
        
    d = config
    for key in keys[:-1]:
        d = d.setdefault(key, {})
    d[keys[-1]] = processed_value
    
    try:
        top_level_attr_name = keys[0]
        attr = _get_settings_object(top_level_attr_name)
        if attr is None:
             raise AttributeError(f"在 settings 中未找到顶层配置对象: {top_level_attr_name}")
        
        reduce(operator.getitem, keys[1:-1], attr)[keys[-1]] = processed_value
        format_and_log("SYSTEM", "配置热更新", {'状态': '成功', '路径': path, '新值': processed_value})
    except (AttributeError, KeyError) as e:
         return f"⚠️ 内存热更新失败: {e}。配置已写入文件，重启后生效。"
        
    if _save_config(config):
        return f"✅ 配置 **{path}** 已更新为 `{value}`。(已保存至文件，立即生效)"
    else:
        return f"⚠️ 配置 **{path}** 已更新为 `{value}`。(仅本次运行生效，文件写入失败)"
