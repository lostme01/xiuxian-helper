# -*- coding: utf-8 -*-
import asyncio

from app.constants import STATE_KEY_SECT_TREASURY, STATE_KEY_PROFILE
from app.logging_service import LogType, format_and_log


class CharacterStatsManager:
    def __init__(self):
        self.data_manager = None
        self._stats_cache = {}
        self._lock = asyncio.Lock()
        self._initialized = asyncio.Event()

    def initialize(self, data_manager):
        """注入 DataManager 依赖"""
        self.data_manager = data_manager
        format_and_log(LogType.SYSTEM, "组件初始化", {'组件': 'CharacterStatsManager', '状态': '依赖注入完成'})

    async def _load_initial_stats(self):
        """[修改] 初始化时同时加载贡献和修为"""
        if not self._initialized.is_set() and self.data_manager:
            async with self._lock:
                if not self._initialized.is_set():
                    # 加载贡献
                    treasury_data = await self.data_manager.get_value(STATE_KEY_SECT_TREASURY, is_json=True, default={})
                    self._stats_cache['contribution'] = treasury_data.get('contribution', 0)
                    
                    # 加载修为
                    profile_data = await self.data_manager.get_value(STATE_KEY_PROFILE, is_json=True, default={})
                    self._stats_cache['cultivation'] = profile_data.get('修为', 0)

                    self._initialized.set()
                    format_and_log(LogType.SYSTEM, "角色数值管理器", {'状态': '已从DataManager加载初始数值到内存'})
        if self.data_manager:
            await self._initialized.wait()

    # --- 贡献管理 ---
    async def get_contribution(self) -> int:
        """获取当前的宗门贡献值"""
        await self._load_initial_stats()
        async with self._lock:
            return self._stats_cache.get('contribution', 0)

    async def _save_contribution(self):
        """将内存中的贡献值写回宗门宝库状态"""
        if not self.data_manager: return
        treasury_data = await self.data_manager.get_value(STATE_KEY_SECT_TREASURY, is_json=True, default={})
        treasury_data['contribution'] = self._stats_cache.get('contribution', 0)
        await self.data_manager.save_value(STATE_KEY_SECT_TREASURY, treasury_data)

    async def add_contribution(self, quantity: int):
        if not isinstance(quantity, int) or quantity <= 0: return
        await self._load_initial_stats()
        async with self._lock:
            current_value = self._stats_cache.get('contribution', 0)
            new_value = current_value + quantity
            self._stats_cache['contribution'] = new_value
            await self._save_contribution()
            format_and_log(LogType.DEBUG, "数值更新 (增加)", {'项目': '宗门贡献', '数量': f'+{quantity}', '当前总量': new_value})

    async def remove_contribution(self, quantity: int):
        if not isinstance(quantity, int) or quantity <= 0: return
        await self._load_initial_stats()
        async with self._lock:
            current_value = self._stats_cache.get('contribution', 0)
            new_value = max(0, current_value - quantity)
            self._stats_cache['contribution'] = new_value
            await self._save_contribution()
            format_and_log(LogType.DEBUG, "数值更新 (减少)", {'项目': '宗门贡献', '数量': f'-{quantity}', '剩余': new_value})

    async def set_contribution(self, value: int):
        if not isinstance(value, int): return
        async with self._lock:
            self._stats_cache['contribution'] = value
            await self._save_contribution()
            if not self._initialized.is_set(): self._initialized.set()
            format_and_log(LogType.SYSTEM, "角色数值管理器", {'状态': '已全量更新贡献值', '新值': value})
            
    # --- 修为管理 ---
    async def get_cultivation(self) -> int:
        """获取当前修为"""
        await self._load_initial_stats()
        async with self._lock:
            return self._stats_cache.get('cultivation', 0)

    async def _save_cultivation(self):
        """将内存中的修为写回角色信息"""
        if not self.data_manager: return
        profile_data = await self.data_manager.get_value(STATE_KEY_PROFILE, is_json=True, default={})
        profile_data['修为'] = self._stats_cache.get('cultivation', 0)
        await self.data_manager.save_value(STATE_KEY_PROFILE, profile_data)

    async def add_cultivation(self, quantity: int):
        if not isinstance(quantity, int) or quantity <= 0: return
        await self._load_initial_stats()
        async with self._lock:
            current_value = self._stats_cache.get('cultivation', 0)
            new_value = current_value + quantity
            self._stats_cache['cultivation'] = new_value
            await self._save_cultivation()
            format_and_log(LogType.DEBUG, "数值更新 (增加)", {'项目': '修为', '数量': f'+{quantity}', '当前总量': new_value})

    async def remove_cultivation(self, quantity: int):
        """[新增] 减少修为值并持久化"""
        if not isinstance(quantity, int) or quantity <= 0: return
        await self._load_initial_stats()
        async with self._lock:
            current_value = self._stats_cache.get('cultivation', 0)
            new_value = current_value - quantity # 允许修为为负
            self._stats_cache['cultivation'] = new_value
            await self._save_cultivation()
            format_and_log(LogType.DEBUG, "数值更新 (减少)", {'项目': '修为', '数量': f'-{quantity}', '剩余': new_value})


# 创建全局单例
stats_manager = CharacterStatsManager()
