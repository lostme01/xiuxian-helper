# -*- coding: utf-8 -*-
import asyncio

from app.context import get_application
from app.utils import create_error_reply
from config import settings

HELP_TEXT_RETAIN = """📌 **保留消息**
**说明**: 回复一条你希望永久保留的、由助手发送的消息，然后发送此指令，可以使其免于被自动删除。
**用法**: `,保留消息` (或 `,pin`, `,保留`)
"""

HELP_TEXT_CLEANUP = """🧹 **清理消息**
**说明**: 在控制群或与助手私聊时，快速清理近期由您和助手发送的消息。
**用法 1**: `,清理消息`
  *默认清理最近的 20 条相关消息。*
**用法 2**: `,清理消息 <数量>`
  *清理指定数量的消息，最大 100 条。*
"""

async def _cmd_retain_message(event, parts):
    """处理 ,保留消息 指令"""
    app = get_application()
    client = app.client

    if not event.is_reply:
        await client.reply_to_admin(event, "❌ **使用方法错误**\n请回复一条您想保留的消息，然后再发送 `,保留消息`。")
        return

    try:
        replied_message = await event.get_reply_message()
        if replied_message.sender_id != client.me.id:
            await client.reply_to_admin(event, "ℹ️ 此指令只能用于保留助手自己发送的消息。")
            return

        await client.cancel_message_deletion_permanently(replied_message)
        
        confirm_msg = await client.reply_to_admin(event, "👌 已永久保留该消息。")
        if confirm_msg:
            await asyncio.sleep(3)
            await confirm_msg.delete()
            await event.message.delete()

    except Exception as e:
        await client.reply_to_admin(event, create_error_reply("保留消息", "操作失败", details=str(e)))


async def _cmd_cleanup_messages(event, parts):
    """处理 ,清理消息 指令"""
    app = get_application()
    client = app.client
    admin_id = int(settings.ADMIN_USER_ID)
    my_id = client.me.id

    limit = 20
    if len(parts) > 1 and parts[1].isdigit():
        limit = min(int(parts[1]), 100)

    messages_to_delete = []
    if event.is_private or event.chat_id == int(settings.CONTROL_GROUP_ID):
        async for message in client.client.iter_messages(event.chat_id, limit=limit * 2):
            if len(messages_to_delete) >= limit:
                break
            if message.sender_id == admin_id or message.sender_id == my_id:
                if (message.chat_id, message.id) not in client._pinned_messages:
                    messages_to_delete.append(message.id)

    if messages_to_delete:
        try:
            await client.client.delete_messages(event.chat_id, messages_to_delete)
            confirm_msg = await client.client.send_message(event.chat_id, f"🧹 已成功清理 {len(messages_to_delete)} 条消息。")
            await asyncio.sleep(3)
            await confirm_msg.delete()
        except Exception as e:
            await client.reply_to_admin(event, create_error_reply("清理消息", "删除时发生错误", details=str(e)))
    else:
        confirm_msg = await client.reply_to_admin(event, "ℹ️ 未找到可清理的消息。")
        if confirm_msg:
            await asyncio.sleep(3)
            await confirm_msg.delete()
    
    await event.message.delete()


def initialize(app):
    app.register_command(
        # [修改] 指令名改为4个字
        name="保留消息",
        handler=_cmd_retain_message,
        help_text="📌 [回复] 使助手的某条消息免于自动删除。",
        category="系统",
        # [修改] 将旧名称加入别名
        aliases=["pin", "保留"],
        usage=HELP_TEXT_RETAIN
    )
    app.register_command(
        # [修改] 指令名改为4个字
        name="清理消息",
        handler=_cmd_cleanup_messages,
        help_text="🧹 快速清理与助手的交互消息。",
        category="系统",
        # [修改] 将旧名称加入别名
        aliases=["cls", "清理"],
        usage=HELP_TEXT_CLEANUP
    )
