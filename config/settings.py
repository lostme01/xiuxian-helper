# -*- coding: utf-8 -*-
import yaml
import logging
import os
import json
import sys
from dotenv import load_dotenv
# [新增] 导入 Pydantic 验证模型和异常
from app.config_validator import ConfigModel
from pydantic import ValidationError

# Load environment variables from .env file
load_dotenv()

CONFIG_FILE_PATH = 'config/prod.yaml'
DATA_DIR = 'data'
LOG_FILE = 'logs/app.log'
ERROR_LOG_FILE = 'logs/error.log'
RAW_LOG_FILE = 'logs/raw_messages.log'

try:
    with open(CONFIG_FILE_PATH, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
except FileNotFoundError:
    print(f"严重错误: 配置文件 {CONFIG_FILE_PATH} 未找到。程序无法启动。")
    sys.exit(1)
except Exception as e:
    print(f"严重错误: 加载配置文件 {CONFIG_FILE_PATH} 时出错: {e}。程序无法启动。")
    sys.exit(1)

ACCOUNT_ID = None
os.makedirs(DATA_DIR, exist_ok=True)

def _merge_config(key: str, defaults: dict) -> dict:
    user_config = config.get(key, {})
    merged = defaults.copy()
    if isinstance(user_config, dict):
        merged.update(user_config)
    return merged

# --- 从配置文件或环境变量加载 ---
API_ID = config.get('api_id', None)
API_HASH = os.getenv('API_HASH') or config.get('api_hash', None)
ADMIN_USER_ID = config.get('admin_user_id', None)
GAME_BOT_IDS = config.get('game_bot_ids', [])
GAME_GROUP_IDS = config.get('game_group_ids', [])
GAME_TOPIC_ID = config.get('game_topic_id', None)
CONTROL_GROUP_ID = config.get('control_group_id', None)
TEST_GROUP_ID = config.get('test_group_id', None)
COMMAND_PREFIXES = config.get('command_prefixes', [',', '，'])
SECT_NAME = config.get('sect_name', None)
TZ = config.get('timezone', 'Asia/Shanghai')
COMMAND_TIMEOUT = config.get('command_timeout', 60)

# [修改] 将环境变量注入到config字典中，以便Pydantic统一验证
config['api_hash'] = API_HASH
if 'exam_solver' in config and isinstance(config['exam_solver'], dict):
    gemini_keys_from_env = os.getenv('GEMINI_API_KEYS')
    if gemini_keys_from_env:
        try:
            keys = json.loads(gemini_keys_from_env)
            if isinstance(keys, list):
                config['exam_solver']['gemini_api_keys'] = keys
        except json.JSONDecodeError:
            print("警告: 无法解析环境变量 GEMINI_API_KEYS，它不是有效的 JSON 格式。")

if 'redis' in config and isinstance(config['redis'], dict):
    config['redis']['password'] = os.getenv('REDIS_PASSWORD') or config['redis'].get('password')


# --- AI 配置 ---
EXAM_SOLVER_CONFIG = _merge_config('exam_solver', {})
GEMINI_MODEL_NAMES = EXAM_SOLVER_CONFIG.get('gemini_model_names', [])


# --- Redis 配置 ---
REDIS_CONFIG = _merge_config('redis', {})

# --- 其他配置 ---
AUTO_DELETE = _merge_config('auto_delete', {})
AUTO_DELETE_STRATEGIES = _merge_config('auto_delete_strategies', {})
TASK_SWITCHES = _merge_config('task_switches', {})
LOGGING_SWITCHES = _merge_config('logging_switches', {})
SEND_DELAY = config.get('send_delay', {})
TASK_JITTER = _merge_config('task_jitter', {})
TASK_SCHEDULES = _merge_config('task_schedules', {})
GAME_COMMANDS = _merge_config('game_commands', {})
HUANGFENG_VALLEY_CONFIG = config.get('huangfeng_valley', {})
TAIYI_SECT_CONFIG = config.get('taiyi_sect', {})
XUANGU_EXAM_CONFIG = config.get('xuangu_exam_solver', {})
TIANJI_EXAM_CONFIG = config.get('tianji_exam_solver', {})
LOG_ROTATION_CONFIG = config.get('log_rotation', {})
TRADE_COORDINATION_CONFIG = _merge_config('trade_coordination', {})
HEARTBEAT_CONFIG = _merge_config('heartbeat', {})
BROADCAST_CONFIG = config.get('broadcast', {})
AUTO_RESOURCE_MANAGEMENT = config.get('auto_resource_management', {})
AUTO_KNOWLEDGE_SHARING = config.get('auto_knowledge_sharing', {})


# --- 路径常量 ---
SESSION_FILE_PATH = f'{DATA_DIR}/user.session'
SCHEDULER_DB = f'sqlite:///{DATA_DIR}/jobs.sqlite'

# --- [重构] 使用 Pydantic 进行启动检查 ---
def validate_config_with_pydantic():
    try:
        # 使用 Pydantic 模型来解析和验证整个 config 字典
        ConfigModel(**config)
        
        # 特殊逻辑检查
        if (XUANGU_EXAM_CONFIG.get('enabled') or TIANJI_EXAM_CONFIG.get('enabled')):
            if not EXAM_SOLVER_CONFIG.get('gemini_api_keys'):
                raise ValueError("- 'exam_solver.gemini_api_keys' 未在 .env 文件 (GEMINI_API_KEYS) 或 prod.yaml 中配置，但AI答题功能已开启。")

    except ValidationError as e:
        error_message = f"严重错误: 您的 `config/prod.yaml` 或 `.env` 配置文件存在以下问题：\n"
        error_message += "--------------------------------------------------\n"
        for error in e.errors():
            # 格式化Pydantic的错误信息，使其更易读
            field_path = " -> ".join(map(str, error['loc']))
            error_message += f"- **字段 '{field_path}'**: {error['msg']}\n"
        error_message += "--------------------------------------------------\n程序无法启动。"
        print(error_message)
        sys.exit(1)
    except ValueError as e:
        # 捕获我们自己抛出的特殊逻辑错误
        error_message = f"严重错误: 您的 `config/prod.yaml` 或 `.env` 配置文件存在以下问题：\n"
        error_message += "--------------------------------------------------\n"
        error_message += str(e)
        error_message += "\n--------------------------------------------------\n程序无法启动。"
        print(error_message)
        sys.exit(1)

# 在文件加载后立即执行验证
validate_config_with_pydantic()
