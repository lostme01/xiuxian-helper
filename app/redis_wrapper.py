# -*- coding: utf-8 -*-
import asyncio
import logging
from functools import wraps
import redis
import redis.asyncio as redis_async
from app.logging_service import LogType, format_and_log

class RedisWrapper:
    """
    一个健壮的 Redis 客户端包装器，用于优雅地处理连接错误。
    """
    def __init__(self, client):
        self._client = client
        self._is_connected = asyncio.Event()
        if client:
            self._is_connected.set()

    @property
    def is_connected(self) -> bool:
        return self._is_connected.is_set()

    def _guard_regular_command(self, func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            if not self._client or not self.is_connected:
                return None if self._is_read_command(func.__name__) else 0
            try:
                result = await func(*args, **kwargs)
                if not self._is_connected.is_set():
                    self._is_connected.set()
                    format_and_log(LogType.SYSTEM, "数据库连接恢复", {'类型': 'Redis', '状态': '连接已恢复'})
                return result
            except (redis.exceptions.ConnectionError, redis.exceptions.TimeoutError, asyncio.TimeoutError) as e:
                if self._is_connected.is_set():
                    self._is_connected.clear()
                    format_and_log(LogType.ERROR, "数据库连接中断", {'类型': 'Redis', '错误': str(e)}, level=logging.CRITICAL)
                return None if self._is_read_command(func.__name__) else 0
            except Exception as e:
                format_and_log(LogType.ERROR, "Redis 操作异常", {'命令': func.__name__, '错误': str(e)}, level=logging.ERROR)
                return None if self._is_read_command(func.__name__) else 0
        return wrapper

    def _guard_scan_iter(self, func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            if not self._client or not self.is_connected:
                if False: yield
                return
            try:
                async for item in func(*args, **kwargs):
                    yield item
                if not self._is_connected.is_set():
                    self._is_connected.set()
                    format_and_log(LogType.SYSTEM, "数据库连接恢复", {'类型': 'Redis', '状态': '连接已恢复'})
            except (redis.exceptions.ConnectionError, redis.exceptions.TimeoutError, asyncio.TimeoutError) as e:
                if self._is_connected.is_set():
                    self._is_connected.clear()
                    format_and_log(LogType.ERROR, "数据库连接中断 (scan_iter)", {'类型': 'Redis', '错误': str(e)}, level=logging.CRITICAL)
            except Exception as e:
                format_and_log(LogType.ERROR, "Redis 操作异常", {'命令': func.__name__, '错误': str(e)}, level=logging.ERROR)
        return wrapper

    def __getattr__(self, name):
        if not self._client:
            async def noop_async_gen():
                if False: yield
            def noop_regular(*args, **kwargs):
                return noop_async_gen() if name == 'scan_iter' else asyncio.sleep(0, result=None)
            return noop_regular

        attr = getattr(self._client, name)
        if callable(attr):
            if name == 'scan_iter':
                return self._guard_scan_iter(attr)
            return self._guard_regular_command(attr)
        return attr

    @staticmethod
    def _is_read_command(command_name: str) -> bool:
        read_commands = ['get', 'hget', 'hgetall', 'exists', 'hexists', 'keys', 'hkeys', 'ping', 'type', 'strlen', 'llen', 'lrange']
        return command_name in read_commands

    def pubsub(self):
        if not self._client:
            class FakePubSub:
                async def __aenter__(self): return self
                async def __aexit__(self, exc_type, exc_val, exc_tb): pass
                async def subscribe(self, *args, **kwargs): pass
                async def listen(self):
                    if False: yield
            return FakePubSub()
        return self._client.pubsub()
