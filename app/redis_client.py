# -*- coding: utf-8 -*-
import redis.asyncio as redis
import logging
from config import settings
from app.logger import format_and_log

# 初始化两个全局变量，初始为 None
db = None
pubsub_client = None

async def initialize_redis():
    """
    初始化 Redis 异步连接。
    成功时返回 Redis 客户端实例，失败时返回 None。
    """
    global db, pubsub_client

    if not settings.REDIS_CONFIG.get('enabled'):
        format_and_log("SYSTEM", "数据库连接", {'类型': 'Redis', '状态': '已禁用'})
        return None

    try:
        # --- 改造：为常规操作和 Pub/Sub 创建独立的连接池 ---
        pool = redis.ConnectionPool(
            host=settings.REDIS_CONFIG.get('host', 'localhost'),
            port=settings.REDIS_CONFIG.get('port', 6379),
            password=settings.REDIS_CONFIG.get('password'),
            db=settings.REDIS_CONFIG.get('db', 0),
            decode_responses=True,
            socket_connect_timeout=5
        )
        db = redis.Redis(connection_pool=pool)
        await db.ping()
        format_and_log("SYSTEM", "数据库连接", {'类型': 'Redis (常规)', '状态': '连接成功'})

        # 为 Pub/Sub 创建另一个客户端，它将使用自己的连接
        pubsub_client = redis.Redis(connection_pool=pool)
        format_and_log("SYSTEM", "数据库连接", {'类型': 'Redis (Pub/Sub)', '状态': '客户端已创建'})

        return db

    except Exception as e:
        format_and_log("SYSTEM", "数据库连接", {
            '类型': 'Redis',
            '状态': '连接失败',
            '错误': str(e),
        }, level=logging.CRITICAL)
        db = None
        pubsub_client = None
        return None
