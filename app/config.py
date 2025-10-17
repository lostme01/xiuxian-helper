# -*- coding: utf-8 -*-
import logging
import os
import sys
from functools import lru_cache

import yaml
from dotenv import load_dotenv

from app.config_validator import ConfigModel
from app.logging_service import format_and_log, LogType

class _Config:
    def __init__(self):
        self.config_data = None
        self._load_config()

    def _load_config(self):
        """
        加载、验证并合并所有配置源 (YAML, .env)。
        """
        try:
            load_dotenv()

            with open('config/prod.yaml', 'r', encoding='utf-8') as f:
                yaml_config = yaml.safe_load(f)

            # 合并 .env 变量
            yaml_config['api_hash'] = os.getenv('API_HASH') or yaml_config.get('api_hash')
            if 'redis' in yaml_config and isinstance(yaml_config['redis'], dict):
                yaml_config['redis']['password'] = os.getenv('REDIS_PASSWORD') or yaml_config['redis'].get('password')
            
            gemini_keys_from_env = os.getenv('GEMINI_API_KEYS')
            if gemini_keys_from_env:
                try:
                    import json
                    keys = json.loads(gemini_keys_from_env)
                    if isinstance(keys, list) and 'exam_solver' in yaml_config:
                        yaml_config['exam_solver']['gemini_api_keys'] = keys
                except Exception:
                    print("警告: 无法解析环境变量 GEMINI_API_KEYS，它不是有效的 JSON 格式。")


            # 使用 Pydantic 进行验证和类型转换
            self.config_data = ConfigModel(**yaml_config)
            print("✅ 配置文件 `config/prod.yaml` 及 `.env` 已成功加载并验证。")

        except FileNotFoundError:
            print(f"❌ 严重错误: 配置文件 `config/prod.yaml` 未找到。程序无法启动。")
            sys.exit(1)
        except Exception as e:
            print(f"❌ 严重错误: 加载或验证配置文件时出错: {e}。请检查 `config/prod.yaml` 和 `.env` 的格式与内容。")
            sys.exit(1)

    def get(self, key_path: str, default=None):
        """
        通过点分隔的路径安全地获取配置项。
        示例: config.get('redis.host')
        """
        try:
            value = self.config_data
            for key in key_path.split('.'):
                if isinstance(value, dict):
                    value = value.get(key)
                else:
                    value = getattr(value, key)
            return value if value is not None else default
        except (AttributeError, KeyError):
            return default

    def __getattr__(self, name):
        """
        允许通过属性访问顶层配置模型。
        示例: config.redis
        """
        if self.config_data and hasattr(self.config_data, name):
            return getattr(self.config_data, name)
        raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")

# 创建一个全局单例
# @lru_cache(maxsize=None)
def get_config_instance():
    return _Config()

config = get_config_instance()

# --- 提供一些便捷的顶级导出，以减少代码修改范围 ---
# 只有最高频、最稳定的配置项才应放在这里
API_ID = config.api_id
API_HASH = config.api_hash
ADMIN_USER_ID = config.admin_user_id
GAME_BOT_IDS = config.game_bot_ids
GAME_GROUP_IDS = config.game_group_ids
CONTROL_GROUP_ID = config.control_group_id
COMMAND_PREFIXES = config.command_prefixes
TZ = config.timezone
ACCOUNT_ID = None # 这个变量在运行时由 core.py 动态设置

# 定义文件路径常量
CONFIG_FILE_PATH = 'config/prod.yaml'
DATA_DIR = 'data'
LOG_FILE = 'logs/app.log'
ERROR_LOG_FILE = 'logs/error.log'
RAW_LOG_FILE = 'logs/raw_messages.log'
SESSION_FILE_PATH = f'{DATA_DIR}/user.session'
SCHEDULER_DB = f'sqlite:///{DATA_DIR}/jobs.sqlite'

def set_account_id(account_id: str):
    """在运行时由 core.py 调用，设置当前账户ID"""
    global ACCOUNT_ID
    ACCOUNT_ID = account_id

