# -*- coding: utf-8 -*-
import redis.asyncio as redis
import logging
from config import settings
from app.logger import format_and_log

# 全局变量，用于存储异步 Redis 客户端实例
db = None

async def initialize_redis():
    """
    [重构版]
    初始化一个全局共享的 Redis 异步连接池和客户端。
    """
    global db

    if not settings.REDIS_CONFIG.get('enabled'):
        format_and_log("SYSTEM", "数据库连接", {'类型': 'Redis', '状态': '已禁用'})
        return None

    try:
        # 创建一个异步连接池
        pool = redis.ConnectionPool.from_url(
            f"redis://{settings.REDIS_CONFIG.get('host', 'localhost')}",
            port=settings.REDIS_CONFIG.get('port', 6379),
            password=settings.REDIS_CONFIG.get('password'),
            db=settings.REDIS_CONFIG.get('db', 0),
            decode_responses=True, # 自动解码，无需手动 .decode()
            socket_connect_timeout=5
        )
        # 从连接池创建一个客户端实例
        db = redis.Redis(connection_pool=pool)
        
        # 验证连接
        await db.ping()
        format_and_log("SYSTEM", "数据库连接", {'类型': 'Redis', '状态': '连接成功'})
        
        return db

    except Exception as e:
        format_and_log("SYSTEM", "数据库连接", {
            '类型': 'Redis', 
            '状态': '连接失败', 
            '错误': str(e),
        }, level=logging.CRITICAL)
        db = None
        return None
