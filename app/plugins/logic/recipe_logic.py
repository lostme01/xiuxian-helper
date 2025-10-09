# -*- coding: utf-8 -*-
import json
from app.context import get_application
from app.logging_service import LogType, format_and_log

CRAFTING_RECIPES_KEY = "crafting_recipes"

async def logic_list_all_recipes() -> str:
    """获取所有可炼制物品的列表"""
    app = get_application()
    if not app.redis_db:
        return "❌ 错误: Redis 未连接。"
        
    try:
        all_items = await app.redis_db.hkeys(CRAFTING_RECIPES_KEY)
        if not all_items:
            return "ℹ️ 配方数据库为空。"
            
        header = "📚 **当前已记录的所有配方:**\n\n"
        # 每行显示3个，更美观
        col_width = 20
        formatted_items = []
        line_items = []
        for item in sorted(all_items):
            line_items.append(f"`{item}`")
            if len(line_items) == 3:
                formatted_items.append(" ".join(line_items))
                line_items = []
        if line_items:
            formatted_items.append(" ".join(line_items))

        usage = "\n\n**使用 `,配方 <物品名称>` 查询具体配方。**"
        return header + "\n".join(formatted_items) + usage
        
    except Exception as e:
        return f"❌ 查询配方列表时出错: {e}"

async def logic_get_specific_recipe(item_name: str) -> str:
    """获取指定物品的配方"""
    app = get_application()
    if not app.redis_db:
        return "❌ 错误: Redis 未连接。"
        
    try:
        recipe_json = await app.redis_db.hget(CRAFTING_RECIPES_KEY, item_name)
        if not recipe_json:
            return f"❓ 未在数据库中找到 **{item_name}** 的配方。"
            
        recipe = json.loads(recipe_json)
        
        if "error" in recipe:
            return f"ℹ️ **{item_name}**: {recipe['error']}"
            
        header = f"🛠️ **{item_name}** 的配方:\n"
        materials = [f"- `{name}` x {count}" for name, count in recipe.items()]
        return header + "\n".join(materials)
        
    except Exception as e:
        return f"❌ 查询配方“{item_name}”时出错: {e}"
