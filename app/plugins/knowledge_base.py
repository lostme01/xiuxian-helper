# -*- coding: utf-8 -*-
from app.context import get_application
from .logic import knowledge_base_logic as kb_logic
from app.utils import require_args, send_paginated_message

HELP_TEXT_KB = """🧠 **游戏知识库**
**说明**: 一个用于记录和查询您自己的游戏攻略、心得和数据的系统。

**用法**:
  `,添加知识 <条目> "<内容>"`
  *示例: `,添加知识 天雷竹获取方式 "在XX地图的雷雨天气采集"`*

  `,查询知识 [<条目>]`
  *不带参数可列出所有条目。*
  *示例: `,查询知识 天雷竹获取方式`*

  `,删除知识 <条目>`
  *示例: `,删除知识 天雷竹获取方式`*
"""

@require_args(count=3, usage=HELP_TEXT_KB)
async def _cmd_add_kb(event, parts):
    key = parts[1]
    value = " ".join(parts[2:])
    await get_application().client.reply_to_admin(event, await kb_logic.logic_add_kb_entry(key, value.strip('"')))

async def _cmd_get_kb(event, parts):
    if len(parts) == 1:
        result = await kb_logic.logic_list_kb_entries()
    else:
        key = " ".join(parts[1:])
        result = await kb_logic.logic_get_kb_entry(key)
    await send_paginated_message(event, result)

@require_args(count=2, usage=HELP_TEXT_KB)
async def _cmd_delete_kb(event, parts):
    key = " ".join(parts[1:])
    await get_application().client.reply_to_admin(event, await kb_logic.logic_delete_kb_entry(key))

def initialize(app):
    app.register_command("添加知识", _cmd_add_kb, help_text="向知识库添加新条目", category="知识库", usage=HELP_TEXT_KB)
    app.register_command("查询知识", _cmd_get_kb, help_text="查询知识库内容", category="知识库", usage=HELP_TEXT_KB)
    app.register_command("删除知识", _cmd_delete_kb, help_text="从知识库删除条目", category="知识库", usage=HELP_TEXT_KB)
