# -*- coding: utf-8 -*-
import json
import asyncio
from app.context import get_application
from app.logger import format_and_log

class InventoryManager:
    def __init__(self):
        self.data_manager = None
        self._inventory_cache = None
        self._lock = asyncio.Lock()

    def initialize(self, data_manager):
        """注入 DataManager 依赖"""
        self.data_manager = data_manager
        format_and_log("SYSTEM", "组件初始化", {'组件': 'InventoryManager', '状态': '依赖注入完成'})

    async def _load_inventory(self):
        """从 DataManager 加载库存到内存"""
        if self._inventory_cache is None and self.data_manager:
            self._inventory_cache = await self.data_manager.get_value("inventory", is_json=True, default={})
            format_and_log("SYSTEM", "库存管理器", {'状态': '已从DataManager加载库存到内存'})

    async def get_inventory(self) -> dict:
        """获取当前完整的库存字典"""
        async with self._lock:
            await self._load_inventory()
            return self._inventory_cache.copy() if self._inventory_cache else {}

    async def get_item_count(self, item_name: str) -> int:
        """获取单个物品的数量"""
        async with self._lock:
            await self._load_inventory()
            return self._inventory_cache.get(item_name, 0) if self._inventory_cache else 0

    async def add_item(self, item_name: str, quantity: int):
        """增加指定物品的数量，并立即持久化"""
        if not isinstance(quantity, int) or quantity <= 0 or not self.data_manager:
            return
        
        async with self._lock:
            await self._load_inventory()
            current_quantity = self._inventory_cache.get(item_name, 0)
            new_quantity = current_quantity + quantity
            self._inventory_cache[item_name] = new_quantity
            await self.data_manager.save_value("inventory", self._inventory_cache)
            format_and_log("DEBUG", "库存更新 (增加)", {'物品': item_name, '数量': f'+{quantity}', '当前总量': new_quantity})

    async def remove_item(self, item_name: str, quantity: int):
        """减少指定物品的数量，并立即持久化"""
        if not isinstance(quantity, int) or quantity <= 0 or not self.data_manager:
            return
            
        async with self._lock:
            await self._load_inventory()
            current_quantity = self._inventory_cache.get(item_name, 0)
            
            if current_quantity < quantity:
                format_and_log("WARNING", "库存更新 (扣减)", {'物品': item_name, '问题': '数量不足', '请求扣减': quantity, '实际拥有': current_quantity})
                self._inventory_cache.pop(item_name, None)
            else:
                new_quantity = current_quantity - quantity
                if new_quantity > 0:
                    self._inventory_cache[item_name] = new_quantity
                else:
                    self._inventory_cache.pop(item_name, None)
                format_and_log("DEBUG", "库存更新 (减少)", {'物品': item_name, '数量': f'-{quantity}', '剩余': self._inventory_cache.get(item_name, 0)})

            await self.data_manager.save_value("inventory", self._inventory_cache)

    async def set_inventory(self, full_inventory: dict):
        """全量设置库存，用于周期性的校准"""
        if not self.data_manager: return
        async with self._lock:
            self._inventory_cache = full_inventory
            await self.data_manager.save_value("inventory", self._inventory_cache)
            format_and_log("SYSTEM", "库存管理器", {'状态': '已全量更新库存'})

# 创建全局单例
inventory_manager = InventoryManager()
