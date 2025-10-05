# -*- coding: utf-8 -*-
import json
from app.context import get_application
from config import settings
from app.config_manager import update_setting, update_nested_setting
from app.utils import create_error_reply

# 定义模型别名与完整名称的映射
MODEL_ALIASES = {
    "pro": "models/gemini-2.5-pro",
    "flash": "models/gemini-2.5-flash",
    "lite": "models/gemini-2.5-flash-lite",
}

HELP_TEXT_AI_CONFIG = """🤖 **AI 功能配置**
**说明**: 统一管理AI答题和聊天功能。
**别名**: `,ai`

**用法**:
  `,ai`
  *查看当前所有AI相关配置的状态。*

  `,ai <开关>`
  *参数: `开` 或 `关` (总开关)*

  `,ai 情感 <开|关>`
  *开启或关闭AI情感系统。*

  `,ai 话题 <开|关>`
  *开启或关闭AI话题记忆系统。*

  `,ai 答题模型 <pro|flash|lite>`
  *设置自动答题使用的模型。*

  `,ai 聊天模型 <pro|flash|lite>`
  *设置AI聊天使用的模型。*

  `,ai 人设`
  *列出所有可用的预设人设。*

  `,ai 人设 <预设名称>`
  *一键切换AI的性格。示例: `,ai 人设 高冷大佬`*

  `,ai 人设 自定义 "<自定义内容>"`
  *设置一个全新的、自定义的人设。*

  `,ai 概率 <0到1的小数>`
  *修改随机闲聊的概率。*

  `,ai 互聊概率 <0到1的小数>`
  *修改助手之间互相回复的概率。*

  `,ai 回复概率 <0到1的小数>`
  *设置AI发言时采用“回复”形式的概率。*

  `,ai 心情 <心情>`
  *手动设置AI当前心情。可用: `高兴`, `平常`, `烦躁`*

  `,ai 查看黑名单`

  `,ai 黑名单添加 <用户ID>`
  
  `,ai 黑名单移除 <用户ID>`
"""

