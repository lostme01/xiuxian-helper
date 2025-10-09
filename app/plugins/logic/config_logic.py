# -*- coding: utf-8 -*-
import json
from app.config_manager import _load_config, update_nested_setting
from app.logging_service import LogType
from config import settings
# [重构] 从元数据中心导入配置定义
from app.config_meta import MODIFIABLE_CONFIGS, LOGGING_SWITCHES_META

# [重构] 动态生成反向映射
LOG_DESC_TO_SWITCH = {v: k for k, v in LOGGING_SWITCHES_META.items()}

def _get_nested_value(config_dict, path):
    """辅助函数，用于通过点分隔的路径获取嵌套字典的值"""
    keys = path.split('.')
    value = config_dict
    for key in keys:
        if isinstance(value, dict):
            value = value.get(key)
        else:
            # 兼容从 settings 对象中读取 (虽然现在不直接用了，但保留逻辑的健壮性)
            value = getattr(value, key, None)
        if value is None:
            return None
    return value


async def logic_get_config_item(key: str | None) -> str:
    """获取指定或所有可查询的配置项"""
    # [重构] 将 MODIFIABLE_CONFIGS 作为查询的数据源
    config_map = {alias: path for alias, (path, _) in MODIFIABLE_CONFIGS.items()}
    
    if not key:
        header = "✅ **可供查询的配置项如下 (请使用中文别名查询):**\n\n"
        keys_text = '\n'.join([f"- `{alias}`: {desc}" for alias, (_, desc) in sorted(MODIFIABLE_CONFIGS.items())])
        return header + keys_text

    if key not in config_map:
        return f"❓ 未知的配置项别名: `{key}`"

    path = config_map[key]
    full_config = _load_config()
    value = _get_nested_value(full_config, path)

    if "api_keys" in path or "password" in path or "api_hash" in path:
        value = "****** (出于安全考虑, 已隐藏)"

    if value is None:
        return f"❌ 查询配置 `{path}` 失败, 未在配置文件中找到该项。"

    # 尝试美化输出
    try:
        formatted_value = json.dumps(value, ensure_ascii=False, indent=2)
        lang = "json"
    except TypeError:
        formatted_value = str(value)
        lang = "text"
        
    return f"🔍 **配置项 [{key}]**\n当前值为:\n```{lang}\n{formatted_value}\n```"


async def logic_toggle_all_logs(enable: bool) -> str:
    """
    批量开启或关闭所有与消息相关的日志。
    """
    # 定义哪些是“消息”日志
    message_log_keys = [
        "msg_recv", "reply_recv", "log_edits", 
        "log_deletes", "original_log_enabled"
    ]
    
    full_config = _load_config()
    if not full_config:
        return "❌ 操作失败：无法加载配置文件。"
        
    current_switches = full_config.get('logging_switches', {})
    
    for key in message_log_keys:
        current_switches[key] = enable
        
    result = await update_nested_setting('logging_switches', current_switches)

    if "✅" in result:
        status_text = "开启" if enable else "关闭"
        return f"✅ 所有消息类日志已设置为 **{status_text}** 状态。"
    else:
        return result
