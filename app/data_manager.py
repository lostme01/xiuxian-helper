# -*- coding: utf-8 -*-
import json
import logging

from app.constants import BASE_KEY
from app.logging_service import LogType, format_and_log
from config import settings


class DataManager:
    def __init__(self):
        self.db = None
        self.base_key = BASE_KEY

    def initialize(self, redis_db):
        """注入 Redis DB 依赖"""
        self.db = redis_db
        if self.db and self.db.is_connected:
            format_and_log(LogType.SYSTEM, "组件初始化", {'组件': 'DataManager', '状态': '依赖注入完成'})
        else:
            format_and_log(LogType.SYSTEM, "组件初始化", {'组件': 'DataManager', '状态': '已禁用 (Redis未连接)'})

    def _get_key(self, account_id: str = None) -> str:
        """获取指定账户或当前账户的 Redis Key"""
        acc_id = account_id or settings.ACCOUNT_ID
        if not acc_id:
            return f"{self.base_key}:uninitialized"
        return f"{self.base_key}:{acc_id}"

    async def get_all_assistant_keys(self) -> list:
        """获取所有助手的 Redis Keys"""
        if not self.db or not self.db.is_connected:
            return []
        
        keys = []
        try:
            # [最终修复] self.db.scan_iter() 直接返回一个可用的异步迭代器，无需 await
            async for key in self.db.scan_iter(f"{self.base_key}:*"):
                keys.append(key)
        except Exception as e:
            format_and_log(LogType.ERROR, "DataManager 扫描 keys 失败", {'错误': str(e)}, level=logging.CRITICAL)
        
        return keys

    async def get_full_state(self, account_id: str = None) -> dict:
        """获取一个账户的完整状态字典"""
        if not self.db or not self.db.is_connected: return {}
        key = self._get_key(account_id)
        data = await self.db.hgetall(key)
        return data if data else {}

    async def get_value(self, field: str, account_id: str = None, is_json: bool = False, default=None):
        """通用获取函数"""
        if not self.db or not self.db.is_connected: return default
        redis_key = self._get_key(account_id)
        value = await self.db.hget(redis_key, field)
        if value is None: return default
        try:
            return json.loads(value) if is_json else value
        except (json.JSONDecodeError, TypeError):
            return default

    async def save_value(self, field: str, value, account_id: str = None):
        """通用保存函数"""
        if not self.db or not self.db.is_connected: return
        is_json = isinstance(value, (dict, list))
        payload = json.dumps(value, ensure_ascii=False) if is_json else str(value)
        redis_key = self._get_key(account_id)
        await self.db.hset(redis_key, field, payload)

    async def delete_value(self, field: str, account_id: str = None):
        """通用删除函数"""
        if not self.db or not self.db.is_connected: return
        redis_key = self._get_key(account_id)
        await self.db.hdel(redis_key, field)

    async def clear_all_data(self) -> int:
        """清空所有助手缓存数据"""
        if not self.db or not self.db.is_connected: return 0
        keys_to_delete = await self.get_all_assistant_keys()
        if keys_to_delete:
            await self.db.delete(*keys_to_delete)
        return len(keys_to_delete)


# 创建全局单例
data_manager = DataManager()
