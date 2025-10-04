# -*- coding: utf-8 -*-
import json
from app.context import get_application
from config import settings
from app.config_manager import _load_config, _save_config, update_setting
from app.utils import create_error_reply

HELP_TEXT_AI_CONFIG = """🤖 **AI 聊天一级配置**
**说明**: 统一管理AI聊天功能的所有参数。
**别名**: `,ai`

**用法**:
  `,AI聊天配置`
  *查看当前所有AI聊天配置的状态。*

  `,AI聊天配置 <开关>`
  *参数: `开` 或 `关`*

  `,AI聊天配置 人设 <新的人设描述>`
  *示例: `,ai 人设 你是一个高冷的大佬`*

  `,AI聊天配置 概率 <0到1的小数>`
  *示例: `,ai 概率 0.03` (即3%的概率)*

  `,AI聊天配置 查看黑名单`
  *列出所有在黑名单中的用户ID。*

  `,AI聊天配置 黑名单添加 <用户ID>`
  *回复某人消息时使用 `,ai 黑名单添加` 可自动添加。*
  
  `,AI聊天配置 黑名单移除 <用户ID>`
"""

async def _cmd_ai_chatter_config(event, parts):
    client = get_application().client
    
    # 显示当前状态
    if len(parts) == 1:
        cfg = settings.AI_CHATTER_CONFIG
        is_enabled = "✅ 开启" if cfg.get('enabled') else "❌ 关闭"
        prob = cfg.get('random_chat_probability', 0.05) * 100
        blacklist_count = len(cfg.get('blacklist', []))
        
        status_text = (
            f"🤖 **AI 聊天当前配置**\n\n"
            f"- **总开关**: {is_enabled}\n"
            f"- **随机聊天概率**: `{prob:.1f}%`\n"
            f"- **黑名单数量**: `{blacklist_count}` 人\n"
            f"- **当前人设**: \n`{cfg.get('personality_prompt', '未设置')}`"
        )
        await client.reply_to_admin(event, status_text)
        return

    sub_command = parts[1]
    
    # 开关
    if sub_command in ["开", "关"]:
        new_status = (sub_command == "开")
        # 注意：关闭后，需要重启才能完全停止监听
        msg = update_setting('ai_chatter', 'enabled', new_status, f"AI聊天功能已 **{sub_command}**")
        if new_status is False:
            msg += "\n*注意: AI聊天功能将在下次重启后完全停止。*"
        await client.reply_to_admin(event, msg)
        return

    # 人设
    if sub_command == "人设" and len(parts) > 2:
        new_prompt = " ".join(parts[2:])
        msg = update_setting('ai_chatter', 'personality_prompt', new_prompt, "AI人设已更新")
        await client.reply_to_admin(event, msg)
        return
        
    # 概率
    if sub_command == "概率" and len(parts) > 2:
        try:
            new_prob = float(parts[2])
            if not 0.0 <= new_prob <= 1.0:
                raise ValueError
            msg = update_setting('ai_chatter', 'random_chat_probability', new_prob, f"AI随机聊天概率已设为 {new_prob*100:.1f}%")
            await client.reply_to_admin(event, msg)
        except ValueError:
            await client.reply_to_admin(event, "❌ **参数错误**: 概率必须是0到1之间的小数，例如 `0.05`。")
        return

    # 查看黑名单
    if sub_command == "查看黑名单":
        blacklist = settings.AI_CHATTER_CONFIG.get('blacklist', [])
        if not blacklist:
            await client.reply_to_admin(event, "ℹ️ 当前聊天黑名单为空。")
            return
        
        blacklist_text = "🚫 **AI 聊天黑名单**\n\n" + "\n".join([f"- `{user_id}`" for user_id in blacklist])
        await client.reply_to_admin(event, blacklist_text)
        return
        
    # 添加/移除黑名单
    if sub_command in ["黑名单添加", "黑名单移除"] and (len(parts) > 2 or event.is_reply):
        user_id = None
        try:
            if len(parts) > 2:
                user_id = int(parts[2])
            elif event.is_reply:
                reply_msg = await event.get_reply_message()
                if reply_msg and reply_msg.sender_id:
                    user_id = reply_msg.sender_id
            
            if not user_id:
                raise ValueError("无法获取用户ID")

            # --- [核心] 动态修改配置文件中的列表 ---
            full_config = _load_config()
            ai_chatter_config = full_config.setdefault('ai_chatter', {})
            blacklist = ai_chatter_config.setdefault('blacklist', [])
            
            action_text = ""
            if sub_command == "黑名单添加":
                if user_id not in blacklist:
                    blacklist.append(user_id)
                    action_text = "添加"
                else:
                    await client.reply_to_admin(event, f"ℹ️ 用户 `{user_id}` 已在黑名单中。")
                    return
            
            elif sub_command == "黑名单移除":
                if user_id in blacklist:
                    blacklist.remove(user_id)
                    action_text = "移除"
                else:
                    await client.reply_to_admin(event, f"❓ 用户 `{user_id}` 不在黑名单中。")
                    return
            
            if _save_config(full_config):
                # 同步更新内存中的配置
                settings.AI_CHATTER_CONFIG['blacklist'] = blacklist
                await client.reply_to_admin(event, f"✅ 已从黑名单中 **{action_text}** 用户 `{user_id}`。")
            else:
                await client.reply_to_admin(event, "❌ **操作失败**: 写入配置文件时发生错误。")

        except (ValueError, TypeError):
            await client.reply_to_admin(event, "❌ **参数错误**: 请提供一个有效的用户ID。")
        return

    # 如果以上都不是，显示帮助
    await client.reply_to_admin(event, create_error_reply("AI聊天配置", "未知的子命令或参数错误", usage_text=HELP_TEXT_AI_CONFIG))


def initialize(app):
    app.register_command(
        name="AI聊天配置",
        handler=_cmd_ai_chatter_config,
        help_text="🤖 统一管理AI聊天功能。",
        category="系统",
        aliases=["ai"],
        usage=HELP_TEXT_AI_CONFIG
    )
