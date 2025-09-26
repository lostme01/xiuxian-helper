# -*- coding: utf-8 -*-
import yaml
import logging

# --- 路径定义 ---
CONFIG_FILE_PATH = 'config/prod.yaml'
DATA_DIR = 'data'
LOG_FILE = 'logs/app.log'
RAW_LOG_FILE = 'logs/raw_messages.log'

# --- 加载配置 ---
try:
    with open(CONFIG_FILE_PATH, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
except FileNotFoundError:
    config = {}
except Exception as e:
    print(f"错误: 加载配置文件 {CONFIG_FILE_PATH} 时出错: {e}")
    config = {}

# --- 配置项导出 ---
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

SEND_DELAY_MIN = 12
SEND_DELAY_MAX = 16
SESSION_FILE_PATH = f'{DATA_DIR}/user.session'
SCHEDULER_DB = f'sqlite:///{DATA_DIR}/jobs.sqlite'
TZ = config.get('timezone', 'Asia/Shanghai')

# 确保所有日志开关都存在
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

