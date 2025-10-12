# -*- coding: utf-8 -*-
import json
import time
from app.context import get_application
from app.constants import COORDINATION_SESSIONS_KEY

class SessionManager:
    """
    管理持久化的协同任务会话（状态机）。
    """
    def __init__(self, redis_db):
        self.db = redis_db

    async def create_session(self, session_id: str, session_data: dict):
        """创建一个新的会话并存入 Redis。"""
        if not self.db: return
        session_data['timestamp'] = time.time()
        await self.db.hset(COORDINATION_SESSIONS_KEY, session_id, json.dumps(session_data))

    async def get_session(self, session_id: str) -> dict | None:
        """根据ID获取一个会话。"""
        if not self.db: return None
        session_json = await self.db.hget(COORDINATION_SESSIONS_KEY, session_id)
        if session_json:
            return json.loads(session_json)
        return None

    async def update_session(self, session_id: str, updates: dict):
        """更新一个现有会话的数据。"""
        session_data = await self.get_session(session_id)
        if session_data:
            session_data.update(updates)
            # 每次更新都刷新时间戳
            session_data['timestamp'] = time.time()
            await self.db.hset(COORDINATION_SESSIONS_KEY, session_id, json.dumps(session_data))

    async def delete_session(self, session_id: str):
        """删除一个会话。"""
        if not self.db: return
        await self.db.hdel(COORDINATION_SESSIONS_KEY, session_id)
        
    async def get_all_sessions(self) -> dict:
        """获取所有会话。"""
        if not self.db: return {}
        return await self.db.hgetall(COORDINATION_SESSIONS_KEY)

# --- 全局单例 ---
_session_manager_instance = None

def get_session_manager():
    """获取会话管理器的全局实例。"""
    global _session_manager_instance
    if _session_manager_instance is None:
        app = get_application()
        _session_manager_instance = SessionManager(app.redis_db)
    return _session_manager_instance
