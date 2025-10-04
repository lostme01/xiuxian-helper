# -*- coding: utf-8 -*-
from app.context import get_application
from app.state_manager import get_state
from app.inventory_manager import inventory_manager
from app.character_stats_manager import stats_manager
from app.plugins.character_info import _format_profile_reply
from app.plugins.sect_treasury import _cmd_view_cached_treasury as view_treasury
from app.plugins.data_management import _cmd_view_inventory as view_inventory
from app.plugins.formation_info import _cmd_view_cached_formation as view_formation
from app.utils import create_error_reply

HELP_TEXT_STATUS = """📊 **统一状态查询**
**说明**: 融合了多个查询指令，提供一站式状态概览。
**用法 1 (总览)**: `,状态`
  *显示角色核心信息摘要。*
**用法 2 (分项查询)**: `,状态 <模块>`
  *模块可选: `背包`, `宝库`, `角色`, `阵法`*
**示例**: `,状态 背包`
"""

async def _cmd_status(event, parts):
    app = get_application()
    
    if len(parts) == 1:
        # 显示总览
        profile_data = await get_state("character_profile", is_json=True)
        contribution = await stats_manager.get_contribution()
        ling_shi_count = await inventory_manager.get_item_count("灵石")
        
        if not profile_data:
            await app.client.reply_to_admin(event, "ℹ️ 尚未缓存任何角色信息，无法生成总览。请先使用 `,我的灵根` 查询一次。")
            return
            
        summary = (
            f"📊 **状态总览**\n"
            f"-----------------\n"
            f"- **道号**: `{profile_data.get('道号', '未知')}`\n"
            f"- **境界**: `{profile_data.get('境界', '未知')}`\n"
            f"- **修为**: `{profile_data.get('当前修为', 'N/A')} / {profile_data.get('修为上限', 'N/A')}`\n"
            f"- **灵石**: `{ling_shi_count}`\n"
            f"- **贡献**: `{contribution}`\n\n"
            f"使用 `,状态 <模块>` 查看更多详情。"
        )
        await app.client.reply_to_admin(event, summary)
        
    elif len(parts) == 2:
        sub_command = parts[1]
        if sub_command == "背包":
            await view_inventory(event, parts)
        elif sub_command == "宝库":
            await view_treasury(event, parts)
        elif sub_command == "角色":
            profile_data = await get_state("character_profile", is_json=True)
            if not profile_data:
                await app.client.reply_to_admin(event, "ℹ️ 尚未缓存任何角色信息。请先使用 `,我的灵根` 查询。")
                return
            reply_text = _format_profile_reply(profile_data, "📄 **已缓存的角色信息**:")
            await app.client.reply_to_admin(event, reply_text)
        elif sub_command == "阵法":
            await view_formation(event, parts)
        else:
            error_msg = create_error_reply("状态", "未知的模块", details=f"可用模块: 背包, 宝库, 角色, 阵法", usage_text=HELP_TEXT_STATUS)
            await app.client.reply_to_admin(event, error_msg)
    else:
        await app.client.reply_to_admin(event, HELP_TEXT_STATUS)

def initialize(app):
    app.register_command(
        name="状态",
        handler=_cmd_status,
        help_text="📊 统一的状态查询入口。",
        category="数据查询",
        usage=HELP_TEXT_STATUS
    )
