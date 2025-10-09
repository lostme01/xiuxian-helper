# -*- coding: utf-8 -*-
import yaml
import logging
import os
import json
import sys
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

CONFIG_FILE_PATH = 'config/prod.yaml'
DATA_DIR = 'data'
LOG_FILE = 'logs/app.log'
# [新增] 定义专门的错误日志文件
ERROR_LOG_FILE = 'logs/error.log'
RAW_LOG_FILE = 'logs/raw_messages.log'

try:
    with open(CONFIG_FILE_PATH, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
except FileNotFoundError:
    print(f"警告: 配置文件 {CONFIG_FILE_PATH} 未找到，将使用默认值。")
    config = {}
except Exception as e:
    print(f"错误: 加载配置文件 {CONFIG_FILE_PATH} 时出错: {e}")
    config = {}

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

# --- AI 配置 ---
EXAM_SOLVER_CONFIG = _merge_config('exam_solver', {
    'gemini_model_names': ['gemini-2.5-pro', 'gemini-2.5-flash', 'gemini-2.5-flash-lite'],
    'gemini_api_keys': [],
    'reply_delay': {'min': 5, 'max': 15}
})
gemini_keys_from_env = os.getenv('GEMINI_API_KEYS')
if gemini_keys_from_env:
    try:
        keys = json.loads(gemini_keys_from_env)
        if isinstance(keys, list):
            EXAM_SOLVER_CONFIG['gemini_api_keys'] = keys
        else:
            print("警告: 环境变量 GEMINI_API_KEYS 不是一个有效的 JSON 列表，将忽略。")
    except json.JSONDecodeError:
        print("警告: 无法解析环境变量 GEMINI_API_KEYS，它不是有效的 JSON 格式。")

GEMINI_MODEL_NAMES = EXAM_SOLVER_CONFIG.get('gemini_model_names')

# --- Redis 配置 ---
REDIS_CONFIG = _merge_config('redis', {
    'enabled': False, 'host': 'localhost', 'port': 6379,
    'password': None, 'db': 0, 'xuangu_db_name': 'xuangu_qa',
    'tianji_db_name': 'tianji_qa'
})
REDIS_CONFIG['password'] = os.getenv('REDIS_PASSWORD') or REDIS_CONFIG.get('password')

# --- 其他配置 ---
AUTO_DELETE = _merge_config('auto_delete', {'enabled': True, 'delay_admin_command': 30})
AUTO_DELETE_STRATEGIES = _merge_config('auto_delete_strategies', {
    'fire_and_forget': {'delay_self': 5},
    'request_response': {'delay_self_on_reply': 5, 'delay_self_on_timeout': 60},
    'long_task': {'delay_self': 0, 'delay_anchor': 30}
})
TASK_SWITCHES = _merge_config('task_switches', {
    'biguan': True, 'dianmao': True, 'learn_recipes': True,
    'garden_check': True, 'inventory_refresh': True, 'chuang_ta': True,
    'mojun_arrival': False, 'sect_treasury': True, 'formation_update': True
})
LOGGING_SWITCHES = _merge_config('logging_switches', {
    'system_activity': True, 'task_activity': True, 'cmd_sent': True,
    'msg_recv': True, 'reply_recv': True, 'original_log_enabled': False,
    'debug_log': False, 'log_edits': False, 'log_deletes': False
})
SEND_DELAY = config.get('send_delay', {'min': 12, 'max': 16})
TASK_JITTER = _merge_config('task_jitter', {
    'biguan': {'min': 30, 'max': 90},
    'taiyi_yindao': {'min': 300, 'max': 1200},
    'huangfeng_garden': {'min': 5, 'max': 15},
    'learn_recipes': {'min': 3, 'max': 7}
})
TASK_SCHEDULES = _merge_config('task_schedules', {'dianmao': ['08:15', '20:15']})
GAME_COMMANDS = _merge_config('game_commands', {'taiyi_yindao': '.引道 水'})
HUANGFENG_VALLEY_CONFIG = config.get('huangfeng_valley', {})
TAIYI_SECT_CONFIG = config.get('taiyi_sect', {})
XUANGU_EXAM_CONFIG = config.get('xuangu_exam_solver', {'enabled': False})
TIANJI_EXAM_CONFIG = config.get('tianji_exam_solver', {'enabled': False})
LOG_ROTATION_CONFIG = config.get('log_rotation', {'max_bytes': 1048576, 'backup_count': 9})
TRADE_COORDINATION_CONFIG = _merge_config('trade_coordination', {
    'focus_fire_auto_delist': True,
    'crafting_session_timeout_seconds': 300,
    'focus_fire_sync_buffer_seconds': 3
})
HEARTBEAT_CONFIG = _merge_config('heartbeat', {
    'active_enabled': True, 'active_interval_minutes': 10,
    'passive_enabled': True, 'passive_check_interval_minutes': 5,
    'passive_threshold_minutes': 30, 'sync_enabled': True, 'sync_run_time': '04:30'
})
BROADCAST_CONFIG = config.get('broadcast', {})
AUTO_RESOURCE_MANAGEMENT = config.get('auto_resource_management', {'enabled': False})
AUTO_KNOWLEDGE_SHARING = config.get('auto_knowledge_sharing', {'enabled': False})


# --- 路径常量 ---
SESSION_FILE_PATH = f'{DATA_DIR}/user.session'
SCHEDULER_DB = f'sqlite:///{DATA_DIR}/jobs.sqlite'

# --- 启动检查 ---
def check_startup_settings():
    errors = []
    validation_rules = {
        'api_id': (API_ID, int, True, None),
        'api_hash': (API_HASH, str, True, None),
        'admin_user_id': (ADMIN_USER_ID, int, True, None),
        'game_group_ids': (GAME_GROUP_IDS, list, True, lambda l: all(isinstance(i, int) for i in l)),
        'command_prefixes': (COMMAND_PREFIXES, list, True, lambda l: all(isinstance(i, str) for i in l)),
        'send_delay': (SEND_DELAY, dict, True, lambda d: 'min' in d and 'max' in d),
    }
    if XUANGU_EXAM_CONFIG.get('enabled') or TIANJI_EXAM_CONFIG.get('enabled'):
        if not EXAM_SOLVER_CONFIG.get('gemini_api_keys'):
            errors.append("- 'exam_solver.gemini_api_keys' 未在 .env 文件 (GEMINI_API_KEYS) 或 prod.yaml 中配置，但AI答题功能已开启。")
    for key, (value, expected_type, is_required, struct_check) in validation_rules.items():
        if is_required and not value:
            errors.append(f"- 必填项 '{key}' 未配置。")
            continue
        if value and not isinstance(value, expected_type):
            errors.append(f"- 配置项 '{key}' 的类型错误，期望是 {expected_type.__name__}，但实际是 {type(value).__name__}。")
            continue
        if struct_check and value and not struct_check(value):
            errors.append(f"- 配置项 '{key}' 的内部结构不正确。")
    if errors:
        error_message = f"严重错误: 您的 `config/prod.yaml` 或 `.env` 配置文件存在以下问题：\n"
        error_message += "--------------------------------------------------\n"
        error_message += "\n".join(errors)
        error_message += "\n--------------------------------------------------\n程序无法启动。"
        print(error_message)
        sys.exit(1)

check_startup_settings()
