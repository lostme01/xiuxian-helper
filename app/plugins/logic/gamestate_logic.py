# -*- coding: utf-8 -*-
from app.context import get_application

async def logic_reset_task_state(task_key: str) -> str:
    """重置指定任务的状态"""
    app = get_application()
    if not app.data_manager: return "❌ 错误: DataManager 未初始化。"

    state_map = {
        'biguan': "biguan", 
        'dianmao': "dianmao", 
        'chuangta': "chuang_ta", 
        'yindao': "taiyi_yindao"
    }
    
    if task_key not in state_map:
        return f"❓ 未知或不支持重置的任务: `{task_key}`\n**可用**: `{' '.join(state_map.keys())}`"
        
    state_key = state_map[task_key]
    await app.data_manager.delete_value(state_key)
    
    return f"✅ 已清除 **[{task_key}]** 的状态。相关任务将在下次检查时重新执行。"
