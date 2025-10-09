# -*- coding: utf-8 -*-
import asyncio
import logging
from functools import wraps
import redis.asyncio as redis
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
        """检查当前是否认为连接是活跃的。"""
        return self._is_connected.is_set()

    # [修复] 将装饰器本身变成一个方法，以正确处理 'self'
    def _connection_guard(self, func):
        """
        一个装饰器方法，用于包装所有 Redis 操作。
        - 捕获连接错误。
        - 根据操作类型（读/写）进行优雅降级。
        """
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # 'self' 现在可以从外部作用域正确捕获
            if not self._client or not self.is_connected:
                if self._is_read_command(func.__name__):
                    return None
                return 0

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
                
                if self._is_read_command(func.__name__):
                    return None
                return 0
            except Exception as e:
                format_and_log(LogType.ERROR, "Redis 操作异常", {'命令': func.__name__, '错误': str(e)}, level=logging.ERROR)
                if self._is_read_command(func.__name__):
                    return None
                return 0
        return wrapper

    def __getattr__(self, name):
        """
        通过 __getattr__ 魔法方法，将所有未在 Wrapper 中定义的方法调用
        都转发给内部的真实 Redis 客户端实例，并通过装饰器进行包装。
        """
        if self._client is None:
            # 如果没有真实客户端，返回一个什么都不做的异步函数以防止崩溃
            async def noop(*args, **kwargs):
                return None
            return noop
            
        attr = getattr(self._client, name)
        if callable(attr):
            # 对所有可调用方法应用我们的连接保护装饰器
            return self._connection_guard(attr)
        return attr

    @staticmethod
    def _is_read_command(command_name: str) -> bool:
        """判断一个命令是否为“读”操作。"""
        read_commands = [
            'get', 'hget', 'hgetall', 'exists', 'hexists', 'keys', 'hkeys', 
            'ping', 'scan_iter', 'type', 'strlen', 'llen', 'lrange'
        ]
        return command_name in read_commands

    # --- 特殊处理 Pub/Sub ---
    def pubsub(self):
        if not self._client:
            class FakePubSub:
                async def __aenter__(self): return self
                async def __aexit__(self, exc_type, exc_val, exc_tb): pass
                async def subscribe(self, *args, **kwargs): pass
                async def listen(self): 
                    yield None
            return FakePubSub()
        return self._client.pubsub()

