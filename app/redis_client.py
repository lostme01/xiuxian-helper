# -*- coding: utf-8 -*-
import logging
import redis.asyncio as redis
from app.logging_service import LogType, format_and_log
from config import settings
from app.redis_wrapper import RedisWrapper

# 全局变量，用于存储 Redis 包装器实例
db: RedisWrapper | None = None

async def initialize_redis():
    """
    初始化一个全局共享的、带健壮性包装的 Redis 客户端。
    """
    global db

    if not settings.REDIS_CONFIG.get('enabled'):
        format_and_log(LogType.SYSTEM, "数据库连接", {'类型': 'Redis', '状态': '已禁用'})
        db = RedisWrapper(None) # 即使禁用，也创建一个空的包装器
        return db

    try:
        # 创建一个异步连接池
        pool = redis.ConnectionPool.from_url(
            f"redis://{settings.REDIS_CONFIG.get('host', 'localhost')}",
            port=settings.REDIS_CONFIG.get('port', 6379),
            password=settings.REDIS_CONFIG.get('password'),
            db=settings.REDIS_CONFIG.get('db', 0),
            decode_responses=True,  # 自动解码，无需手动 .decode()
            socket_connect_timeout=5,
            health_check_interval=30 # 增加健康检查
        )
        # 从连接池创建一个真实的客户端实例
        real_client = redis.Redis(connection_pool=pool)

        # 验证连接
        await real_client.ping()
        format_and_log(LogType.SYSTEM, "数据库连接", {'类型': 'Redis', '状态': '连接成功'})

        # 将真实客户端包装起来并赋值给全局变量
        db = RedisWrapper(real_client)
        return db

    except Exception as e:
        format_and_log(LogType.SYSTEM, "数据库连接", {
            '类型': 'Redis',
            '状态': '连接失败',
            '错误': str(e),
        }, level=logging.CRITICAL)
        # 即使连接失败，也创建一个空的包装器，防止程序在调用 db 时直接崩溃
        db = RedisWrapper(None)
        return db
