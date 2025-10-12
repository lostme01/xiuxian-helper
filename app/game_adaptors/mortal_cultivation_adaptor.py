# -*- coding: utf-8 -*-
import re
from .base_adaptor import BaseGameAdaptor

class MortalCultivationAdaptor(BaseGameAdaptor):
    """
    针对当前修仙游戏的具体适配器实现。
    """
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

    def divination(self) -> str:
        return ".卜筮问天"

    def parse_profile(self, text: str) -> dict | None:
        match = self.PROFILE_PATTERN.search(text)
        if not match:
            return None
        
        groups = match.groups()
        
        profile_data = {
            "用户": groups[0], "称号": groups[1], "宗门": groups[2], "道号": groups[3],
            "灵根": groups[4], "境界": groups[5], "修为": int(groups[6]), "修为上限": int(groups[7]),
            "丹毒": int(groups[8]), "杀戮": int(groups[9]) if groups[9] else 0,
        }

        return {k: v.strip() if isinstance(v, str) else v for k, v in profile_data.items() if v is not None}

    def list_item(self, sell_item: str, sell_quantity: int, buy_item: str, buy_quantity: int) -> str:
        sell_str = f"{sell_item}*{sell_quantity}"
        buy_str = f"{buy_item}*{buy_quantity}"
        return f".上架 {sell_str} 换 {buy_str}"

    def buy_item(self, listing_id: str) -> str:
        return f".购买 {listing_id}"

    def unlist_item(self, listing_id: str) -> str:
        return f".下架 {listing_id}"

    def get_my_stall(self) -> str:
        return ".我的货摊"

    def craft_item(self, item_name: str, quantity: int) -> str:
        quantity_str = str(quantity) if quantity > 1 else ""
        return f".炼制 {item_name} {quantity_str}".strip()

    def get_crafting_list(self) -> str:
        return ".炼制"

    def learn_recipe(self, recipe_name: str) -> str:
        return f".学习 {recipe_name}"

    def get_inventory(self) -> str:
        return ".储物袋"

    def meditate(self) -> str:
        return ".闭关修炼"

    def challenge_tower(self) -> str:
        return ".闯塔"
    
    def get_profile(self) -> str:
        return ".我的灵根"

    def get_formation_info(self) -> str:
        return ".我的阵法"

    def get_sect_treasury(self) -> str:
        return ".宗门宝库"

    def sect_check_in(self) -> str:
        return ".宗门点卯"

    def sect_contribute_skill(self) -> str:
        return ".宗门传功"

    def sect_donate(self, item_name: str, quantity: int) -> str:
        return f".宗门捐献 {item_name} {quantity}"

    def sect_exchange(self, item_name: str, quantity: int) -> str:
        command = f".兑换 {item_name}"
        if quantity > 1:
            command += f" {quantity}"
        return command

    def huangfeng_garden(self) -> str:
        return ".小药园"

    def huangfeng_water(self) -> str:
        return ".浇水"

    def huangfeng_remove_pests(self) -> str:
        return ".除虫"

    def huangfeng_weed(self) -> str:
        return ".除草"

    def huangfeng_harvest(self) -> str:
        return ".采药"

    def huangfeng_sow(self, seed_name: str) -> str:
        return f".播种 {seed_name}"

    def mojun_hide_presence(self) -> str:
        return ".收敛气息"
