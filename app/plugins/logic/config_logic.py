# -*- coding: utf-8 -*-
import json
from config import settings
from app.config_manager import _load_config, update_nested_setting
from app.logger import LOG_DESC_TO_SWITCH, LOG_SWITCH_TO_DESC

CONFIG_MAP = {
    "指令前缀": "command_prefixes", "宗门名称": "sect_name", "时区": "timezone",
    "指令超时": "command_timeout",
    "发送延迟min": "send_delay.min", "发送延迟max": "send_delay.max",
    "闭关开关": "task_switches.biguan", "点卯开关": "task_switches.dianmao",
    "学习开关": "task_switches.learn_recipes", "药园开关": "task_switches.garden_check",
    "自动删除开关": "auto_delete.enabled", "AI模型": "exam_solver.gemini_model_name",
    "药园播种种子": "huangfeng_valley.garden_sow_seed",
    "引道冷却(时)": "taiyi_sect.yindao_success_cooldown_hours",
    "引道指令": "game_commands.taiyi_yindao",
}

def _get_nested_value(config_dict, path):
    """辅助函数，用于通过点分隔的路径获取嵌套字典的值"""
    keys = path.split('.')
    value = config_dict
    for key in keys:
        if isinstance(value, dict):
            value = value.get(key)
        else:
            # 兼容从 settings 对象中读取
            value = getattr(value, key, None)
        if value is None:
            return None
    return value

async def logic_get_config_item(key: str | None) -> str:
    """获取指定或所有可查询的配置项"""
    if not key:
        header = "✅ **可供查询的配置项如下 (请使用中文名查询):**\n\n"
        keys_text = '\n'.join([f"- `{k}`" for k in sorted(CONFIG_MAP.keys())])
        return header + keys_text
        
    if key not in CONFIG_MAP:
        return f"❓ 未知的配置项: `{key}`"
        
    path = CONFIG_MAP[key]
    full_config = _load_config()
    value = _get_nested_value(full_config, path)
    
    if "api_keys" in path or "password" in path: 
        value = "****** (出于安全考虑, 已隐藏)"

    if value is None:
        # 尝试从 settings 对象中读取
        value = _get_nested_value(settings, path.upper())
        if value is None:
            return f"❌ 查询配置 `{path}` 失败, 未在配置文件或默认设置中找到该项。"
        
    formatted_value = json.dumps(value, ensure_ascii=False, indent=2)
    return f"🔍 **配置项 [{key}]**\n当前值为:\n```json\n{formatted_value}\n```"


async def logic_toggle_all_logs(enable: bool) -> str:
    """
    [重构] 批量开启或关闭所有日志，统一调用标准接口。
    """
    # 1. 构建完整的、新的 logging_switches 字典
    new_switches = {switch_name: enable for switch_name in LOG_DESC_TO_SWITCH.values()}
    
    # 2. 调用标准接口，一次性更新整个字典
    result = await update_nested_setting('logging_switches', new_switches)
    
    if "✅" in result:
        status_text = "开启" if enable else "关闭"
        return f"✅ 所有日志模块已设置为 **{status_text}** 状态。"
    else:
        # 如果出错，直接返回 config_manager 提供的详细错误信息
        return result

