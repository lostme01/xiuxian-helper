# -*- coding: utf-8 -*-
import asyncio
import json
import logging

from app.constants import GAME_EVENTS_CHANNEL, TASK_CHANNEL
from app.context import get_application
from app.logging_service import LogType, format_and_log
from config import settings


async def redis_message_handler(message):
    """
    Redis 消息的统一处理器和路由器。
    """
    app = get_application()
    try:
        if not settings.MASTER_SWITCH:
            return 

        data_str = message.get('data', '{}')
        data = json.loads(data_str)
        channel = message.get('channel')
        task_type = data.get("task_type")
        target_id = data.get("target_account_id")

        if channel == GAME_EVENTS_CHANNEL:
            from app.plugins.trade_coordination import _handle_game_event
            await _handle_game_event(app, data)
            return

        if task_type == "broadcast_command":
            from app.plugins.logic.trade_logic import execute_broadcast_command
            await execute_broadcast_command(app, data)
            return

        if str(app.client.me.id) != target_id:
            return

        # [核心修改] 注册全新、安全的知识共享处理器
        from app.plugins.knowledge_sharing import handle_request_recipe_task, handle_fulfill_recipe_request_task
        from app.plugins.trade_coordination import (
            handle_ff_listing_successful, handle_ff_report_state,
            handle_material_delivered, handle_query_state
        )
        plugin_handlers = {
            "listing_successful": handle_ff_listing_successful, 
            "report_state": handle_ff_report_state,
            "crafting_material_delivered": handle_material_delivered,
            "query_state": handle_query_state,
            "request_recipe_from_teacher": handle_request_recipe_task,
            "fulfill_recipe_request": handle_fulfill_recipe_request_task,
        }
        if task_type in plugin_handlers:
            await plugin_handlers[task_type](app, data)
            return

        from app.plugins.logic import trade_logic
        from app.plugins.auto_management import handle_auto_management_tasks
        
        if await handle_auto_management_tasks(data):
            return

        generic_handlers = {
            "list_item_for_ff": trade_logic.execute_listing_task,
            "purchase_item": trade_logic.execute_purchase_task,
            "execute_synced_delist": trade_logic.execute_synced_unlisting_task,
            "execute_purchase": trade_logic.execute_purchase_task,
        }
        
        if task_type in generic_handlers:
            format_and_log(LogType.TASK, "Redis 任务匹配成功", {'任务类型': task_type})
            if task_type == "list_item_for_ff":
                await generic_handlers[task_type](app, data.get("requester_account_id"), **data.get("payload", {}))
            else:
                await generic_handlers[task_type](app, **data.get("payload", {}))
            return

    except (json.JSONDecodeError, TypeError):
        pass
    except Exception as e:
        format_and_log(LogType.ERROR, "Redis 任务处理器异常", {'状态': '执行异常', '错误': str(e), '原始消息': message.get('data', '')})


async def redis_listener_loop():
    app = get_application()
    while True:
        if not app.redis_db or not app.redis_db.is_connected:
            if app.redis_db:
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
