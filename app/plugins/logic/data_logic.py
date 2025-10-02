# -*- coding: utf-8 -*-
from config import settings
from app.context import get_application
from app.state_manager import get_state
from app.utils import mask_string

async def logic_get_redis_status() -> str:
    """获取 Redis 连接状态"""
    app = get_application()
    if not app.redis_db: return "🗄️ **Redis**: `已禁用`"
    try:
        if app.redis_db.ping():
            config = settings.REDIS_CONFIG
            masked_pass = mask_string(config.get('password')) if config.get('password') else "未设置"
            return (f"🗄️ **Redis 连接状态**\n"
                    f"  - `状态`: ✅ 连接成功\n"
                    f"  - `主机`: `{config.get('host')}`\n"
                    f"  - `端口`: `{config.get('port')}`\n"
                    f"  - `密码`: `{masked_pass}`\n"
                    f"  - `DB`: `{config.get('db')}`")
        else: return "🗄️ **Redis 连接状态**: `❌ 连接失败`"
    except Exception as e: return f"🗄️ **Redis 连接状态**: `❌ 连接异常: {e}`"

async def logic_view_inventory() -> str:
    """查看缓存的背包内容"""
    inventory = get_state("inventory", is_json=True, default={})
    if not inventory: return "🎒 你的储物袋是空的或尚未缓存。"
    header = "🎒 **储物袋内容 (缓存)**:\n"
    items = [f"- `{name}` x {count}" for name, count in sorted(inventory.items())]
    return header + "\n".join(items)

async def logic_query_qa_db(db_key: str) -> str:
    """查询指定题库的内容"""
    app = get_application()
    db_map = {"玄骨": settings.REDIS_CONFIG['xuangu_db_name'], "天机": settings.REDIS_CONFIG['tianji_db_name']}
    if db_key not in db_map: return f"**用法**: `,查询题库 <玄骨|天机>`"
    
    redis_key = db_map[db_key]
    if not app.redis_db:
        return "❌ 错误: Redis 未连接。"
        
    qa_data = app.redis_db.hgetall(redis_key)
    if not qa_data: return f"📚 **{db_key}** 知识库为空。"
    
    sorted_qa = sorted(qa_data.items())
    response_lines = [f"{i}. **问**: `{q}`\n   **答**: `{a}`" for i, (q, a) in enumerate(sorted_qa, 1)]
    title = f"📚 **{db_key}** 知识库 (共 {len(sorted_qa)} 条)"
    
    return f"{title}\n\n" + "\n\n".join(response_lines)

async def logic_delete_answer(db_key: str, question: str) -> str:
    """从题库删除问答"""
    app = get_application()
    db_map = {"玄骨": settings.REDIS_CONFIG['xuangu_db_name'], "天机": settings.REDIS_CONFIG['tianji_db_name']}
    if db_key not in db_map: return f"❓ 未知的题库: `{db_key}`"
    if not app.redis_db: return "❌ 错误: Redis 未连接。"
    redis_key = db_map[db_key]
    if app.redis_db.hexists(redis_key, question):
        app.redis_db.hdel(redis_key, question)
        return f"✅ 已从 **[{db_key}]** 题库中删除问题:\n`{question}`"
    else: return f"❓ 在 **[{db_key}]** 题库中未找到问题:\n`{question}`"

async def logic_update_answer(db_key: str, question: str, answer: str) -> str:
    """更新或添加题库问答"""
    app = get_application()
    db_map = {"玄骨": settings.REDIS_CONFIG['xuangu_db_name'], "天机": settings.REDIS_CONFIG['tianji_db_name']}
    if db_key not in db_map: return f"❓ 未知的题库: `{db_key}`"
    if not app.redis_db: return "❌ 错误: Redis 未连接。"
    redis_key = db_map[db_key]
    app.redis_db.hset(redis_key, question, answer)
    return f"✅ 已在 **[{db_key}]** 题库中更新/添加:\n**问**: `{question}`\n**答**: `{answer}`"
