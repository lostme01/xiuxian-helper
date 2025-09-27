# -*- coding: utf-8 -*-
import yaml
import logging

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

API_ID = config.get('api_id', 0)
API_HASH = config.get('api_hash', '')
ADMIN_USER_ID = config.get('admin_user_id', 0)
IS_MAIN_ADMIN_ACCOUNT = config.get('is_main_admin_account', False)
GAME_GROUP_ID = config.get('game_group_id', 0)
COMMAND_PREFIXES = config.get('command_prefixes', [',', '，'])
SECT_NAME = config.get('sect_name', None)

HUANGFENG_VALLEY_CONFIG = config.get('huangfeng_valley', {})
GARDEN_SOW_SEED = HUANGFENG_VALLEY_CONFIG.get('garden_sow_seed', None)

AUTO_DELETE = config.get('auto_delete', {'enabled': False})

TASK_SWITCHES = config.get('task_switches', {'biguan': True, 'dianmao': True, 'learn_recipes': True, 'garden_check': True, 'inventory_refresh': True, 'chuang_ta': True})

EXAM_SOLVER_CONFIG = config.get('exam_solver', {'enabled': False, 'gemini_api_key': None})
TIANJI_EXAM_CONFIG = config.get('tianji_exam_solver', {'enabled': False})

# *** 优化：Redis 配置加载逻辑 ***
if 'redis' in config:
    REDIS_CONFIG = config.get('redis')
    REDIS_CONFIG['enabled'] = True # 标记为已启用
else:
    print("警告: 在 config/prod.yaml 中未找到 [redis] 配置块。所有依赖Redis的功能（如自动答题）将被禁用。")
    REDIS_CONFIG = {'enabled': False} # 标记为未启用

SEND_DELAY_MIN = 12
SEND_DELAY_MAX = 16
SESSION_FILE_PATH = f'{DATA_DIR}/user.session'
SCHEDULER_DB = f'sqlite:///{DATA_DIR}/jobs.sqlite'
TZ = config.get('timezone', 'Asia/Shanghai')

LOG_ROTATION_CONFIG = config.get('log_rotation', {'max_bytes': 10485760, 'backup_count': 5})

default_logging_switches = {
    'system_activity': True, 'task_activity': True, 'cmd_sent': True, 'msg_recv': True, 'reply_recv': True, 'original_log_enabled': False, 'debug_log': False, 'log_edits': False, 'log_deletes': False,
}
user_logging_switches = config.get('logging_switches', {})
default_logging_switches.update(user_logging_switches)
LOGGING_SWITCHES = default_logging_switches

if not all([API_ID, API_HASH, ADMIN_USER_ID, GAME_GROUP_ID]):
    print("严重错误: 配置文件中的核心设置不完整，程序无法启动。")
    exit(1)
