# -*- coding: utf-8 -*-
import re
import asyncio
import random
from app import game_adaptor
from app.logging_service import LogType, format_and_log

async def logic_clear_my_stall(client) -> str:
    """
    核心逻辑：查询当前账号的货摊，并下架所有物品。
    返回一个操作摘要字符串。
    """
    format_and_log(LogType.TASK, "清理货摊", {'阶段': '开始查询'})
    
    # 1. 发送指令并等待直接回复
    _sent, reply = await client.send_game_command_request_response(game_adaptor.get_my_stall())
    reply_text = reply.text
    
    # 2. 检查货摊是否为空
    if "尚未在万宝楼中上架任何物品" in reply_text:
        format_and_log(LogType.TASK, "清理货摊", {'阶段': '完成', '详情': '货摊为空'})
        return "✅ **清理完成**：您的货摊上没有任何物品。"
        
    # 3. 解析所有挂单ID
    listing_ids = re.findall(r'\*\*ID: (\d+)\*\*', reply_text)
    if not listing_ids:
        format_and_log(LogType.WARNING, "清理货摊", {'阶段': '解析失败', '原因': '无法从收到的回复中解析出ID'})
        return f"❓ **操作异常**：无法从货摊信息中解析出任何挂单ID。\n\n**游戏返回**:\n`{reply_text}`"
    
    format_and_log(LogType.TASK, "清理货摊", {'阶段': '解析成功', '待下架ID': str(listing_ids)})
    
    # 4. 逐一下架
    delisted_count = 0
    failed_ids = []
    
    for item_id in listing_ids:
        try:
            delist_command = game_adaptor.unlist_item(item_id)
            await client.send_game_command_fire_and_forget(delist_command)
            delisted_count += 1
            await asyncio.sleep(random.uniform(2, 4))
        except Exception as e:
            failed_ids.append(item_id)
            format_and_log(LogType.ERROR, "清理货摊-单项失败", {'ID': item_id, '错误': str(e)})

    # 5. 生成并返回最终报告
    report_lines = [f"✅ **清理完成**：共尝试下架 **{len(listing_ids)}** 件物品。"]
    report_lines.append(f"- **成功发送指令**: {delisted_count} 次")
    if failed_ids:
        report_lines.append(f"- **失败**: {len(failed_ids)} 次 (ID: `{', '.join(failed_ids)}`)")
        
    summary = "\n".join(report_lines)
    format_and_log(LogType.TASK, "清理货摊", {'阶段': '完成', '摘要': summary})
    return summary
