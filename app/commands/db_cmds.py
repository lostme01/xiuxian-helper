# -*- coding: utf-8 -*-
from config import settings
from app.redis_client import db as redis_db
from app.logger import format_and_log

HELP_DETAILS = {
    "查询题库": "查询已缓存的答题知识库内容。\n用法: `,查询题库 <玄骨|天机>`",
}

async def _cmd_query_qa_db(client, event, parts):
    if len(parts) != 2 or parts[1] not in ["玄骨", "天机"]:
        await event.reply(HELP_DETAILS["查询题库"], parse_mode='md')
        return

    if not redis_db:
        await event.reply("❌ **错误**: Redis 连接不可用，无法查询题库。")
        return

    db_type = parts[1]
    db_name = settings.REDIS_CONFIG['xuangu_db_name'] if db_type == "玄骨" else settings.REDIS_CONFIG['tianji_db_name']
    
    try:
        qa_pairs = redis_db.hgetall(db_name)
        if not qa_pairs:
            await event.reply(f"ℹ️ **{db_type}** 知识库为空。")
            return
        
        reply_text = f"📚 **{db_type} 知识库 (共 {len(qa_pairs)} 条)**:\n\n"
        count = 0
        for question, answer in qa_pairs.items():
            count += 1
            reply_text += f"**{count}. 问**: `{question}`\n** 答**: `{answer}`\n\n"
            # 防止消息过长
            if len(reply_text) > 3500:
                reply_text += "...\n(内容过多，已截断)"
                break
        
        await event.reply(reply_text, parse_mode='md')

    except Exception as e:
        await event.reply(f"❌ 查询题库时发生错误: {e}")
        format_and_log("SYSTEM", "题库查询失败", {'错误': str(e)}, level=logging.ERROR)

def initialize_commands(client):
    client.register_admin_command("查询题库", _cmd_query_qa_db, HELP_DETAILS["查询题库"])
