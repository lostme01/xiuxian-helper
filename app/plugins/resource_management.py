# -*- coding: utf-8 -*-
import re
from app.context import get_application
from app.utils import require_args
from .logic import resource_logic

HELP_TEXT_MANAGE_RULES = """🔧 **智能资源规则 (v2.0)**
**说明**: 通过简单指令，自动化管理资源捐献/兑换策略。

**1. 查看规则**:
   `,管理规则 查看`

**2. 添加捐献规则 (推荐)**:
   `,管理规则 捐献 <物品> 保留 <数量>`
   *示例: `,管理规则 捐献 凝血草 保留 1000`*
   *效果: 当凝血草超过1000个时，自动捐献所有多余的部分。*

**3. 添加兑换规则**:
   `,管理规则 兑换 <物品> <数量> 当 <资源> <操作符> <阈值>`
   *示例: `,管理规则 兑换 凝血草种子 10 当 贡献 > 20000`*
   *资源: `贡献` 或 物品名 (如 `凝血草`)*
   *操作符: `>` `<` `>=` `<=` `==` `!=`*

**4. 删除规则**:
   `,管理规则 删除 <编号>`
   *示例: `,管理规则 删除 1`*
"""

async def _cmd_manage_rules(event, parts):
    """
    [新] 统一的规则管理指令处理器
    """
    app = get_application()
    client = app.client
    
    if len(parts) < 2:
        await client.reply_to_admin(event, HELP_TEXT_MANAGE_RULES)
        return

    sub_command = parts[1]
    result = ""

    if sub_command in ["查看", "列表"]:
        result = await resource_logic.logic_get_rules()
    elif sub_command in ["添加", "捐献", "兑换"]:
        result = await resource_logic.logic_add_rule(parts)
    elif sub_command == "删除":
        if len(parts) < 3:
            result = "❌ **删除失败**: 请提供要删除的规则编号。"
        else:
            result = await resource_logic.logic_delete_rule(parts[2])
    else:
        result = f"❓ 未知的子命令: `{sub_command}`\n\n{HELP_TEXT_MANAGE_RULES}"

    await client.reply_to_admin(event, result)


def initialize(app):
    app.register_command(
        name="管理规则",
        handler=_cmd_manage_rules,
        help_text="🔧 (新) 管理智能资源规则。",
        category="系统",
        aliases=["规则", "查看规则", "添加规则", "删除规则"], # 保留旧指令为别名
        usage=HELP_TEXT_MANAGE_RULES
    )
