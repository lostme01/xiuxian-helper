# -*- coding: utf-8 -*-
import json
import asyncio
from app.state_manager import get_state, set_state
from app.logger import format_and_log

STATE_KEY_INVENTORY = "inventory"

class InventoryManager:
    def __init__(self):
        self._inventory_cache = None
        self._lock = asyncio.Lock()

    async def _load_inventory(self):
        """
        [已修复] 从状态管理器加载完整库存到内存缓存。
        此内部函数不应再获取锁，因为它总是被已获取锁的公共函数调用。
        """
        if self._inventory_cache is None:
            # 移除了此处的 async with self._lock，因为它会导致死锁
            self._inventory_cache = await get_state(STATE_KEY_INVENTORY, is_json=True, default={})
            format_and_log("SYSTEM", "库存管理器", {'状态': '已从State加载库存到内存'})

    async def get_inventory(self) -> dict:
        """获取当前完整的库存字典"""
        async with self._lock:
            await self._load_inventory()
            return self._inventory_cache.copy()

    async def get_item_count(self, item_name: str) -> int:
        """获取单个物品的数量"""
        async with self._lock:
            await self._load_inventory()
            return self._inventory_cache.get(item_name, 0)

    async def add_item(self, item_name: str, quantity: int):
        """
        [优化版] 增加指定物品的数量，并立即持久化 (线程安全)。
        """
        if not isinstance(quantity, int) or quantity <= 0:
            return
        
        async with self._lock:
            await self._load_inventory()
            
            current_quantity = self._inventory_cache.get(item_name, 0)
            new_quantity = current_quantity + quantity
            self._inventory_cache[item_name] = new_quantity
            
            await set_state(STATE_KEY_INVENTORY, self._inventory_cache)
            format_and_log("DEBUG", "库存更新 (增加)", {'物品': item_name, '数量': f'+{quantity}', '当前总量': new_quantity})

    async def remove_item(self, item_name: str, quantity: int):
        """
        [优化版] 减少指定物品的数量，并立即持久化 (线程安全)。
        """
        if not isinstance(quantity, int) or quantity <= 0:
            return
            
        async with self._lock:
            await self._load_inventory()
            
            current_quantity = self._inventory_cache.get(item_name, 0)
            
            if current_quantity < quantity:
                format_and_log("WARNING", "库存更新 (扣减)", {
                    '物品': item_name, 
                    '问题': '数量不足', 
                    '请求扣减': quantity, 
                    '实际拥有': current_quantity
                })
                # [修复] 即使数量不足，也应该扣除所有，以匹配游戏逻辑
                self._inventory_cache.pop(item_name, None)
            else:
                new_quantity = current_quantity - quantity
                if new_quantity > 0:
                    self._inventory_cache[item_name] = new_quantity
                else:
                    self._inventory_cache.pop(item_name, None)
                
                format_and_log("DEBUG", "库存更新 (减少)", {'物品': item_name, '数量': f'-{quantity}', '剩余': self._inventory_cache.get(item_name, 0)})

            await set_state(STATE_KEY_INVENTORY, self._inventory_cache)

    async def set_inventory(self, full_inventory: dict):
        """
        [优化版] 全量设置库存，用于周期性的校准 (线程安全)。
        """
        async with self._lock:
            self._inventory_cache = full_inventory
            await set_state(STATE_KEY_INVENTORY, self._inventory_cache)
            format_and_log("SYSTEM", "库存管理器", {'状态': '已全量更新库存'})

# 创建一个全局单例
inventory_manager = InventoryManager()
