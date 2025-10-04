# -*- coding: utf-8 -*-
from app.context import get_application

KB_REDIS_KEY = "tg_helper:knowledge_base"

async def logic_add_kb_entry(key: str, value: str) -> str:
    app = get_application()
    if not app.redis_db:
        return "❌ 错误: Redis 未连接。"
    
    await app.redis_db.hset(KB_REDIS_KEY, key, value)
    return f"✅ **知识库已更新**\n\n**条目**: `{key}`\n**内容**: `{value}`"

async def logic_get_kb_entry(key: str) -> str:
    app = get_application()
    if not app.redis_db:
        return "❌ 错误: Redis 未连接。"
        
    value = await app.redis_db.hget(KB_REDIS_KEY, key)
    if value:
        return f"🧠 **知识库查询: {key}**\n\n{value}"
    else:
        return f"❓ 未在知识库中找到关于 `{key}` 的条目。"

async def logic_list_kb_entries() -> str:
    app = get_application()
    if not app.redis_db:
        return "❌ 错误: Redis 未连接。"
    
    all_keys = await app.redis_db.hkeys(KB_REDIS_KEY)
    if not all_keys:
        return "🧠 知识库为空。"
        
    header = "🧠 **知识库现有条目:**\n\n"
    formatted_keys = [f"- `{key}`" for key in sorted(all_keys)]
    usage = "\n\n**使用 `,查询知识 <条目>` 查看详情。**"
    return header + "\n".join(formatted_keys) + usage

async def logic_delete_kb_entry(key: str) -> str:
    app = get_application()
    if not app.redis_db:
        return "❌ 错误: Redis 未连接。"
        
    if await app.redis_db.hdel(KB_REDIS_KEY, key):
        return f"✅ 已从知识库中删除条目: `{key}`"
    else:
        return f"❓ 未在知识库中找到条目: `{key}`"
