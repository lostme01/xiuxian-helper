# -*- coding: utf-8 -*-
import asyncio
import json
import logging

from app.constants import GAME_EVENTS_CHANNEL, TASK_CHANNEL
from app.context import get_application
from app.logging_service import LogType, format_and_log

# --- 核心处理器 ---

async def redis_message_handler(message):
    """
    Redis 消息的统一处理器和路由器。
    """
    app = get_application()
    try:
        data_str = message.get('data', '{}')
        data = json.loads(data_str)
        channel = message.get('channel')
        task_type = data.get("task_type")
        target_id = data.get("target_account_id")

        # 1. 路由游戏事件
        if channel == GAME_EVENTS_CHANNEL:
            from app.plugins.trade_coordination import _handle_game_event
            await _handle_game_event(app, data)
            return

        # 检查是否是针对本机的任务
        if str(app.client.me.id) != target_id:
            # 广播指令是例外，它没有target_id，需要所有非admin号执行
            if task_type != "broadcast_command":
                return

        # --- 路由到插件的特定任务处理器 ---
        from app.plugins.trade_coordination import (
            handle_ff_listing_successful, handle_ff_report_state,
            handle_material_delivered, handle_query_state,
            handle_propose_knowledge_share
        )
        plugin_handlers = {
            # 集火流程
            "listing_successful": handle_ff_listing_successful, 
            "report_state": handle_ff_report_state,
            # 智能炼制流程
            "crafting_material_delivered": handle_material_delivered,
            # 知识共享流程
            "propose_knowledge_share": handle_propose_knowledge_share,
            # 通用
            "query_state": handle_query_state
        }
        if task_type in plugin_handlers:
            await plugin_handlers[app, data]
            return

        # --- 路由到通用的逻辑处理器 ---
        from app.plugins.logic import trade_logic
        from app.plugins.auto_management import handle_auto_management_tasks
        
        if await handle_auto_management_tasks(data):
            return

        generic_handlers = {
            "broadcast_command": trade_logic.execute_broadcast_command,
            "list_item_for_ff": trade_logic.execute_listing_task,
            "purchase_item": trade_logic.execute_purchase_task,
            "execute_synced_delist": trade_logic.execute_synced_unlisting_task,
            # [新增] 集火购买方的最终执行任务
            "execute_purchase": trade_logic.execute_purchase_task,
        }
        
        if task_type in generic_handlers:
            format_and_log(LogType.TASK, "Redis 任务匹配成功", {'任务类型': task_type})
            if task_type == "list_item_for_ff":
                await generic_handlers[task_type](app, data.get("requester_account_id"), **data.get("payload", {}))
            else:
                 # broadcast_command 和其他任务有不同的签名
                if task_type == 'broadcast_command':
                    await generic_handlers[task_type](app, data)
                else:
                    await generic_handlers[task_type](app, **data.get("payload", {}))
            return

    except (json.JSONDecodeError, TypeError):
        # 忽略无法解析的非JSON消息
        pass
    except Exception as e:
        format_and_log(LogType.ERROR, "Redis 任务处理器异常", {'状态': '执行异常', '错误': str(e), '原始消息': message.get('data', '')})


async def redis_listener_loop():
    """
    负责监听 Redis 频道的后台循环。
    """
    app = get_application()
    while True:
        if not app.redis_db or not app.redis_db.is_connected:
            if app.redis_db: # Check if redis is enabled
                format_and_log(LogType.WARNING, "Redis 监听器", {'状态': '暂停', '原因': 'Redis 未连接'})
                await asyncio.sleep(15)
            else:
                return
        try:
            async with app.redis_db.pubsub() as pubsub:
                await pubsub.subscribe(TASK_CHANNEL, GAME_EVENTS_CHANNEL)
                format_and_log(LogType.SYSTEM, "核心服务",
                               {'服务': 'Redis 监听器', '状态': '已订阅', '频道': f"{TASK_CHANNEL}, {GAME_EVENTS_CHANNEL}"})
                async for message in pubsub.listen():
                    if not app.redis_db.is_connected:
                        format_and_log(LogType.WARNING, "Redis 监听器", {'状态': '中断', '原因': '连接在监听时丢失'})
                        break
                    if message and message.get('type') == 'message':
                        format_and_log(LogType.DEBUG, "Redis 监听器", {'阶段': '收到消息', '原始返回': str(message)})
                        asyncio.create_task(redis_message_handler(message))
        except Exception as e:
            format_and_log(LogType.ERROR, "Redis 监听循环异常", {'错误': str(e)}, level=logging.CRITICAL)
            await asyncio.sleep(15)
