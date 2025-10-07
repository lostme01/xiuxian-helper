# -*- coding: utf-8 -*-
import yaml
from config import settings
from app.config_manager import update_nested_setting

RULE_KEYS = {"check_resource", "condition", "action", "item", "amount"}
ACTION_TYPES = {"donate", "exchange"}

def _format_rule_string(rule: dict, index: int) -> str:
    """将规则字典格式化为人类可读的字符串"""
    check_str = f"当 `{rule.get('check_resource', 'N/A')}`"
    condition_str = f"满足 `{rule.get('condition', 'N/A')}` 时"
    action_str = f"自动 `{rule.get('action', 'N/A')}`"
    item_str = f"`{rule.get('item', 'N/A')}` x `{rule.get('amount', 'N/A')}`"
    return f"**{index}.** {check_str} {condition_str}，{action_str} {item_str}"

def _parse_and_validate_rule(rule_str: str) -> tuple[dict | None, str | None]:
    """
    解析并验证单条规则字符串的正确性。
    预期格式: "当 资源 条件, 执行 动作 物品 数量"
    示例: "当 凝血草 >1000, 执行 donate 凝血草 500"
    """
    try:
        # 1. 切分条件与动作
        parts = re.match(r"当\s+(.+?)\s+([<>=!]+.+?),?\s+执行\s+(.+)", rule_str)
        if not parts:
            return None, "格式不匹配，请使用 `当 资源 条件, 执行 动作 物品 数量` 的格式。"
        
        check_resource, condition, action_part = parts.groups()
        
        # 2. 进一步解析动作部分
        action_parts = action_part.strip().split()
        if len(action_parts) < 3:
            return None, "动作部分格式不完整，应为 `动作 物品 数量`。"
            
        action, amount = action_parts[0], action_parts[-1]
        item = " ".join(action_parts[1:-1])

        # 3. 校验各部分内容
        if action not in ACTION_TYPES:
            return None, f"无效的动作 `{action}`，只支持 `donate` 或 `exchange`。"
        
        if not amount.isdigit() or int(amount) <= 0:
            return None, f"数量 `{amount}` 必须是一个正整数。"

        # 4. 组合成规则字典
        rule = {
            "check_resource": check_resource.strip(),
            "condition": f"resource {condition.strip()}",
            "action": action,
            "item": item,
            "amount": int(amount)
        }
        return rule, None
    except Exception as e:
        return None, f"解析时发生未知错误: {e}"

async def logic_get_rules() -> str:
    """获取并格式化所有当前规则"""
    rules = settings.AUTO_RESOURCE_MANAGEMENT.get('rules', [])
    if not rules:
        return "ℹ️ 当前未配置任何智能资源管理规则。"
    
    header = "📄 **当前的智能资源管理规则**:\n\n"
    rule_lines = [_format_rule_string(rule, i + 1) for i, rule in enumerate(rules)]
    
    return header + "\n".join(rule_lines)

async def logic_add_rule(rule_str: str) -> str:
    """添加一条新规则"""
    new_rule, error = _parse_and_validate_rule(rule_str)
    if error:
        return f"❌ **添加失败**\n**原因**: {error}"

    current_rules = settings.AUTO_RESOURCE_MANAGEMENT.get('rules', [])
    current_rules.append(new_rule)
    
    result = await update_nested_setting('auto_resource_management.rules', current_rules)

    if "✅" in result:
        return f"✅ **规则已成功添加**\n\n{_format_rule_string(new_rule, len(current_rules))}"
    else:
        # 如果保存失败，则从内存中移除刚刚添加的规则以保持同步
        settings.AUTO_RESOURCE_MANAGEMENT['rules'].pop()
        return result

async def logic_delete_rule(index_str: str) -> str:
    """根据编号删除一条规则"""
    current_rules = settings.AUTO_RESOURCE_MANAGEMENT.get('rules', [])
    if not current_rules:
        return "ℹ️ 当前没有任何规则可供删除。"
        
    try:
        index = int(index_str)
        if index < 1 or index > len(current_rules):
            return f"❌ **删除失败**: 编号 `{index}` 无效，请输入 `1` 到 `{len(current_rules)}` 之间的数字。"
        
        rule_to_delete = current_rules.pop(index - 1)
        
        result = await update_nested_setting('auto_resource_management.rules', current_rules)

        if "✅" in result:
            return f"✅ **规则已成功删除**\n\n- **已删除**: {_format_rule_string(rule_to_delete, index)}"
        else:
            # 如果保存失败，则将规则重新插回内存以保持同步
            settings.AUTO_RESOURCE_MANAGEMENT['rules'].insert(index - 1, rule_to_delete)
            return result
            
    except ValueError:
        return f"❌ **删除失败**: 请提供一个有效的规则编号数字。"

