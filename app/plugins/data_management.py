# -*- coding: utf-8 -*-
from app.context import get_application
from .logic import data_logic
from app.utils import require_args, send_paginated_message

HELP_TEXT_QUERY_QA = "📚 **查询题库内容**\n**用法**: `,查询题库 <玄骨|天机>`"

# --- 核心修改：更新帮助文本 ---
HELP_TEXT_DELETE_ANSWER = """🗑️ **删除题库问答**
**用法**: `,删除答案 <题库> <编号|“问题”>`
**参数**:
  - `题库`: `玄骨` 或 `天机`
  - `编号|“问题”`: 要删除的问题编号 (通过 `,查询题库` 获取) 或完整的带引号的问题原文。
**示例**:
  `,删除答案 玄骨 5`
  `,删除答案 天机 "第一道题的题目是什么？"`"""

HELP_TEXT_UPDATE_ANSWER = """✍️ **修改/添加题库问答**
**用法**: `,修改答案 <题库> <编号|“问题”> “<答案>”`
**参数**:
  - `题库`: `玄骨` 或 `天机`
  - `编号|“问题”`: 要修改的问题编号或问题原文。如果问题不存在，则会添加为新条目。
  - `答案`: 新的正确答案。
**示例**:
  `,修改答案 天机 1 "这是新的正确答案"`
  `,修改答案 玄骨 "某个问题" "这是它的答案"`"""

async def _cmd_redis_status(event, parts):
    await get_application().client.reply_to_admin(event, await data_logic.logic_get_redis_status())

async def _cmd_view_inventory(event, parts):
    await get_application().client.reply_to_admin(event, await data_logic.logic_view_inventory())

@require_args(count=2, usage=HELP_TEXT_QUERY_QA)
async def _cmd_query_qa_db(event, parts):
    await send_paginated_message(event, await data_logic.logic_query_qa_db(parts[1]))

# --- 核心修改：参数数量减少，因为问题和编号现在是同一个参数 ---
@require_args(count=3, usage=HELP_TEXT_DELETE_ANSWER)
async def _cmd_delete_answer(event, parts):
    _, db_key, identifier = parts
    await get_application().client.reply_to_admin(event, await data_logic.logic_delete_answer(db_key, identifier))

@require_args(count=4, usage=HELP_TEXT_UPDATE_ANSWER)
async def _cmd_update_answer(event, parts):
    _, db_key, identifier, answer = parts
    await get_application().client.reply_to_admin(event, await data_logic.logic_update_answer(db_key, identifier, answer))

def initialize(app):
    app.register_command("查询redis", _cmd_redis_status, help_text="🗄️ 检查Redis状态", category="数据查询", aliases=['redis'])
    app.register_command("查看背包", _cmd_view_inventory, help_text="🎒 查看缓存的背包", category="数据查询")
    app.register_command("查询题库", _cmd_query_qa_db, help_text="📚 查询题库内容", category="数据查询", usage=HELP_TEXT_QUERY_QA)
    app.register_command("删除答案", _cmd_delete_answer, help_text="🗑️ 删除题库问答", category="数据管理", usage=HELP_TEXT_DELETE_ANSWER)
    app.register_command("修改答案", _cmd_update_answer, help_text="✍️ 修改/添加题库问答", category="数据管理", usage=HELP_TEXT_UPDATE_ANSWER)
