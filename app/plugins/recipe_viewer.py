# -*- coding: utf-8 -*-
from app.context import get_application
from .logic import recipe_logic
from app.utils import send_paginated_message

HELP_TEXT_RECIPE = """📚 **查询配方数据库**
**用法 1 (查询列表)**:
  `,查询配方`
**用法 2 (查询详情)**:
  `,查询配方 <物品名称>`
**示例**: `,查询配方 风雷翅`
"""

async def _cmd_view_recipes(event, parts):
    if len(parts) == 1:
        result_text = await recipe_logic.logic_list_all_recipes()
    else:
        item_name = " ".join(parts[1:])
        result_text = await recipe_logic.logic_get_specific_recipe(item_name)
    
    await get_application().client.reply_to_admin(event, result_text)


def initialize(app):
    app.register_command(
        # [修改] 指令名改为4个字
        name="查询配方", 
        handler=_cmd_view_recipes, 
        help_text="📚 查询配方数据库。", 
        category="知识", 
        # [修改] 将旧名称加入别名
        aliases=["配方"],
        usage=HELP_TEXT_RECIPE
    )
