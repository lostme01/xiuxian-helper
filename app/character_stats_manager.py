# -*- coding: utf-8 -*-
import asyncio
from app.context import get_application
from app.logger import format_and_log

STATE_KEY_TREASURY = "sect_treasury"

class CharacterStatsManager:
    def __init__(self):
        self.data_manager = None
        self._stats_cache = {}
        self._lock = asyncio.Lock()

    def initialize(self, data_manager):
        """注入 DataManager 依赖"""
        self.data_manager = data_manager
        format_and_log("SYSTEM", "组件初始化", {'组件': 'CharacterStatsManager', '状态': '依赖注入完成'})

    async def _load_contribution(self):
        """从 DataManager 加载贡献值到内存"""
        if 'contribution' not in self._stats_cache and self.data_manager:
            treasury_data = await self.data_manager.get_value(STATE_KEY_TREASURY, is_json=True, default={})
            self._stats_cache['contribution'] = treasury_data.get('contribution', 0)
            format_and_log("SYSTEM", "角色数值管理器", {'状态': '已从DataManager加载贡献值到内存'})

    async def get_contribution(self) -> int:
        """获取当前的宗门贡献值"""
        async with self._lock:
            await self._load_contribution()
            return self._stats_cache.get('contribution', 0)

    async def _save_contribution(self):
        """将内存中的贡献值写回宗门宝库状态"""
        if not self.data_manager: return
        treasury_data = await self.data_manager.get_value(STATE_KEY_TREASURY, is_json=True, default={})
        treasury_data['contribution'] = self._stats_cache.get('contribution', 0)
        await self.data_manager.save_value(STATE_KEY_TREASURY, treasury_data)

    async def add_contribution(self, quantity: int):
        """增加贡献值并持久化"""
        if not isinstance(quantity, int) or quantity <= 0: return
        async with self._lock:
            await self._load_contribution()
            current_value = self._stats_cache.get('contribution', 0)
            new_value = current_value + quantity
            self._stats_cache['contribution'] = new_value
            await self._save_contribution()
            format_and_log("DEBUG", "数值更新 (增加)", {'项目': '宗门贡献', '数量': f'+{quantity}', '当前总量': new_value})

    async def remove_contribution(self, quantity: int):
        """减少贡献值并持久化"""
        if not isinstance(quantity, int) or quantity <= 0: return
        async with self._lock:
            await self._load_contribution()
            current_value = self._stats_cache.get('contribution', 0)
            new_value = max(0, current_value - quantity)
            self._stats_cache['contribution'] = new_value
            await self._save_contribution()
            format_and_log("DEBUG", "数值更新 (减少)", {'项目': '宗门贡献', '数量': f'-{quantity}', '剩余': new_value})

    async def set_contribution(self, value: int):
        """全量设置贡献值，用于校准"""
        if not isinstance(value, int): return
        async with self._lock:
            self._stats_cache['contribution'] = value
            await self._save_contribution()
            format_and_log("SYSTEM", "角色数值管理器", {'状态': '已全量更新贡献值', '新值': value})

# 创建全局单例
stats_manager = CharacterStatsManager()
