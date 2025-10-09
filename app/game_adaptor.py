# -*- coding: utf-8 -*-
"""
游戏行为适配层 (Game Adaptor)

该模块的目标是将游戏相关的具体指令与插件的核心逻辑解耦。
所有插件都应调用此模块中的函数来执行游戏操作，而不是手动拼接指令字符串。
"""
import re
from config import settings

# --- 角色信息解析 ---
PROFILE_PATTERN = re.compile(
    r"\*\*@([^\*]+)\*\*.*?天命玉牒.*?"
    r"(?:\*\*称号\*\*[:：]?\s*【?([^】\n]+)】?.*?)?"
    r"\*\*宗门\*\*[:：]?\s*[【]?([^】\n]+)[】]?\s*"
    r"\*\*道号\*\*[:：]?\s*([^\n]+)\s*"
    r"\*\*灵根\*\*[:：]?\s*([^\n]+)\s*"
    r"\*\*境界\*\*[:：]?\s*([^\n]+)\s*"
    r"\*\*修为\*\*[:：]?\s*(-?\d+)\s*/\s*(\d+)\s*"
    r"\*\*丹毒\*\*[:：]?\s*(-?\d+)\s*点.*?"
    r"(?:\*\*杀戮\*\*[:：]?\s*(\d+)\s*人.*?)?"
    , re.S | re.I
)

def parse_profile(text: str) -> dict | None:
    """
    从文本中解析角色信息。
    如果解析失败，返回 None。
    """
    match = PROFILE_PATTERN.search(text)
    if not match:
        return None
    
    groups = match.groups()
    
    profile_data = {
        "用户": groups[0], "称号": groups[1], "宗门": groups[2], "道号": groups[3],
        "灵根": groups[4], "境界": groups[5], "修为": int(groups[6]), "修为上限": int(groups[7]),
        "丹毒": int(groups[8]), "杀戮": int(groups[9]) if groups[9] else 0,
    }

    return {k: v.strip() if isinstance(v, str) else v for k, v in profile_data.items() if v is not None}


# --- 交易行为 ---

def list_item(sell_item: str, sell_quantity: int, buy_item: str, buy_quantity: int) -> str:
    """
    生成上架物品的指令。
    """
    sell_str = f"{sell_item}*{sell_quantity}"
    buy_str = f"{buy_item}*{buy_quantity}"
    return f".上架 {sell_str} 换 {buy_str}"

def buy_item(listing_id: str) -> str:
    """
    生成购买物品的指令。
    """
    return f".购买 {listing_id}"

def unlist_item(listing_id: str) -> str:
    """
    生成下架物品的指令。
    """
    return f".下架 {listing_id}"

def get_my_stall() -> str:
    """
    [新增] 生成查询货摊的指令。
    """
    return ".我的货摊"

# --- 炼制与学习行为 ---

def craft_item(item_name: str, quantity: int) -> str:
    """
    生成炼制物品的指令。
    """
    quantity_str = str(quantity) if quantity > 1 else ""
    return f".炼制 {item_name} {quantity_str}".strip()

def get_crafting_list() -> str:
    """
    生成获取可炼制列表的指令 (不带参数的炼制指令)。
    """
    return ".炼制"

def learn_recipe(recipe_name: str) -> str:
    """
    生成学习配方/图纸的指令。
    """
    return f".学习 {recipe_name}"

# --- 角色与宗门行为 ---

def get_inventory() -> str:
    """获取储物袋指令"""
    return ".储物袋"

def meditate() -> str:
    """闭关修炼指令"""
    return ".闭关修炼"

def challenge_tower() -> str:
    """闯塔指令"""
    return ".闯塔"
    
def get_profile() -> str:
    """获取角色信息指令"""
    return ".我的灵根"

def get_formation_info() -> str:
    """获取阵法信息指令"""
    return ".我的阵法"

def get_sect_treasury() -> str:
    """获取宗门宝库指令"""
    return ".宗门宝库"

def sect_check_in() -> str:
    """宗门点卯指令"""
    return ".宗门点卯"

def sect_contribute_skill() -> str:
    """宗门传功指令"""
    return ".宗门传功"

def sect_donate(item_name: str, quantity: int) -> str:
    """宗门捐献指令"""
    return f".宗门捐献 {item_name} {quantity}"

def sect_exchange(item_name: str, quantity: int) -> str:
    """宗门兑换指令"""
    command = f".兑换 {item_name}"
    if quantity > 1:
        command += f" {quantity}"
    return command

# --- 宗门专属：黄枫谷 ---

def huangfeng_garden() -> str:
    """黄枫谷小药园指令"""
    return ".小药园"

def huangfeng_water() -> str:
    """黄枫谷浇水指令"""
    return ".浇水"

def huangfeng_remove_pests() -> str:
    """黄枫谷除虫指令"""
    return ".除虫"

def huangfeng_weed() -> str:
    """黄枫谷除草指令"""
    return ".除草"

def huangfeng_harvest() -> str:
    """黄枫谷采药指令"""
    return ".采药"

# [重构] 适配新版的一键播种指令
def huangfeng_sow(seed_name: str) -> str:
    """黄枫谷一键播种指令"""
    return f".播种 {seed_name}"

# --- 事件行为 ---
def mojun_hide_presence() -> str:
    """魔君降临事件中收敛气息的指令"""
    return ".收敛气息"
