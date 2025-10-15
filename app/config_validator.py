# -*- coding: utf-8 -*-
from typing import List, Dict, Optional, Union

from pydantic import BaseModel, Field, conint, constr


# --- 内嵌子模型 ---

class DelayModel(BaseModel):
    min: int
    max: int

class ExamSolverModel(BaseModel):
    gemini_model_names: List[str]
    gemini_api_keys: List[str]
    reply_delay: DelayModel

class ExamToggleModel(BaseModel):
    enabled: bool

class TaskSwitchesModel(BaseModel):
    biguan: bool
    dianmao: bool
    learn_recipes: bool
    garden_check: bool
    inventory_refresh: bool
    chuang_ta: bool
    mojun_arrival: bool
    sect_treasury: bool
    formation_update: bool
    # [新增] 元婴功能开关
    nascent_soul: bool = False
    # [新增] 卜筮功能开关
    divination: bool = False


class TaskJitterModel(BaseModel):
    biguan: DelayModel
    taiyi_yindao: DelayModel
    huangfeng_garden: DelayModel
    learn_recipes: DelayModel

class RedisModel(BaseModel):
    enabled: bool
    host: str
    port: int
    password: Optional[str] = None
    db: int
    xuangu_db_name: str
    tianji_db_name: str

class AutoDeleteStrategyModel(BaseModel):
    delay_self: Optional[int] = None
    delay_self_on_reply: Optional[int] = None
    delay_self_on_timeout: Optional[int] = None
    delay_anchor: Optional[int] = None
    
class TradeCoordinationModel(BaseModel):
    focus_fire_auto_delist: bool
    crafting_session_timeout_seconds: int
    focus_fire_sync_buffer_seconds: int

class AutoResourceRule(BaseModel):
    check_resource: str
    condition: str
    action: constr(pattern=r'^(donate|exchange)$')
    item: str
    amount: conint(gt=0)
    
class AutoManagementModel(BaseModel):
    enabled: bool
    interval_minutes: conint(gt=0)
    rules: Optional[List[AutoResourceRule]] = []

class AutoKnowledgeSharingModel(BaseModel):
    enabled: bool
    interval_minutes: conint(gt=0)
    blacklist: List[str] = []

class LogRotationModel(BaseModel):
    max_bytes: int
    backup_count: int

class LoggingSwitchesModel(BaseModel):
    system_activity: bool
    task_activity: bool
    cmd_sent: bool
    msg_recv: bool
    reply_recv: bool
    original_log_enabled: bool
    debug_log: bool
    log_edits: bool
    log_deletes: bool
    
class HeartbeatModel(BaseModel):
    active_enabled: bool
    active_interval_minutes: int
    passive_enabled: bool
    passive_check_interval_minutes: int
    passive_threshold_minutes: int
    sync_enabled: bool
    sync_run_time: constr(pattern=r'^\d{2}:\d{2}$')


# --- 顶层配置模型 ---

class ConfigModel(BaseModel):
    # [新增] 全局总开关
    master_switch: bool = True
    
    api_id: int
    api_hash: str
    admin_user_id: int
    game_bot_ids: List[int]
    game_group_ids: List[int]
    control_group_id: Optional[int] = None
    test_group_id: Optional[int] = None
    sect_name: Optional[str] = None
    command_prefixes: List[str]
    timezone: str
    command_timeout: int = 60
    
    exam_solver: ExamSolverModel
    xuangu_exam_solver: ExamToggleModel
    tianji_exam_solver: ExamToggleModel
    
    task_switches: TaskSwitchesModel
    send_delay: DelayModel
    task_jitter: TaskJitterModel
    task_schedules: Dict[str, List[str]]
    game_commands: Dict[str, str]
    
    huangfeng_valley: Optional[Dict[str, str]] = {}
    taiyi_sect: Optional[Dict[str, int]] = {}
    
    redis: RedisModel
    
    auto_delete: Dict[str, Union[bool, int]]
    auto_delete_strategies: Dict[str, AutoDeleteStrategyModel]
    
    trade_coordination: TradeCoordinationModel
    
    auto_resource_management: AutoManagementModel
    auto_knowledge_sharing: AutoKnowledgeSharingModel
    
    broadcast: Optional[Dict[str, List[str]]] = {}
    
    log_rotation: LogRotationModel
    logging_switches: LoggingSwitchesModel
    heartbeat: HeartbeatModel
