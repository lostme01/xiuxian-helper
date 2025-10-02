# -*- coding: utf-8 -*-
import json
import logging
import os
from app import redis_client
from app.utils import read_state as read_from_file, write_state as write_to_file, read_json_state as read_json_from_file, write_json_state as write_json_to_file
from app.logger import format_and_log
from config import settings

_REDIS_BASE_HASH_KEY = "tg_helper:task_states"

def _get_redis_key_for_account():
    """根据配置动态生成当前账户的 Redis Key"""
    if not settings.ACCOUNT_ID:
        raise RuntimeError("ACCOUNT_ID not set. State manager cannot operate before login.")
    return f"{_REDIS_BASE_HASH_KEY}:{settings.ACCOUNT_ID}"

async def set_state(key: str, value):
    """
    保存一个状态值。优先使用 Redis，失败则降级到文件。
    """
    is_json = isinstance(value, (dict, list))
    
    if redis_client.db:
        try:
            redis_key = _get_redis_key_for_account()
            payload = json.dumps(value, ensure_ascii=False) if is_json else value
            await redis_client.db.hset(redis_key, key, payload)
            return
        except Exception as e:
            format_and_log("SYSTEM", "状态管理降级", {'原因': 'Redis写入失败', '键': key, '错误': str(e)}, level=logging.WARNING)
    
    if is_json:
        file_path = f"{settings.DATA_DIR}/{key}.json"
        write_json_to_file(file_path, value)
    else:
        file_path = f"{settings.DATA_DIR}/{key}.state"
        write_to_file(file_path, str(value))

async def get_state(key: str, is_json: bool = False, default=None):
    """
    获取一个状态值。优先从 Redis 读取，失败则降级到文件。
    """
    if redis_client.db:
        try:
            redis_key = _get_redis_key_for_account()
            value = await redis_client.db.hget(redis_key, key)
            if value is not None:
                return json.loads(value) if is_json else value
        except Exception as e:
            format_and_log("SYSTEM", "状态管理降级", {'原因': 'Redis读取失败', '键': key, '错误': str(e)}, level=logging.WARNING)

    if is_json:
        file_path = f"{settings.DATA_DIR}/{key}.json"
        content = read_json_from_file(file_path)
        return content if content is not None else default
    else:
        file_path = f"{settings.DATA_DIR}/{key}.state"
        content = read_from_file(file_path)
        return content if content is not None else default

async def delete_state(key: str):
    """
    删除一个状态值，同时操作 Redis 和对应的降级文件。
    """
    if redis_client.db:
        try:
            redis_key = _get_redis_key_for_account()
            await redis_client.db.hdel(redis_key, key)
        except Exception as e:
            format_and_log("SYSTEM", "状态删除失败", {'存储': 'Redis', '键': key, '错误': str(e)}, level=logging.WARNING)
    
    file_path_state = f"{settings.DATA_DIR}/{key}.state"
    file_path_json = f"{settings.DATA_DIR}/{key}.json"
    for file_path in [file_path_state, file_path_json]:
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except OSError as e:
                format_and_log("SYSTEM", "状态删除失败", {'存储': 'File', '路径': file_path, '错误': str(e)}, level=logging.WARNING)
