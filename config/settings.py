# -*- coding: utf-8 -*-
import yaml
import logging
import os
import json
from dotenv import load_dotenv

load_dotenv()

CONFIG_FILE_PATH = 'config/prod.yaml'
DATA_DIR = 'data'
LOG_FILE = 'logs/app.log'
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

API_ID = config.get('api_id', None)
API_HASH = config.get('api_hash', None)
ADMIN_USER_ID = config.get('admin_user_id', None)
GAME_GROUP_IDS = config.get('game_group_ids', [])
CONTROL_GROUP_ID = config.get('control_group_id', None)
TEST_GROUP_ID = config.get('test_group_id', None)
COMMAND_PREFIXES = config.get('command_prefixes', [',', '，'])
SECT_NAME = config.get('sect_name', None)
TZ = config.get('timezone', 'Asia/Shanghai')

# --- 改造：从配置中读取全局指令超时时间 ---
COMMAND_TIMEOUT = config.get('command_timeout', 60)

AUTO_DELETE = _merge_config('auto_delete', {
    'enabled': False, 
    'delay_admin_command': 30
})

AUTO_DELETE_STRATEGIES = _merge_config('auto_delete_strategies', {
    'fire_and_forget': { 'delay_self': 5 },
    'request_response': { 'delay_self_on_reply': 30, 'delay_self_on_timeout': 60 },
    'long_task': { 'delay_self': 0 }
})

TASK_SWITCHES = _merge_config('task_switches', {
    'biguan': True, 'dianmao': True, 'learn_recipes': True, 
    'garden_check': True, 'inventory_refresh': True, 'chuang_ta': True,
    'mojun_arrival': False, 'sect_treasury': True
})
LOGGING_SWITCHES = _merge_config('logging_switches', {
    'system_activity': True, 'task_activity': True, 'cmd_sent': True, 
    'msg_recv': True, 'reply_recv': True, 'original_log_enabled': False, 
    'debug_log': False, 'log_edits': False, 'log_deletes': False
})
REDIS_CONFIG = _merge_config('redis', {
    'enabled': False, 'host': 'localhost', 'port': 6379, 
    'password': None, 'db': 0, 'xuangu_db_name': 'xuangu_qa', 
    'tianji_db_name': 'tianji_qa'
})

redis_password_from_env = os.getenv('REDIS_PASSWORD')
if redis_password_from_env:
    REDIS_CONFIG['password'] = redis_password_from_env

if 'redis' not in config or not config.get('redis'):
    print(f"警告: 在 {CONFIG_FILE_PATH} 中未找到 [redis] 配置块。所有依赖Redis的功能将被禁用。")
    REDIS_CONFIG['enabled'] = False
else:
    REDIS_CONFIG['enabled'] = config.get('redis', {}).get('enabled', False)

SEND_DELAY = config.get('send_delay', {'min': 12, 'max': 16})
HEARTBEAT_TIMEOUT = config.get('heartbeat_timeout', 1200)
TASK_JITTER = _merge_config('task_jitter', {
    'biguan': {'min': 30, 'max': 90},
    'taiyi_yindao': {'min': 300, 'max': 1200},
    'huangfeng_garden': {'min': 5, 'max': 15},
    'learn_recipes': {'min': 3, 'max': 7}
})
TASK_SCHEDULES = _merge_config('task_schedules', { 'dianmao': [ '08:15', '20:15' ] })
GAME_COMMANDS = _merge_config('game_commands', { 'taiyi_yindao': '.引道 水' })

HUANGFENG_VALLEY_CONFIG = config.get('huangfeng_valley', {})
TAIYI_SECT_CONFIG = config.get('taiyi_sect', {})
EXAM_SOLVER_CONFIG = config.get('exam_solver', {})
XUANGU_EXAM_CONFIG = config.get('xuangu_exam_solver', {'enabled': False})
TIANJI_EXAM_CONFIG = config.get('tianji_exam_solver', {'enabled': False})
LOG_ROTATION_CONFIG = config.get('log_rotation', {'max_bytes': 1048576, 'backup_count': 9})
# --- 新增: 读取交易协同配置 ---
TRADE_COORDINATION_CONFIG = config.get('trade_coordination', {'focus_fire_auto_delist': True})

GEMINI_MODEL_NAME = EXAM_SOLVER_CONFIG.get('gemini_model_name', 'gemini-2.5-pro')

gemini_keys_from_env = os.getenv('GEMINI_API_KEYS')
if gemini_keys_from_env:
    try:
        EXAM_SOLVER_CONFIG['gemini_api_keys'] = json.loads(gemini_keys_from_env)
    except json.JSONDecodeError:
        print("错误: 环境变量 GEMINI_API_KEYS 格式不正确，应为 JSON 格式的字符串列表。")
        EXAM_SOLVER_CONFIG['gemini_api_keys'] = []

SESSION_FILE_PATH = f'{DATA_DIR}/user.session'
SCHEDULER_DB = f'sqlite:///{DATA_DIR}/jobs.sqlite'

def check_startup_settings():
    missing_info = []
    required_settings = {
        'api_id': (API_ID, "api_id: 12345678"),
        'api_hash': (API_HASH, "api_hash: '0123456789abcdef0123456789abcdef'"),
        'admin_user_id': (ADMIN_USER_ID, "admin_user_id: 987654321"),
        'game_group_ids': (GAME_GROUP_IDS, "game_group_ids:\n  - -1001234567890"),
    }
    if XUANGU_EXAM_CONFIG.get('enabled') or TIANJI_EXAM_CONFIG.get('enabled'):
        required_settings['gemini_api_keys'] = (EXAM_SOLVER_CONFIG.get('gemini_api_keys'), "在 prod.yaml 或 .env 文件中设置 gemini_api_keys")
    for key, (value, _) in required_settings.items():
        if not value: missing_info.append(key)
    if missing_info:
        error_message = f"严重错误: 您的 `config/prod.yaml` 或 `.env` 配置文件中缺少或未正确配置以下必须的设置：\n"
        error_message += "--------------------------------------------------\n"
        for key in missing_info:
            _, example = required_settings[key]
            error_message += f"\n缺失项: {key}\n正确格式示例:\n{example}\n"
        error_message += "\n--------------------------------------------------\n程序无法启动。"
        print(error_message)
        exit(1)

check_startup_settings()
