# -*- coding: utf-8 -*-
import logging
from functools import reduce
import operator
import sys

import yaml

from app.logging_service import LogType, format_and_log
from config import settings
from app.context import get_application


def _get_settings_object(root_key: str):
    """辅助函数，用于从全局 settings 对象中获取相应的配置字典。"""
    if hasattr(settings, root_key.upper()):
        return getattr(settings, root_key.upper())

    if hasattr(settings, f"{root_key.upper()}_CONFIG"):
        return getattr(settings, f"{root_key.upper()}_CONFIG")

    if root_key.endswith("_exam_solver"):
        var_name = root_key.replace("_solver", "").upper() + "_CONFIG"
        if hasattr(settings, var_name):
            return getattr(settings, var_name)

    if hasattr(settings, root_key.upper().replace('_', '')):
        return getattr(settings, root_key.upper().replace('_', ''))

    return None


def _load_config() -> dict:
    """读取完整的 prod.yaml 文件内容。"""
    try:
        with open(settings.CONFIG_FILE_PATH, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    except Exception as e:
        format_and_log(LogType.SYSTEM, "配置加载失败", {'文件': settings.CONFIG_FILE_PATH, '错误': str(e)}, level=logging.ERROR)
        return None


def _save_config(config_data: dict) -> bool:
    """直接覆盖写入原始文件。"""
    try:
        with open(settings.CONFIG_FILE_PATH, 'w', encoding='utf-8') as f:
            yaml.dump(config_data, f, allow_unicode=True, sort_keys=False, indent=2)
        return True
    except Exception as e:
        format_and_log(LogType.SYSTEM, "配置写入失败", {'文件': settings.CONFIG_FILE_PATH, '错误': str(e)}, level=logging.ERROR)
        return False


def _hot_reload_setting(path: str, value):
    """[修复版] 在内存中热更新配置，兼容顶级和嵌套配置"""
    if path == 'master_switch':
        try:
            app = get_application()
            app.master_switch = value
            format_and_log(LogType.SYSTEM, "配置热更新 (App State)", {'状态': '成功', '路径': path, '新值': value})
            return True, ""
        except Exception as e:
            return False, f"更新 App.master_switch 失败: {e}"

    keys = path.split('.')
    try:
        # --- 核心修复：处理顶级配置项 ---
        if len(keys) == 1:
            key_name = keys[0].upper()
            # 直接在 settings 模块上设置属性值
            if hasattr(settings, key_name):
                setattr(sys.modules['config.settings'], key_name, value)
                format_and_log(LogType.SYSTEM, "配置热更新", {'状态': '成功', '路径': path, '新值': value})
                return True, ""
            else:
                raise AttributeError(f"在 settings 模块中未找到顶层配置项: {key_name}")
        
        # --- 原有逻辑：处理嵌套配置项 ---
        settings_obj = _get_settings_object(keys[0])
        if settings_obj is None:
            raise AttributeError(f"在 settings 中未找到顶层配置对象: {keys[0]}")

        parent = reduce(operator.getitem, keys[1:-1], settings_obj)
        parent[keys[-1]] = value
        format_and_log(LogType.SYSTEM, "配置热更新", {'状态': '成功', '路径': path, '新值': value})
        return True, ""
    except (AttributeError, KeyError, TypeError) as e:
        return False, f"内存热更新失败: {e}"


async def update_setting(root_key: str, sub_key: str, value, success_message: str) -> str:
    """
    [标准接口]
    更新一个顶层配置项 (如: logging_switches.debug_log)。
    """
    path = f"{root_key}.{sub_key}"
    result = await update_nested_setting(path, value)
    if "✅" in result:
        return f"✅ **{success_message}**。\n(已保存至文件，立即生效)"
    else:
        # 如果底层函数报错，直接返回详细错误
        return result


async def update_nested_setting(path: str, value) -> str:
    """
    [标准接口]
    更新一个嵌套的配置项，这是所有配置修改的最终入口。
    """
    keys = path.split('.')
    if not keys:
        return "❌ 路径不能为空。"

    # 尝试转换 value 类型
    if isinstance(value, str):
        try:
            processed_value = int(value)
        except ValueError:
            if value.lower() == 'true':
                processed_value = True
            elif value.lower() == 'false':
                processed_value = False
            else:
                processed_value = value
    else:
        processed_value = value

    config = _load_config()
    if config is None:
        return "❌ **修改失败**: 无法加载配置文件。"

    d = config
    for key in keys[:-1]:
        d = d.setdefault(key, {})
    d[keys[-1]] = processed_value

    if not _save_config(config):
        return "❌ **修改失败**: 写入配置文件时发生错误。"

    success, err_msg = _hot_reload_setting(path, processed_value)
    if success:
        return f"✅ 配置 **{path}** 已更新为 `{value}`。"
    else:
        return f"⚠️ 配置文件已更新，但内存热重载失败: {err_msg}。配置将在下次重启后生效。"

