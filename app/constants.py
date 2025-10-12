# -*- coding: utf-8 -*-
"""
统一管理项目中的所有“魔法字符串”，便于维护和修改。
"""

# --- Redis Keys ---
# Base key for all assistant data
BASE_KEY = "tg_helper:task_states"

# Hash field keys within an assistant's state
STATE_KEY_PROFILE = "character_profile"
STATE_KEY_INVENTORY = "inventory"
STATE_KEY_SECT_TREASURY = "sect_treasury"
STATE_KEY_LEARNED_RECIPES = "learned_recipes"
STATE_KEY_FORMATION_INFO = "formation_info"
STATE_KEY_BIGUAN = "biguan"
STATE_KEY_CHUANG_TA = "chuang_ta"
STATE_KEY_TAIYI_YINDAO = "taiyi_yindao"
STATE_KEY_LAST_TIMESTAMPS = "last_message_timestamps"
STATE_KEY_FORMATION_LAST_RUN = "formation_last_run"

# Standalone Redis keys
CRAFTING_RECIPES_KEY = "crafting_recipes"
CRAFTING_SESSIONS_KEY = "crafting_sessions"
KNOWLEDGE_SESSIONS_KEY = "knowledge_sessions"
# [新增] 用于存储持久化协同任务状态的键
COORDINATION_SESSIONS_KEY = "coordination_sessions"

# QA Database keys from config
XUANGU_DB_NAME_KEY = "xuangu_db_name"
TIANJI_DB_NAME_KEY = "tianji_db_name"

# --- Redis Channels ---
TASK_CHANNEL = "tg_helper:tasks"
GAME_EVENTS_CHANNEL = "tg_helper:game_events"

# --- Scheduler Task IDs ---
TASK_ID_BIGUAN = 'biguan_xiulian_task'
TASK_ID_CHUANG_TA_BASE = 'chuang_ta_task_'
TASK_ID_INVENTORY_REFRESH = 'inventory_refresh_task'
TASK_ID_LEARN_RECIPES = 'learn_recipes_task'
TASK_ID_SECT_TREASURY = 'sect_treasury_daily_task'
TASK_ID_FORMATION_BASE = 'formation_update_task_'
TASK_ID_DIANMAO_BASE = 'zongmen_dianmao_task_'
TASK_ID_YINDAO = 'taiyi_yindao_task'
TASK_ID_GARDEN = 'huangfeng_garden_task'

# Heartbeat tasks
TASK_ID_ACTIVE_HEARTBEAT = 'active_heartbeat_task'
TASK_ID_PASSIVE_HEARTBEAT = 'passive_heartbeat_task'
TASK_ID_DAILY_SYNC = 'daily_dialog_sync_task'

# Auto-management tasks
TASK_ID_AUTO_RESOURCE = 'auto_resource_management_task'
TASK_ID_AUTO_KNOWLEDGE = 'auto_knowledge_sharing_task'
TASK_ID_KNOWLEDGE_TIMEOUT = 'knowledge_timeout_checker_task'
TASK_ID_CRAFTING_TIMEOUT = 'crafting_timeout_checker_task'
# [新增] 用于清理过时协同任务的调度ID
TASK_ID_SESSION_CLEANUP = 'session_cleanup_task'
