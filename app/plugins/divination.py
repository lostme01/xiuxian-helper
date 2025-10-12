# -*- coding: utf-8 -*-
import re
import asyncio
from app import game_adaptor
from app.context import get_application
from app.telegram_client import CommandTimeoutError
from app.utils import create_error_reply, progress_manager

HELP_TEXT_DIVINATION = """☯️ **卜筮问天**
**说明**: 消耗修为，窥探今日机缘，可能会有意外的收获或损失。
**用法**: `,卜筮问天` (或 `,卜筮`)
"""

def _parse_divination_result(text: str) -> str:
    """从最终的卦象文本中解析出核心信息并格式化"""
    
    # 匹配卦象类型，例如【卦象：吉】
    gua_match = re.search(r"【卦象：([^】]+)】", text)
    gua_type = gua_match.group(1) if gua_match else "未知"
    
    # 预设一个默认的简洁描述
    description = text.split('\n')[-1]

    if "天降横财" in text:
        match = re.search(r"获得了 \*\*(\d+)\*\* 块灵石", text)
        if match:
            description = f"天降横财，获得 **{match.group(1)}** 灵石！"
    elif "道心通明" in text:
        match = re.search(r"修为止增加了 \*\*(\d+)\*\* 点", text)
        if match:
            description = f"道心通明，修为增加 **{match.group(1)}** 点！"
    elif "金玉满堂" in text:
        match = re.search(r"捡到了 \*\*(\d+)\*\* 块灵石", text)
        if match:
            description = f"金玉满堂，捡到 **{match.group(1)}** 灵石！"
    elif "小有破财" in text:
        match = re.search(r"遗失了 \*\*(\d+)\*\* 块灵石", text)
        if match:
            description = f"小有破财，遗失 **{match.group(1)}** 灵石..."
    elif "古井无波" in text:
        description = "古井无波，心如止水。"

    icon_map = {"大吉": "🎉", "吉": "吉", "平": "平", "凶": "凶"}
    icon = icon_map.get(gua_type, "❓")
    
    return f"**{icon} {gua_type}**: {description}"


async def _cmd_divination(event, parts):
    """处理用户指令，执行卜筮问天功能"""
    app = get_application()
    client = app.client
    
    async with progress_manager(event, "⏳ 正在消耗修为，转动天机罗盘...") as progress:
        final_text = ""
        try:
            # 使用健壮的 send_and_wait_for_edit 等待最终结果
            _sent, final_reply = await client.send_and_wait_for_edit(
                command=game_adaptor.divination(),
                initial_pattern="开始转动天机罗盘",
                final_pattern="【卦象："
            )
            
            # 解析并格式化结果
            parsed_result = _parse_divination_result(final_reply.text)
            final_text = f"**卜筮结果**\n{parsed_result}"

        except CommandTimeoutError:
            final_text = create_error_reply("卜筮问天", "游戏机器人响应超时", details="未能等到初始回复或最终结果。")
        except Exception as e:
            final_text = create_error_reply("卜筮问天", "执行时发生未知异常", details=str(e))
        
        # 将最终结果更新到交互消息中
        await progress.update(final_text)


def initialize(app):
    """注册指令到应用"""
    app.register_command(
        name="卜筮问天",
        handler=_cmd_divination,
        help_text="☯️ 消耗修为，窥探今日机缘。",
        category="动作",
        aliases=["卜筮"],
        usage=HELP_TEXT_DIVINATION
    )
