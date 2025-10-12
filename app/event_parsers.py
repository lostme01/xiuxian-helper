# -*- coding: utf-8 -*-
import re
import logging
from app.logging_service import LogType, format_and_log

# --- 多策略解析器 ---

def _parse_items_from_text(text: str) -> dict:
    """
    一个健壮的物品解析器，采用多种策略从文本中提取 "【物品】x数量" 的信息。
    """
    gained_items = {}
    
    # 策略1: 严格正则匹配 (最常见、最高效)
    # 匹配：【物品名】x123 or 【物品名】x1,234
    strict_pattern = r"【(.+?)】x([\d,]+)"
    matches = re.findall(strict_pattern, text)
    if matches:
        for item, quantity_str in matches:
            gained_items[item] = int(quantity_str.replace(',', ''))
        return gained_items

    # 策略2: 宽松正则匹配 (兼容可能的格式变化)
    # 匹配：物品名 x 123
    loose_pattern = r"([^\s【】]+?)\s*x\s*(\d+)"
    matches = re.findall(loose_pattern, text)
    if matches:
        for item, quantity_str in matches:
            # 过滤掉一些可能的误判，例如 "ID: 123"
            if item.endswith(':'): continue
            gained_items[item] = int(quantity_str)
        return gained_items
        
    return gained_items

# --- “域内解析” 函数 ---

def parse_tower_challenge(text: str) -> dict | None:
    """解析“闯塔”事件"""
    gained_items = _parse_items_from_text(text)
    if gained_items:
        return {"event_type": "TOWER_CHALLENGE_COMPLETED", "gained_items": gained_items}
    return None

def parse_trade_completed(text: str) -> dict | None:
    """解析“交易”事件"""
    gained_items, sold_items = {}, {}
    gained_match = re.search(r"你获得了：\s*(.*)", text, re.DOTALL)
    if gained_match:
        gained_items = _parse_items_from_text(gained_match.group(1))
        
    sold_match = re.search(r"你成功出售了【(.+?)】x([\d,]+)", text)
    if sold_match:
        sold_items[sold_match.group(1)] = int(sold_match.group(2).replace(',', ''))
        
    if gained_items or sold_items:
        return {"event_type": "TRADE_COMPLETED", "gained": gained_items, "sold": sold_items}
    return None

def parse_crafting_completed(text: str, original_message_text: str = None) -> dict | None:
    """解析“炼制”事件"""
    gained_items = {item: int(q.replace(',', '')) for item, q in
                    re.findall(r"最终获得【(.+?)】x\*\*([\d,]+)\*\*", text)}
    if gained_items and original_message_text:
        command_parts = original_message_text.split()
        crafted_quantity = 1
        if len(command_parts) > 2 and command_parts[-1].isdigit():
            crafted_quantity = int(command_parts[-1])
        return {
            "event_type": "CRAFTING_COMPLETED",
            "crafted_item": {"name": next(iter(gained_items)), "quantity": crafted_quantity},
            "gained_items": gained_items
        }
    return None

def parse_donation_completed(text: str) -> dict | None:
    """解析“宗门捐献”事件"""
    consumed_match = re.search(r"捐献了 \*\*【(.+?)】\*\*x([\d,]+)", text)
    contrib_match = re.search(r"获得了 \*\*([\d,]+)\*\* 点宗门贡献", text)
    if consumed_match and contrib_match:
        return {
            "event_type": "DONATION_COMPLETED",
            "consumed_item": {consumed_match.group(1): int(consumed_match.group(2).replace(',', ''))},
            "gained_contribution": int(contrib_match.group(1).replace(',', ''))
        }
    return None

def parse_exchange_completed(text: str) -> dict | None:
    """解析“宗门兑换”事件"""
    gain_match = re.search(r"获得了【(.+?)】x([\d,]+)", text)
    cost_match = re.search(r"消耗了 \*\*([\d,]+)\*\* 点贡献", text)
    if gain_match and cost_match:
        return {
            "event_type": "EXCHANGE_COMPLETED",
            "gained_item": {gain_match.group(1): int(gain_match.group(2).replace(',', ''))},
            "consumed_contribution": int(cost_match.group(1).replace(',', ''))
        }
    return None

def parse_delist_completed(text: str) -> dict | None:
    """解析“下架”事件"""
    match = re.search(r"你已成功将 \*\*【(.+?)】\*\*x([\d,]+)", text)
    if match:
        item_name = match.group(1)
        quantity = int(match.group(2).replace(',', ''))
        return {
            "event_type": "DELIST_COMPLETED",
            "gained_items": {item_name: quantity}
        }
    return None

# --- “指纹识别”与调度中心 ---

# 定义事件指纹及其对应的解析函数
EVENT_FINGERPRINTS = [
    # 指纹越独特，越应该放在前面
    ({"【试炼古塔 - 战报】", "总收获"}, parse_tower_challenge),
    ({"【万宝楼快报】"}, parse_trade_completed),
    ({"炼制结束！", "最终获得"}, parse_crafting_completed),
    ({"**兑换成功！**", "消耗了"}, parse_exchange_completed),
    # 对于下架，需要结合原始指令判断，所以放在handler里特殊处理
    # ({"从万宝楼下架"}, parse_delist_completed),
    ({"你向宗门捐献了", "获得了"}, parse_donation_completed),
]

def dispatch_and_parse(text: str, original_message_text: str = None) -> dict | None:
    """
    主调度函数：接收消息文本，进行指纹识别，并调用相应的解析器。
    """
    for keywords, parser_func in EVENT_FINGERPRINTS:
        if all(keyword in text for keyword in keywords):
            try:
                # 传递原始指令文本给需要它的解析器
                if parser_func is parse_crafting_completed:
                    return parser_func(text, original_message_text=original_message_text)
                else:
                    return parser_func(text)
            except Exception as e:
                format_and_log(
                    LogType.ERROR, "域内解析失败", 
                    {'事件': parser_func.__name__, '错误': str(e), '文本': text}, 
                    level=logging.WARNING
                )
                return None
    return None
