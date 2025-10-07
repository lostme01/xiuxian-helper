# -*- coding: utf-8 -*-
import re
from app.context import get_application
from app.utils import require_args
from .logic import resource_logic

HELP_TEXT_MANAGE_RULES = """🔧 **智能资源规则管理**
**说明**: 动态管理自动化的资源捐献/兑换策略。

**1. 查看规则**:
   `,查看规则`

**2. 添加规则**:
   `,添加规则 当 <资源> <条件>, 执行 <动作> <物品> <数量>`
   - **资源**: `contribution` 或物品名 (如 `凝血草`)
   - **条件**: `>1000`, `<50` 等
   - **动作**: `donate` (捐献) 或 `exchange` (兑换)
   
   *示例*: `,添加规则 当 贡献 >20000, 执行 exchange 凝血草种子 10`

**3. 删除规则**:
   `,删除规则 <编号>`
   *示例*: `,删除规则 1`
"""

async def _cmd_view_rules(event, parts):
    """处理 ,查看规则 指令"""
    app = get_application()
    result = await resource_logic.logic_get_rules()
    await app.client.reply_to_admin(event, result)

@require_args(count=2, usage=HELP_TEXT_MANAGE_RULES)
async def _cmd_add_rule(event, parts):
    """处理 ,添加规则 指令"""
    app = get_application()
    # 将 "当" 之后的所有部分合并为一个字符串
    rule_str = " ".join(parts[1:])
    # 确保 "当" 这个关键字在字符串的开头
    if not rule_str.strip().lower().startswith('当'):
        rule_str = f"当 {rule_str}"
        
    result = await resource_logic.logic_add_rule(rule_str)
    await app.client.reply_to_admin(event, result)

@require_args(count=2, usage=HELP_TEXT_MANAGE_RULES)
async def _cmd_delete_rule(event, parts):
    """处理 ,删除规则 指令"""
    app = get_application()
    result = await resource_logic.logic_delete_rule(parts[1])
    await app.client.reply_to_admin(event, result)

def initialize(app):
    app.register_command(
        name="查看规则",
        handler=_cmd_view_rules,
        help_text="📄 查看所有智能资源管理规则。",
        category="系统",
        usage=HELP_TEXT_MANAGE_RULES
    )
    app.register_command(
        name="添加规则",
        handler=_cmd_add_rule,
        help_text="➕ 添加一条智能资源管理规则。",
        category="系统",
        usage=HELP_TEXT_MANAGE_RULES
    )
    app.register_command(
        name="删除规则",
        handler=_cmd_delete_rule,
        help_text="➖ 删除一条智能资源管理规则。",
        category="系统",
        usage=HELP_TEXT_MANAGE_RULES
    )
