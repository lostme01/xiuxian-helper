# -*- coding: utf-8 -*-
import redis
import logging
from config import settings
from app.logger import format_and_log

# 初始化一个全局变量，初始为 None
db = None

def initialize_redis():
    """
    初始化 Redis 连接，并设置全局 db 变量。
    返回连接成功与否的布尔值。
    """
    global db

    if not settings.REDIS_CONFIG.get('enabled'):
        format_and_log("SYSTEM", "数据库连接", {'类型': 'Redis', '状态': '已禁用'})
        return False

    try:
        pool = redis.ConnectionPool(
            host=settings.REDIS_CONFIG.get('host', 'localhost'),
            port=settings.REDIS_CONFIG.get('port', 6379),
            password=settings.REDIS_CONFIG.get('password'),
            db=settings.REDIS_CONFIG.get('db', 0),
            decode_responses=True,
            socket_connect_timeout=5
        )
        db = redis.Redis(connection_pool=pool)
        db.ping()
        format_and_log("SYSTEM", "数据库连接", {'类型': 'Redis', '状态': '连接成功'})
        return True

    except Exception as e:
        format_and_log("SYSTEM", "数据库连接", {
            '类型': 'Redis', 
            '状态': '连接失败', 
            '错误': str(e),
        }, level=logging.CRITICAL)
        db = None
        return False
