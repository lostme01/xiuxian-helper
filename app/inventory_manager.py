# -*- coding: utf-8 -*-
import json
from app.state_manager import get_state, set_state
from app.logger import format_and_log

STATE_KEY_INVENTORY = "inventory"

class InventoryManager:
    def __init__(self):
        self._inventory_cache = None

    async def _load_inventory(self):
        """从状态管理器加载完整库存到内存缓存"""
        if self._inventory_cache is None:
            self._inventory_cache = await get_state(STATE_KEY_INVENTORY, is_json=True, default={})
            format_and_log("SYSTEM", "库存管理器", {'状态': '已从State加载库存到内存'})

    async def get_inventory(self) -> dict:
        """获取当前完整的库存字典"""
        await self._load_inventory()
        return self._inventory_cache.copy()

    async def get_item_count(self, item_name: str) -> int:
        """获取单个物品的数量"""
        await self._load_inventory()
        return self._inventory_cache.get(item_name, 0)

    async def add_item(self, item_name: str, quantity: int):
        """
        增加指定物品的数量，并立即持久化。
        """
        if not isinstance(quantity, int) or quantity <= 0:
            return
        
        await self._load_inventory()
        
        current_quantity = self._inventory_cache.get(item_name, 0)
        new_quantity = current_quantity + quantity
        self._inventory_cache[item_name] = new_quantity
        
        await set_state(STATE_KEY_INVENTORY, self._inventory_cache)
        format_and_log("DEBUG", "库存更新 (增加)", {'物品': item_name, '数量': f'+{quantity}', '当前总量': new_quantity})

    async def remove_item(self, item_name: str, quantity: int):
        """
        减少指定物品的数量，并立即持久化。
        如果物品不存在或数量不足，会记录警告但不会使数量变为负数。
        """
        if not isinstance(quantity, int) or quantity <= 0:
            return
            
        await self._load_inventory()
        
        current_quantity = self._inventory_cache.get(item_name, 0)
        
        if current_quantity < quantity:
            format_and_log("WARNING", "库存更新 (扣减)", {
                '物品': item_name, 
                '问题': '数量不足', 
                '请求扣减': quantity, 
                '实际拥有': current_quantity
            })
            # 数量不足时，为避免数据不一致，将该物品数量清零
            self._inventory_cache.pop(item_name, None)
        else:
            new_quantity = current_quantity - quantity
            if new_quantity > 0:
                self._inventory_cache[item_name] = new_quantity
            else:
                # 如果减完后数量为0，则从库存中移除该物品
                self._inventory_cache.pop(item_name, None)
            
            format_and_log("DEBUG", "库存更新 (减少)", {'物品': item_name, '数量': f'-{quantity}', '剩余': self._inventory_cache.get(item_name, 0)})

        await set_state(STATE_KEY_INVENTORY, self._inventory_cache)

    async def set_inventory(self, full_inventory: dict):
        """
        全量设置库存，用于周期性的校准。
        """
        self._inventory_cache = full_inventory
        await set_state(STATE_KEY_INVENTORY, self._inventory_cache)
        format_and_log("SYSTEM", "库存管理器", {'状态': '已全量更新库存'})

# 创建一个全局单例
inventory_manager = InventoryManager()
