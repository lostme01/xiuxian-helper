# -*- coding: utf-8 -*-
from app.context import get_application
from .logic import data_logic
from app.utils import require_args, send_paginated_message

HELP_TEXT_QUERY_QA = """📚 **查询题库内容**
**用法**: `,查询题库 <玄骨|天机>`"""

HELP_TEXT_DELETE_QA = """🗑️ **删除题库问答**
**用法**: `,删除题库 <题库> <编号|“问题”>`"""

HELP_TEXT_UPDATE_QA = """✍️ **修改/添加题库问答**
**用法**: `,修改题库 <题库> <编号|“问题”> “<新答案>”`"""

# [重构] 更新帮助文档
HELP_TEXT_CLEAR_CACHE = """🗑️ **清理助手缓存**
**说明**: 当某个助手账号被封禁或不再使用时，可通过此指令清理其在 Redis 中的所有缓存数据。
**用法**:
  `,清理缓存 <用户名|ID>`
  *第一步：根据 Telegram 用户名或用户ID查找助手并请求确认。*
  
  `,清理缓存 <用户名|ID> 确认`
  *第二步：确认并执行删除操作。*
**示例**:
  `,清理缓存 my_helper_bot`
  `,清理缓存 123456789 确认`
"""

HELP_TEXT_LIST_CACHES = """👥 **查询助手缓存列表**
**说明**: 列出当前 Redis 中缓存的所有助手的 Telegram 用户名和ID。
**用法**: `,查询缓存`
"""

async def _cmd_redis_status(event, parts):
    await get_application().client.reply_to_admin(event, await data_logic.logic_get_redis_status())

async def _cmd_view_inventory(event, parts):
    await get_application().client.reply_to_admin(event, await data_logic.logic_view_inventory())

@require_args(count=2, usage=HELP_TEXT_QUERY_QA)
async def _cmd_query_qa_db(event, parts):
    await send_paginated_message(event, await data_logic.logic_query_qa_db(parts[1]))

@require_args(count=3, usage=HELP_TEXT_DELETE_QA)
async def _cmd_delete_qa(event, parts):
    _, db_key, identifier = parts
    await get_application().client.reply_to_admin(event, await data_logic.logic_delete_answer(db_key, identifier))

@require_args(count=4, usage=HELP_TEXT_UPDATE_QA)
async def _cmd_update_qa(event, parts):
    _, db_key, identifier, answer = parts
    await get_application().client.reply_to_admin(event, await data_logic.logic_update_answer(db_key, identifier, answer))

@require_args(count=2, usage=HELP_TEXT_CLEAR_CACHE)
async def _cmd_clear_cache(event, parts):
    name_to_find = parts[1]
    confirmed = len(parts) > 2 and parts[2].lower() == '确认'
    result = await data_logic.logic_find_and_clear_cache(name_to_find, confirmed)
    await get_application().client.reply_to_admin(event, result)

async def _cmd_list_caches(event, parts):
    result = await data_logic.logic_list_cached_assistants()
    await get_application().client.reply_to_admin(event, result)

def initialize(app):
    app.register_command("查询redis", _cmd_redis_status, help_text="🗄️ 检查Redis状态", category="查询", aliases=['redis'])
    app.register_command("查看背包", _cmd_view_inventory, help_text="🎒 查看缓存的背包", category="查询")
    app.register_command("查询题库", _cmd_query_qa_db, help_text="📚 查询题库内容", category="知识", usage=HELP_TEXT_QUERY_QA)
    app.register_command("删除题库", _cmd_delete_qa, help_text="🗑️ 删除题库问答", category="知识", usage=HELP_TEXT_DELETE_QA)
    app.register_command("修改题库", _cmd_update_qa, help_text="✍️ 修改/添加题库问答", category="知识", usage=HELP_TEXT_UPDATE_QA)
    app.register_command("清理缓存", _cmd_clear_cache, help_text="🗑️ 清理指定助手的缓存", category="系统", usage=HELP_TEXT_CLEAR_CACHE)
    app.register_command("查询缓存", _cmd_list_caches, help_text="👥 列出所有已缓存的助手", category="系统", usage=HELP_TEXT_LIST_CACHES)
