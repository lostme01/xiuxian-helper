# -*- coding: utf-8 -*-
from abc import ABC, abstractmethod

class BaseGameAdaptor(ABC):
    """
    游戏适配器抽象基类。
    定义了所有游戏适配器必须实现的接口，确保上层插件可以统一调用。
    """

    @abstractmethod
    def parse_profile(self, text: str) -> dict | None:
        """从文本中解析角色信息。"""
        pass

    @abstractmethod
    def list_item(self, sell_item: str, sell_quantity: int, buy_item: str, buy_quantity: int) -> str:
        """生成上架物品的指令。"""
        pass

    @abstractmethod
    def buy_item(self, listing_id: str) -> str:
        """生成购买物品的指令。"""
        pass

    @abstractmethod
    def unlist_item(self, listing_id: str) -> str:
        """生成下架物品的指令。"""
        pass

    @abstractmethod
    def get_my_stall(self) -> str:
        """生成查询货摊的指令。"""
        pass

    @abstractmethod
    def craft_item(self, item_name: str, quantity: int) -> str:
        """生成炼制物品的指令。"""
        pass
    
    @abstractmethod
    def get_crafting_list(self) -> str:
        """生成获取可炼制列表的指令。"""
        pass

    @abstractmethod
    def learn_recipe(self, recipe_name: str) -> str:
        """生成学习配方的指令。"""
        pass
        
    @abstractmethod
    def get_inventory(self) -> str:
        """获取储物袋指令。"""
        pass

    @abstractmethod
    def meditate(self) -> str:
        """闭关修炼指令。"""
        pass

    @abstractmethod
    def challenge_tower(self) -> str:
        """闯塔指令。"""
        pass

    @abstractmethod
    def get_profile(self) -> str:
        """获取角色信息指令。"""
        pass

    @abstractmethod
    def get_formation_info(self) -> str:
        """获取阵法信息指令。"""
        pass

    @abstractmethod
    def get_sect_treasury(self) -> str:
        """获取宗门宝库指令。"""
        pass

    @abstractmethod
    def sect_check_in(self) -> str:
        """宗门点卯指令。"""
        pass

    @abstractmethod
    def sect_contribute_skill(self) -> str:
        """宗门传功指令。"""
        pass

    @abstractmethod
    def sect_donate(self, item_name: str, quantity: int) -> str:
        """宗门捐献指令。"""
        pass

    @abstractmethod
    def sect_exchange(self, item_name: str, quantity: int) -> str:
        """宗门兑换指令。"""
        pass

    # --- 宗门专属 ---
    @abstractmethod
    def huangfeng_garden(self) -> str:
        pass
        
    @abstractmethod
    def huangfeng_water(self) -> str:
        pass
        
    @abstractmethod
    def huangfeng_remove_pests(self) -> str:
        pass
        
    @abstractmethod
    def huangfeng_weed(self) -> str:
        pass
        
    @abstractmethod
    def huangfeng_harvest(self) -> str:
        pass
        
    @abstractmethod
    def huangfeng_sow(self, seed_name: str) -> str:
        pass

    # --- 事件行为 ---
    @abstractmethod
    def mojun_hide_presence(self) -> str:
        pass
