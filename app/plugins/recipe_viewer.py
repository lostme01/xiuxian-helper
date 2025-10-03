# -*- coding: utf-8 -*-
from app.context import get_application
from .logic import recipe_logic
from app.utils import send_paginated_message

HELP_TEXT_RECIPE = """📚 **查询配方数据库**
**用法 1 (查询列表)**:
  `,`配方
**用法 2 (查询详情)**:
  `,`配方 <物品名称>
**示例**: `,配方 风雷翅`
"""

async def _cmd_view_recipes(event, parts):
    """
    处理 ,配方 指令。
    """
    # 如果只有 ,配方，则列出所有
    if len(parts) == 1:
        result_text = await recipe_logic.logic_list_all_recipes()
    # 如果有参数，则查询具体物品
    else:
        item_name = " ".join(parts[1:])
        result_text = await recipe_logic.logic_get_specific_recipe(item_name)
    
    await get_application().client.reply_to_admin(event, result_text)


def initialize(app):
    app.register_command(
        name="配方",
        handler=_cmd_view_recipes,
        help_text="📚 查询配方数据库。",
        category="数据查询",
        usage=HELP_TEXT_RECIPE
    )
