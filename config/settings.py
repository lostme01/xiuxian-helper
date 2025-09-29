# -*- coding: utf-8 -*-
import yaml
import logging
import os

CONFIG_FILE_PATH = 'config/prod.yaml'
DATA_DIR = 'data'
LOG_FILE = 'logs/app.log'
RAW_LOG_FILE = 'logs/raw_messages.log'

try:
    with open(CONFIG_FILE_PATH, 'r', encoding='utf-8') as f: config = yaml.safe_load(f)
except FileNotFoundError:
    print(f"警告: 配置文件 {CONFIG_FILE_PATH} 未找到，将使用默认值。")
    config = {}
except Exception as e:
    print(f"错误: 加载配置文件 {CONFIG_FILE_PATH} 时出错: {e}")
    config = {}

API_ID = config.get('api_id', None)
API_HASH = config.get('api_hash', None)
ADMIN_USER_ID = config.get('admin_user_id', None)
IS_MAIN_ADMIN_ACCOUNT = config.get('is_main_admin_account', False)
GAME_GROUP_IDS = config.get('game_group_ids', [])

COMMAND_PREFIXES = config.get('command_prefixes', [',', '，'])
SECT_NAME = config.get('sect_name', None)
HUANGFENG_VALLEY_CONFIG = config.get('huangfeng_valley', {})
TAIYI_SECT_CONFIG = config.get('taiyi_sect', {})
GARDEN_SOW_SEED = HUANGFENG_VALLEY_CONFIG.get('garden_sow_seed', None)
AUTO_DELETE = config.get('auto_delete', {'enabled': False, 'delay_after_reply': 60, 'delay_fire_and_forget': 120})

default_task_switches = {
    'biguan': True, 'dianmao': True, 'learn_recipes': True, 
    'garden_check': True, 'inventory_refresh': True, 'chuang_ta': True,
    'mojun_arrival': False, 'auto_delete': False
}
user_task_switches = config.get('task_switches', {})
default_task_switches.update(user_task_switches)
TASK_SWITCHES = default_task_switches

EXAM_SOLVER_CONFIG = config.get('exam_solver', {})
TIANJI_EXAM_CONFIG = config.get('tianji_exam_solver', {'enabled': False})

# --- 核心新增：将模型名称也作为配置项读取 ---
GEMINI_MODEL_NAME = EXAM_SOLVER_CONFIG.get('gemini_model_name', 'gemini-1.5-pro-latest') # 提供一个备用模型

default_redis_config = {'enabled': False, 'host': 'localhost', 'port': 6379, 'password': None, 'db': 0, 'xuangu_db_name': 'xuangu_qa', 'tianji_db_name': 'tianji_qa'}
if 'redis' in config and config['redis']:
    default_redis_config.update(config['redis'])
    default_redis_config['enabled'] = True
else: print(f"警告: 在 {CONFIG_FILE_PATH} 中未找到 [redis] 配置块。所有依赖Redis的功能（如自动答题）将被禁用。")
REDIS_CONFIG = default_redis_config
SEND_DELAY_MIN = 12
SEND_DELAY_MAX = 16
SESSION_FILE_PATH = f'{DATA_DIR}/user.session'
SCHEDULER_DB = f'sqlite:///{DATA_DIR}/jobs.sqlite'
TZ = config.get('timezone', 'Asia/Shanghai')
LOG_ROTATION_CONFIG = config.get('log_rotation', {'max_bytes': 1048576, 'backup_count': 9})
default_logging_switches = {'system_activity': True, 'task_activity': True, 'cmd_sent': True, 'msg_recv': True, 'reply_recv': True, 'original_log_enabled': False, 'debug_log': False, 'log_edits': False, 'log_deletes': False}
user_logging_switches = config.get('logging_switches', {})
default_logging_switches.update(user_logging_switches)
LOGGING_SWITCHES = default_logging_switches

def check_startup_settings():
    """检查所有必需的配置项，并在缺失时提供带格式的详细错误提示"""
    missing_info = []
    
    required_settings = {
        'api_id': (API_ID, "api_id: 12345678"),
        'api_hash': (API_HASH, "api_hash: '0123456789abcdef0123456789abcdef'"),
        'admin_user_id': (ADMIN_USER_ID, "admin_user_id: 987654321"),
        'game_group_ids': (GAME_GROUP_IDS, "game_group_ids:\n  - -1001234567890"),
        'gemini_model_name': (EXAM_SOLVER_CONFIG.get('gemini_model_name'), "exam_solver:\n  gemini_model_name: 'gemini-2.5-pro'"),
        'gemini_api_keys': (EXAM_SOLVER_CONFIG.get('gemini_api_keys'), "exam_solver:\n  gemini_api_keys:\n    - 'AIzaSy...key'")
    }
    
    for key, (value, _) in required_settings.items():
        if not value:
            missing_info.append(key)
            
    if missing_info:
        error_message = f"严重错误: 您的 `config/prod.yaml` 配置文件中缺少或未正确配置以下必须的设置：\n"
        error_message += "--------------------------------------------------\n"
        for key in missing_info:
            _, example = required_settings[key]
            error_message += f"\n缺失项: {key}\n正确格式示例:\n{example}\n"
        error_message += "\n--------------------------------------------------\n"
        error_message += "程序无法启动，请根据以上提示补全您的配置。"
        print(error_message)
        exit(1)

check_startup_settings()
