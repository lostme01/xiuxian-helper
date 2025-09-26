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
    config = {}
except Exception as e:
    config = {}

API_ID = config.get('api_id', 0)
API_HASH = config.get('api_hash', '')
ADMIN_USER_ID = config.get('admin_user_id', 0)
GAME_GROUP_ID = config.get('game_group_id', 0)
COMMAND_PREFIXES = config.get('command_prefixes', [',', '，'])
SECT_NAME = config.get('sect_name', None)

HUANGFENG_VALLEY_CONFIG = config.get('huangfeng_valley', {})
GARDEN_SOW_SEED = HUANGFENG_VALLEY_CONFIG.get('garden_sow_seed', None)

AUTO_DELETE = config.get('auto_delete', {
    'enabled': False, 'delay_after_reply': 60, 'delay_fire_and_forget': 120,
})

# *** 新增：加载后台任务总开关 ***
TASK_SWITCHES = config.get('task_switches', {
    'biguan': True,
    'dianmao': True,
    'learn_recipes': True,
    'garden_check': True,
    'inventory_refresh': True,
})

EXAM_SOLVER_CONFIG = config.get('exam_solver', {
    'enabled': False,
    'gemini_api_key': None,
})

TIANJI_EXAM_CONFIG = config.get('tianji_exam_solver', {
    'enabled': False,
})

SEND_DELAY_MIN = 12
SEND_DELAY_MAX = 16
SESSION_FILE_PATH = f'{DATA_DIR}/user.session'
SCHEDULER_DB = f'sqlite:///{DATA_DIR}/jobs.sqlite'
TZ = config.get('timezone', 'Asia/Shanghai')

LOG_ROTATION_CONFIG = config.get('log_rotation', {
    'max_bytes': 10485760,
    'backup_count': 5,
})

default_logging_switches = {
    'system_activity': True, 'task_activity': True, 'cmd_sent': True,
    'msg_recv': True, 'reply_recv': True, 'original_log_enabled': False,
    'debug_log': False, 'log_edits': False, 'log_deletes': False,
}
user_logging_switches = config.get('logging_switches', {})
default_logging_switches.update(user_logging_switches)
LOGGING_SWITCHES = default_logging_switches

if not all([API_ID, API_HASH, ADMIN_USER_ID, GAME_GROUP_ID]):
    print("严重错误: 配置文件中的核心设置不完整，程序无法启动。")
    exit(1)
