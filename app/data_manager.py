# -*- coding: utf-8 -*-
import json
import logging
from app.context import get_application
from app.logger import format_and_log
from config import settings

class DataManager:
    def __init__(self, redis_db):
        self.db = redis_db
        self.base_key = "tg_helper:task_states"

    def _get_key(self, account_id: str = None) -> str:
        """获取指定账户或当前账户的 Redis Key"""
        acc_id = account_id or settings.ACCOUNT_ID
        if not acc_id:
            raise RuntimeError("ACCOUNT_ID not set. DataManager cannot operate.")
        return f"{self.base_key}:{acc_id}"

    async def get_all_assistant_keys(self) -> list:
        """获取所有助手的 Redis Keys"""
        if not self.db: return []
        return [key async for key in self.db.scan_iter(f"{self.base_key}:*")]

    async def get_full_state(self, account_id: str = None) -> dict:
        """获取一个账户的完整状态字典"""
        if not self.db: return {}
        key = self._get_key(account_id)
        return await self.db.hgetall(key)

    async def get_value(self, key: str, account_id: str = None, is_json: bool = False, default=None):
        """通用获取函数"""
        if not self.db: return default
        redis_key = self._get_key(account_id)
        value = await self.db.hget(redis_key, key)
        if value is None: return default
        try:
            return json.loads(value) if is_json else value
        except (json.JSONDecodeError, TypeError):
            return default

    async def save_value(self, key: str, value, account_id: str = None):
        """通用保存函数"""
        if not self.db: return
        is_json = isinstance(value, (dict, list))
        payload = json.dumps(value, ensure_ascii=False) if is_json else str(value)
        redis_key = self._get_key(account_id)
        await self.db.hset(redis_key, key, payload)

    async def delete_value(self, key: str, account_id: str = None):
        """通用删除函数"""
        if not self.db: return
        redis_key = self._get_key(account_id)
        await self.db.hdel(redis_key, key)

    async def clear_all_data(self) -> int:
        """清空所有助手缓存数据"""
        if not self.db: return 0
        keys_to_delete = await self.get_all_assistant_keys()
        if keys_to_delete:
            await self.db.delete(*keys_to_delete)
        return len(keys_to_delete)

# 在 app/core.py 中进行实例化
data_manager = None

def initialize_data_manager(redis_db):
    """由 app.core 在初始化时调用"""
    global data_manager
    if redis_db:
        data_manager = DataManager(redis_db)
        format_and_log("SYSTEM", "组件初始化", {'组件': 'DataManager', '状态': '成功'})
    else:
        format_and_log("SYSTEM", "组件初始化", {'组件': 'DataManager', '状态': '已禁用 (Redis未连接)'})