async def _cmd_ai_chatter_config(event, parts):
    client = get_application().client
    app = get_application()
    
    # 状态查询
    if len(parts) == 1:
        cfg = settings.AI_CHATTER_CONFIG
        is_enabled = "✅ 开启" if cfg.get('enabled') else "❌ 关闭"
        mood_enabled = "✅ 开启" if cfg.get('mood_system_enabled') else "❌ 关闭"
        topic_enabled = "✅ 开启" if cfg.get('topic_system_enabled') else "❌ 关闭"
        prob = cfg.get('random_chat_probability', 0.05) * 100
        inter_prob = cfg.get('inter_assistant_reply_probability', 0.3) * 100
        reply_ratio = cfg.get('reply_vs_send_ratio', 0.8) * 100
        blacklist_count = len(cfg.get('blacklist', []))
        
        reverse_aliases = {v: k for k, v in MODEL_ALIASES.items()}
        exam_model_alias = reverse_aliases.get(settings.GEMINI_MODEL_NAME, "未知")
        chat_model_alias = reverse_aliases.get(cfg.get('chat_model_name'), "未知")

        current_mood = "未知 (Redis未连接)"
        if app.redis_db:
            mood_key = await app.redis_db.get("ai_chatter:mood")
            current_mood = {"happy": "😊 高兴", "annoyed": "😠 烦躁"}.get(mood_key, "😐 平常")

        status_text = (
            f"🤖 **AI 功能当前配置**\n\n"
            f"  `答题模型`: **{exam_model_alias}**\n"
            f"  `聊天模型`: **{chat_model_alias}**\n\n"
            f"**----- AI 聊天详细配置 -----**\n"
            f"  `开关`: {is_enabled}\n"
            f"  `情感`: {mood_enabled} (当前: {current_mood})\n"
            f"  `话题`: {topic_enabled}\n"
            f"  `概率`: **{prob:.1f}%**\n"
            f"  `互聊概率`: **{inter_prob:.1f}%**\n"
            f"  `回复概率`: **{reply_ratio:.1f}%**\n"
            f"  `黑名单`: **{blacklist_count}** 人\n"
            f"  `人设`: \n`{cfg.get('personality_prompt', '未设置')}`"
        )
        await client.reply_to_admin(event, status_text)
        return

    sub_command = parts[1]
    
    # 总开关
    if sub_command in ["开", "关"]:
        new_status = (sub_command == "开")
        msg = await update_setting('ai_chatter', 'enabled', new_status, f"AI聊天总开关已 **{sub_command}**")
        if new_status is False:
            msg += "\n*注意: AI聊天功能将在下次重启后完全停止。*"
        await client.reply_to_admin(event, msg)
        return

    # 情感和话题系统开关
    if sub_command in ["情感", "话题"] and len(parts) > 2 and parts[2] in ["开", "关"]:
        new_status = (parts[2] == "开")
        system_map = {"情感": ("mood_system_enabled", "情感系统"), "话题": ("topic_system_enabled", "话题系统")}
        key, name = system_map[sub_command]
        
        msg = await update_nested_setting(f'ai_chatter.{key}', new_status)
        if "✅" in msg:
            await client.reply_to_admin(event, f"✅ **{name}** 已 **{parts[2]}**。")
        else:
            await client.reply_to_admin(event, msg)
        return

    # 模型配置
    if sub_command in ["答题模型", "聊天模型"] and len(parts) > 2:
        alias = parts[2].lower()
        if alias not in MODEL_ALIASES:
            await client.reply_to_admin(event, f"❌ **模型错误**: 无效的模型别名 `{alias}`。可用别名: `pro`, `flash`, `lite`")
            return
            
        full_model_name = MODEL_ALIASES[alias]
        
        if sub_command == "答题模型":
            path = 'exam_solver.gemini_model_name'
        else: # 聊天模型
            path = 'ai_chatter.chat_model_name'
            
        msg = await update_nested_setting(path, full_model_name)
        if "✅" in msg:
            await client.reply_to_admin(event, f"✅ **{sub_command}** 已成功设置为 `{alias}` ({full_model_name})。")
        else:
            await client.reply_to_admin(event, msg)
        return
        
    # 人设指令
    if sub_command == "人设":
        if len(parts) == 2:
            personas_list = [f"- `{name}`" for name in settings.AI_PERSONAS.keys()]
            help_text = ("👤 **可用预设人设列表**\n\n" + "\n".join(personas_list) + 
                         "\n\n**用法:**\n- `,ai 人设 <预设名称>`\n- `,ai 人设 自定义 \"<内容>\"`")
            await client.reply_to_admin(event, help_text)
            return
        if len(parts) > 3 and parts[2] == "自定义":
            new_prompt = " ".join(parts[3:]).strip('"')
            if not new_prompt:
                await client.reply_to_admin(event, "❌ 自定义人设内容不能为空。")
                return
            msg = await update_nested_setting('ai_chatter.personality_prompt', new_prompt)
            await client.reply_to_admin(event, f"✅ AI人设已更新为 **自定义**。\n{msg}")
            return
        if len(parts) == 3:
            persona_name = parts[2]
            if persona_name in settings.AI_PERSONAS:
                new_prompt = settings.AI_PERSONAS[persona_name]
                msg = await update_nested_setting('ai_chatter.personality_prompt', new_prompt)
                await client.reply_to_admin(event, f"✅ AI人设已切换为 **{persona_name}**。\n{msg}")
            else:
                await client.reply_to_admin(event, f"❌ 未找到名为 `{persona_name}` 的预设人设。")
            return
    
    # 概率设置
    if sub_command in ["概率", "互聊概率", "回复概率"] and len(parts) > 2:
        try:
            new_prob = float(parts[2])
            if not 0.0 <= new_prob <= 1.0: raise ValueError
            prob_map = {"概率": "random_chat_probability", "互聊概率": "inter_assistant_reply_probability", "回复概率": "reply_vs_send_ratio"}
            key = prob_map[sub_command]
            msg = await update_nested_setting(f'ai_chatter.{key}', new_prob)
            if "✅" in msg:
                await client.reply_to_admin(event, f"✅ {sub_command}已设为 {new_prob*100:.1f}%。")
            else:
                await client.reply_to_admin(event, msg)
        except ValueError:
            await client.reply_to_admin(event, f"❌ **参数错误**: `{sub_command}` 的值必须是0到1之间的小数，例如 `0.05`。")
        return

    # 手动设置心情
    if sub_command == "心情" and len(parts) > 2:
        mood_map = {"高兴": "happy", "平常": "neutral", "烦躁": "annoyed"}
        mood_input = parts[2]
        if app.redis_db and mood_input in mood_map:
            await app.redis_db.set("ai_chatter:mood", mood_map[mood_input], ex=1800)
            await client.reply_to_admin(event, f"✅ AI 当前心情已手动设置为: **{mood_input}**")
        else:
            await client.reply_to_admin(event, "❌ **设置失败**: 无效的心情或Redis未连接。可用: `高兴`, `平常`, `烦躁`")
        return
        
    # 黑名单管理
    if sub_command == "查看黑名单":
        blacklist = settings.AI_CHATTER_CONFIG.get('blacklist', [])
        if not blacklist:
            await client.reply_to_admin(event, "ℹ️ 当前聊天黑名单为空。")
            return
        blacklist_text = "🚫 **AI 聊天黑名单**\n\n" + "\n".join([f"- `{user_id}`" for user_id in blacklist])
        await client.reply_to_admin(event, blacklist_text)
        return
        
    if sub_command in ["黑名单添加", "黑名单移除"] and (len(parts) > 2 or event.is_reply):
        user_id = None
        try:
            if len(parts) > 2: user_id = int(parts[2])
            elif event.is_reply:
                reply_msg = await event.get_reply_message()
                if reply_msg and reply_msg.sender_id: user_id = reply_msg.sender_id
            if not user_id: raise ValueError("无法获取用户ID")
            blacklist = settings.AI_CHATTER_CONFIG.get('blacklist', []).copy()
            action_text = ""
            if sub_command == "黑名单添加":
                if user_id not in blacklist:
                    blacklist.append(user_id)
                    action_text = "添加"
                else:
                    await client.reply_to_admin(event, f"ℹ️ 用户 `{user_id}` 已在黑名单中。"); return
            elif sub_command == "黑名单移除":
                if user_id in blacklist:
                    blacklist.remove(user_id)
                    action_text = "移除"
                else:
                    await client.reply_to_admin(event, f"❓ 用户 `{user_id}` 不在黑名单中。"); return
            result_msg = await update_nested_setting('ai_chatter.blacklist', blacklist)
            if "✅" in result_msg:
                 await client.reply_to_admin(event, f"✅ 已从黑名单中 **{action_text}** 用户 `{user_id}`。")
            else:
                 await client.reply_to_admin(event, result_msg)
        except (ValueError, TypeError):
            await client.reply_to_admin(event, "❌ **参数错误**: 请提供一个有效的用户ID。")
        return

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
