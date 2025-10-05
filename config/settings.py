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
GAME_BOT_IDS = config.get('game_bot_ids', []) 
GAME_GROUP_IDS = config.get('game_group_ids', [])
# [核心修改] 新增游戏话题ID配置
GAME_TOPIC_ID = config.get('game_topic_id', None) 
CONTROL_GROUP_ID = config.get('control_group_id', None)
TEST_GROUP_ID = config.get('test_group_id', None)
COMMAND_PREFIXES = config.get('command_prefixes', [',', '，'])
SECT_NAME = config.get('sect_name', None)
TZ = config.get('timezone', 'Asia/Shanghai')

COMMAND_TIMEOUT = config.get('command_timeout', 60)

EXAM_SOLVER_CONFIG = _merge_config('exam_solver', {
    'gemini_model_name': 'models/gemini-1.5-pro-latest',
    'gemini_api_keys': [],
    'reply_delay': {'min': 5, 'max': 15}
})

AI_PERSONAS = _merge_config('ai_personas', {
    '老油条': '你是一个玩世不恭的修仙老油条，说话有点贱兮兮的，喜欢吐槽，偶尔也羡慕一下别人的好运气。',
    '高冷大佬': '你是一位境界高深、不苟言笑的大佬，言语非常简练，充满威严，偶尔会用一两个字指点一下群里的菜鸟。',
    '萌新师妹': '你是一个刚入门派的小师妹，什么都不懂，对一切都很好奇，喜欢问问题，看到别人出好东西会惊叹“哇，好厉害！”。',
    '好好先生': '你是一个性格温和的修士，与人为善，乐于助人，总是积极地回答别人的问题，说话很客气。',
    '战斗狂人': '你是一个战斗狂人，言语中充满战意，三句不离切磋和斗法，看不起胆小的人，总想着“干就完了”。',
    '苟道大师': '你是一个信奉“活着才是硬道理”的苟道大师，说话总是小心翼翼，劝人不要冲动，喜欢分享各种保命心得。',
    '炼丹宗师': '你是一个炼丹宗师，对话的焦点总在炼丹上，对材料、火候、成丹率有种偏执的热情，偶尔会炫耀自己的作品。',
    '天命之子': '你是一个运气爆棚的天命之子，说话总带点凡尔赛，字里行间透露出自己又轻松突破或者获得了什么天材地宝。',
    '愤青': '你是一个愤青玩家，觉得游戏里的什么都不合理，总是吐槽游戏机制、任务难度和机器人AI，感觉自己被针对了。',
    '谜语人': '你是一个谜语人，说话神神秘秘，喜欢用比喻和典故，从不把话说透，让人感觉高深莫测。'
})

AI_CHATTER_CONFIG = _merge_config('ai_chatter', {
    'enabled': False,
    'personality_prompt': AI_PERSONAS.get('老油条'),
    'chat_model_name': 'models/gemini-1.5-flash-latest',
    'random_chat_probability': 0.05,
    'inter_assistant_reply_probability': 0.3,
    'reply_vs_send_ratio': 0.8,
    'blacklist': [],
    'mood_system_enabled': True,
    'topic_system_enabled': True,
    'positive_keywords': ["成功", "获得", "完成", "升级", "提升", "领悟"],
    'negative_keywords': ["失败", "不足", "无法", "上限", "被抢"]
})

AUTO_DELETE = _merge_config('auto_delete', {
    'enabled': True, 
    'delay_admin_command': 30
})

AUTO_DELETE_STRATEGIES = _merge_config('auto_delete_strategies', {
    'fire_and_forget': { 'delay_self': 5 },
    'request_response': { 
        'delay_self_on_reply': 5, 
        'delay_self_on_timeout': 60,
    },
    'long_task': { 
        'delay_self': 0,
        'delay_anchor': 30
    }
})

TASK_SWITCHES = _merge_config('task_switches', {
    'biguan': True, 'dianmao': True, 'learn_recipes': True, 
    'garden_check': True, 'inventory_refresh': True, 'chuang_ta': True,
    'mojun_arrival': False, 'sect_treasury': True
})

AUTO_RESOURCE_MANAGEMENT = _merge_config('auto_resource_management', {'enabled': False})
AUTO_KNOWLEDGE_SHARING = _merge_config('auto_knowledge_sharing', {'enabled': False})


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

XUANGU_EXAM_CONFIG = config.get('xuangu_exam_solver', {'enabled': False})
TIANJI_EXAM_CONFIG = config.get('tianji_exam_solver', {'enabled': False})
LOG_ROTATION_CONFIG = config.get('log_rotation', {'max_bytes': 1048576, 'backup_count': 9})
TRADE_COORDINATION_CONFIG = config.get('trade_coordination', {'focus_fire_auto_delist': True})

GEMINI_MODEL_NAME = EXAM_SOLVER_CONFIG.get('gemini_model_name')

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

    for key, (value, _) in required_settings.items():
        if not value:
            missing_info.append(key)

    if XUANGU_EXAM_CONFIG.get('enabled') or TIANJI_EXAM_CONFIG.get('enabled') or AI_CHATTER_CONFIG.get('enabled'):
        if not EXAM_SOLVER_CONFIG.get('gemini_api_keys'):
             missing_info.append('gemini_api_keys')
             required_settings['gemini_api_keys'] = (None, "在 prod.yaml 中设置 gemini_api_keys 列表")
    
    if missing_info:
        error_message = f"严重错误: 您的 `config/prod.yaml` 或 `.env` 配置文件中缺少或未正确配置以下必须的设置：\n"
        error_message += "--------------------------------------------------\n"
        for key in sorted(list(set(missing_info))):
            _, example = required_settings[key]
            error_message += f"\n缺失项: {key}\n正确格式示例:\n{example}\n"
        error_message += "\n--------------------------------------------------\n程序无法启动。"
        print(error_message)
        exit(1)

check_startup_settings()
