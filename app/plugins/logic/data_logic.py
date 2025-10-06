# -*- coding: utf-8 -*-
import json
from config import settings
from app.context import get_application
from app.utils import mask_string

async def logic_get_redis_status() -> str:
    """获取 Redis 连接状态"""
    app = get_application()
    if not app.redis_db: return "🗄️ **Redis**: `已禁用`"
    try:
        if await app.redis_db.ping():
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
    app = get_application()
    inventory = await app.inventory_manager.get_inventory()
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
        
    qa_data = await app.redis_db.hgetall(redis_key)
    if not qa_data: return f"📚 **{db_key}** 知识库为空。"
    
    sorted_qa = sorted(qa_data.items())
    response_lines = [f"**{i}. 问**: `{q}`\n   **答**: `{a}`" for i, (q, a) in enumerate(sorted_qa, 1)]
    title = f"📚 **{db_key}** 知识库 (共 {len(sorted_qa)} 条)"
    
    return f"{title}\n\n" + "\n\n".join(response_lines)

async def _get_question_by_id(redis_db, redis_key: str, item_id_str: str) -> str | None:
    try:
        item_id = int(item_id_str)
        if item_id <= 0: return None
        
        all_questions = await redis_db.hkeys(redis_key)
        if not all_questions: return None
        
        sorted_questions = sorted(all_questions)
        if item_id > len(sorted_questions): return None
        
        return sorted_questions[item_id - 1]
    except (ValueError, IndexError):
        return None

async def logic_delete_answer(db_key: str, identifier: str) -> str:
    """从题库删除问答（支持问题原文或编号）"""
    app = get_application()
    db_map = {"玄骨": settings.REDIS_CONFIG['xuangu_db_name'], "天机": settings.REDIS_CONFIG['tianji_db_name']}
    if db_key not in db_map: return f"❓ 未知的题库: `{db_key}`"
    if not app.redis_db: return "❌ 错误: Redis 未连接。"
    
    redis_key = db_map[db_key]
    
    question = await _get_question_by_id(app.redis_db, redis_key, identifier)
    if not question:
        question = identifier
        
    if await app.redis_db.hexists(redis_key, question):
        await app.redis_db.hdel(redis_key, question)
        return f"✅ 已从 **[{db_key}]** 题库中删除问题:\n`{question}`"
    else: return f"❓ 在 **[{db_key}]** 题库中未找到编号或问题:\n`{identifier}`"

async def logic_update_answer(db_key: str, identifier: str, answer: str) -> str:
    """更新或添加题库问答（支持问题原文或编号）"""
    app = get_application()
    db_map = {"玄骨": settings.REDIS_CONFIG['xuangu_db_name'], "天机": settings.REDIS_CONFIG['tianji_db_name']}
    if db_key not in db_map: return f"❓ 未知的题库: `{db_key}`"
    if not app.redis_db: return "❌ 错误: Redis 未连接。"
    
    redis_key = db_map[db_key]
    
    question = await _get_question_by_id(app.redis_db, redis_key, identifier)
    if not question:
        question = identifier
        
    await app.redis_db.hset(redis_key, question, answer)
    return f"✅ 已在 **[{db_key}]** 题库中更新/添加:\n**问**: `{question}`\n**答**: `{answer}`"


async def logic_find_and_clear_cache(identifier: str, confirmed: bool = False) -> str:
    """根据用户名或ID查找并清理助手缓存"""
    app = get_application()
    if not app.data_manager: return "❌ 错误: DataManager 未初始化。"

    keys_found = await app.data_manager.get_all_assistant_keys()
    
    target_key = None
    profile_info = {}

    for key in keys_found:
        try:
            key_user_id = key.split(':')[-1]
            profile = await app.data_manager.get_value("character_profile", account_id=key_user_id, is_json=True, default={})

            profile_user = profile.get("用户")
            profile_user_id = str(profile.get("ID", ""))

            is_match = (profile_user and identifier.lower() == profile_user.lower()) or \
                       (profile_user_id and identifier == profile_user_id) or \
                       (key_user_id and identifier == key_user_id)

            if is_match:
                target_key = key
                profile_info = {
                    "TG 用户名": f"`{profile_user or '未知'}`",
                    "用户ID": f"`{key_user_id}`",
                    "游戏道号": f"`{profile.get('道号', '未知')}`",
                }
                break
        except (json.JSONDecodeError, IndexError):
            continue

    if not target_key:
        return f"❓ 未找到用户名为或ID为 **{identifier}** 的助手缓存。"

    if not confirmed:
        details = "\n".join([f"- **{k}**: {v}" for k, v in profile_info.items()])
        return (f"**⚠️ 请确认是否要删除以下助手的全部缓存？**\n\n"
                f"{details}\n\n"
                f"**此操作不可逆！**\n"
                f"确认请输入: `,清理缓存 {identifier} 确认`")

    try:
        await app.redis_db.delete(target_key)
        return (f"✅ **缓存已成功删除**\n\n"
                f"已清除标识为 **{identifier}** 的所有缓存数据。")
    except Exception as e:
        return f"❌ **删除失败**\n\n删除过程中发生错误: `{e}`"

async def logic_list_cached_assistants() -> str:
    """扫描并列出所有已缓存助手的信息"""
    app = get_application()
    if not app.data_manager: return "❌ 错误: DataManager 未初始化。"

    keys_found = await app.data_manager.get_all_assistant_keys()
    if not keys_found:
        return "ℹ️ Redis 中没有任何助手缓存数据。"

    assistant_lines = []
    for key in keys_found:
        try:
            user_id = key.split(':')[-1]
            profile = await app.data_manager.get_value("character_profile", account_id=user_id, is_json=True, default={})
            user = profile.get("用户", "未知")
            assistant_lines.append(f"- **TG 用户名**: `{user}`, **ID**: `{user_id}`")
        except (json.JSONDecodeError, IndexError):
            continue
    
    if not assistant_lines:
        return "ℹ️ 未能从 Redis 缓存中解析出任何有效的助手信息。"

    header = "👥 **当前已缓存的所有助手列表**:\n\n"
    return header + "\n".join(sorted(assistant_lines))
