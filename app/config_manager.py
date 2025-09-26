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

async def update_setting(event, root_key, value, sub_key=None, success_message="配置更新成功"):
    """
    更新配置项并写回文件，同时更新内存中的settings。
    :param event: Telethon的事件对象，用于回复消息。
    :param root_key: 要更新的顶级键或在settings中的属性名（小写）。
    :param value: 新的值。
    :param sub_key: 如果要更新的是嵌套字典中的值，则提供此子键。
    :param success_message: 成功后回复给用户的消息。
    """
    full_config = _load_config()
    target_obj_config = full_config
    target_obj_settings = settings
    
    try:
        if sub_key:
            # 更新嵌套配置 e.g., logging_switches: { system_activity: true }
            if root_key not in target_obj_config or not isinstance(target_obj_config.get(root_key), dict):
                target_obj_config[root_key] = {}
            target_obj_config[root_key][sub_key] = value
            # 更新内存中的配置
            settings_attr = getattr(settings, root_key.upper(), {})
            settings_attr[sub_key] = value
        else:
            # 更新顶级配置 e.g., sect_name: '黄枫谷'
            target_obj_config[root_key] = value
            # 更新内存中的配置
            setattr(settings, root_key.upper(), value)

        if _save_config(full_config):
            await event.reply(f"✅ {success_message}。(已保存至文件)", parse_mode='md')
        else:
            await event.reply(f"✅ {success_message}。(仅本次运行生效)", parse_mode='md')
            
    except Exception as e:
        error_msg = f"❌ 更新配置时发生内部错误: {e}"
        await event.reply(error_msg)
        format_and_log("SYSTEM", "配置更新失败", {'错误': str(e)}, level=logging.ERROR)

