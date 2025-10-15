# -*- coding: utf-8 -*-
import yaml
import re
from config import settings
from app.config_manager import update_nested_setting

RULE_KEYS = {"check_resource", "condition", "action", "item", "amount"}
ACTION_TYPES = {"donate", "exchange"}

def _format_rule_string(rule: dict, index: int) -> str:
    """将规则字典格式化为人类可读的字符串"""
    check_str = f"当 `{rule.get('check_resource', 'N/A')}`"
    condition_str = f"满足 `{rule.get('condition', 'N/A')}` 时"
    action_str = f"自动 `{rule.get('action', 'N/A')}`"
    
    if rule.get('dynamic_amount'):
        item_str = f"`{rule.get('item', 'N/A')}` (超出 `{rule.get('threshold')}` 的部分)"
    else:
        item_str = f"`{rule.get('item', 'N/A')}` x `{rule.get('amount', 'N/A')}`"
        
    return f"**{index}.** {check_str} {condition_str}，{action_str} {item_str}"

def _parse_simplified_rule(parts: list) -> tuple[dict | None, str | None]:
    """
    [新功能] 解析简化版的规则指令
    """
    if len(parts) < 2:
        return None, "指令不完整。"
    
    action = parts[1]

    # 模式一: ,规则 捐献 <物品> 保留 <数量>
    if action == "捐献" and "保留" in parts:
        try:
            preserve_index = parts.index("保留")
            item_name = " ".join(parts[2:preserve_index])
            threshold_str = parts[preserve_index + 1]
            
            if not item_name or not threshold_str.isdigit():
                return None, "捐献指令格式错误。"
            
            threshold = int(threshold_str)
            rule = {
                "check_resource": item_name,
                "condition": f"resource > {threshold}",
                "action": "donate",
                "item": item_name,
                "amount": 0,  # 占位符，实际由 dynamic_amount 控制
                "dynamic_amount": f"resource - {threshold}",
                "threshold": threshold # 用于显示
            }
            return rule, None
        except (ValueError, IndexError):
            return None, "捐献指令格式错误。"

    # 模式二: ,规则 兑换 <物品> <数量> 当 <资源> <条件> <阈值>
    elif action == "兑换" and "当" in parts:
        try:
            when_index = parts.index("当")
            item_name = " ".join(parts[2:when_index-1])
            amount_str = parts[when_index-1]
            
            condition_parts = parts[when_index+1:]
            if len(condition_parts) != 3 or not amount_str.isdigit():
                 return None, "兑换指令格式错误。"

            check_resource = condition_parts[0]
            operator = condition_parts[1]
            threshold_str = condition_parts[2]

            if operator not in ['>', '<', '>=', '<=', '==', '!='] or not threshold_str.isdigit():
                return None, "兑换指令的条件部分格式错误。"

            rule = {
                "check_resource": check_resource,
                "condition": f"resource {operator} {threshold_str}",
                "action": "exchange",
                "item": item_name,
                "amount": int(amount_str)
            }
            return rule, None
        except (ValueError, IndexError):
            return None, "兑换指令格式错误。"

    return None, "无法识别的规则格式。"

async def logic_get_rules() -> str:
    """获取并格式化所有当前规则"""
    rules = settings.AUTO_RESOURCE_MANAGEMENT.get('rules', [])
    if not rules:
        return "ℹ️ 当前未配置任何智能资源管理规则。"
    
    header = "📄 **当前的智能资源管理规则**:\n\n"
    rule_lines = [_format_rule_string(rule, i + 1) for i, rule in enumerate(rules)]
    
    return header + "\n".join(rule_lines)

async def logic_add_rule(parts: list) -> str:
    """添加一条新规则（简化版）"""
    new_rule, error = _parse_simplified_rule(parts)
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
