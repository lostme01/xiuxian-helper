# -*- coding: utf-8 -*-
"""
配置元数据中心

此文件统一定义了所有用户可以通过指令查看和修改的配置项。
每个配置项都包含：
- path: 在 prod.yaml 文件中的路径 (使用点号分隔)。
- alias: 用户在指令中使用的中文别名。
- description: 配置项的简短描述。
"""

# 定义可动态修改的配置项
MODIFIABLE_CONFIGS = {
    # 核心行为
    "指令全局超时": ("command_timeout", "指令执行的全局超时秒数。"),
    "最小发送延迟": ("send_delay.min", "发送游戏指令后的最小随机等待时间（秒）。"),
    "最大发送延迟": ("send_delay.max", "发送游戏指令后的最大随机等待时间（秒）。"),
    
    # 消息删除策略
    "管理员指令删除延迟": ("auto_delete.delay_admin_command", "删除管理员指令原文前的等待时间（秒）。"),
    "成功回复后删除延迟": ("auto_delete_strategies.request_response.delay_self_on_reply", "指令成功后，删除指令原文前的等待时间（秒）。"),
    "超时回复后删除延迟": ("auto_delete_strategies.request_response.delay_self_on_timeout", "指令超时后，删除指令原文前的等待时间（秒）。"),
    
    # AI 答题
    "AI答题延迟-最小": ("exam_solver.reply_delay.min", "AI 答题前的最小随机等待时间（秒）。"),
    "AI答题延迟-最大": ("exam_solver.reply_delay.max", "AI 答题前的最大随机等待时间（秒）。"),
    
    # 协同与自动化
    "智能炼制超时秒数": ("trade_coordination.crafting_session_timeout_seconds", "智能炼制任务等待材料的超时时间（秒）。"),
    "集火同步缓冲": ("trade_coordination.focus_fire_sync_buffer_seconds", "集火任务中，计算出的同步时间点之后的额外缓冲秒数。"),
    
    # 心跳与维护
    "主动心跳间隔分钟": ("heartbeat.active_interval_minutes", "保持 Telegram 连接活跃的心跳间隔（分钟）。"),
    "被动心跳阈值分钟": ("heartbeat.passive_threshold_minutes", "超过此时间未收到任何消息则发出警报（分钟）。"),
    
    # 宗门专属
    "黄枫谷-药园播种": ("huangfeng_valley.garden_sow_seed", "黄枫谷小药园自动播种的种子名称。"),
    "太一门-引道冷却": ("taiyi_sect.yindao_success_cooldown_hours", "太一门引道成功后的冷却时间（小时）。"),
}

# 定义日志开关
LOGGING_SWITCHES_META = {
    "system_activity": "系统活动",
    "task_activity": "任务活动",
    "cmd_sent": "指令发送",
    "msg_recv": "消息接收",
    "reply_recv": "回复接收",
    "debug_log": "调试日志",
    "log_edits": "消息编辑",
    "log_deletes": "消息删除",
    "original_log_enabled": "原始日志"
}

# 定义功能开关 (任务开关)
TASK_SWITCHES_META = {
    '玄骨': ('玄骨考校', 'xuangu_exam_solver.enabled'),
    '天机': ('天机考验', 'tianji_exam_solver.enabled'),
    '闭关': ('自动闭关', 'task_switches.biguan'),
    '点卯': ('自动点卯', 'task_switches.dianmao'),
    '学习': ('自动学习', 'task_switches.learn_recipes'),
    '药园': ('自动药园', 'task_switches.garden_check'),
    '背包': ('自动刷新背包', 'task_switches.inventory_refresh'),
    '闯塔': ('自动闯塔', 'task_switches.chuang_ta'),
    '宝库': ('自动宗门宝库', 'task_switches.sect_treasury'),
    '阵法': ('自动更新阵法', 'task_switches.formation_update'),
    '魔君': ('自动应对魔君', 'task_switches.mojun_arrival'),
    '自动删除': ('消息自动删除', 'auto_delete.enabled'),
    '智能资源': ('智能资源管理', 'auto_resource_management.enabled'),
    '知识共享': ('自动化知识共享', 'auto_knowledge_sharing.enabled'),
    # [新增] 元婴出窍任务开关
    '元婴': ('自动元婴出窍', 'task_switches.nascent_soul'),
}
