# -*- coding: utf-8 -*-
import asyncio

from app.constants import STATE_KEY_SECT_TREASURY
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

    async def _load_contribution(self):
        """从 DataManager 加载贡献值到内存"""
        if not self._initialized.is_set() and self.data_manager:
            async with self._lock:
                if not self._initialized.is_set():
                    treasury_data = await self.data_manager.get_value(STATE_KEY_SECT_TREASURY, is_json=True, default={})
                    self._stats_cache['contribution'] = treasury_data.get('contribution', 0)
                    self._initialized.set()
                    format_and_log(LogType.SYSTEM, "角色数值管理器", {'状态': '已从DataManager加载贡献值到内存'})
        if self.data_manager:
            await self._initialized.wait()

    async def get_contribution(self) -> int:
        """获取当前的宗门贡献值"""
        await self._load_contribution()
        async with self._lock:
            return self._stats_cache.get('contribution', 0)

    async def _save_contribution(self):
        """将内存中的贡献值写回宗门宝库状态"""
        if not self.data_manager: return
        # 加载最新数据，以防其他字段被覆盖
        treasury_data = await self.data_manager.get_value(STATE_KEY_SECT_TREASURY, is_json=True, default={})
        treasury_data['contribution'] = self._stats_cache.get('contribution', 0)
        await self.data_manager.save_value(STATE_KEY_SECT_TREASURY, treasury_data)

    async def add_contribution(self, quantity: int):
        """增加贡献值并持久化"""
        if not isinstance(quantity, int) or quantity <= 0: return
        await self._load_contribution()
        async with self._lock:
            current_value = self._stats_cache.get('contribution', 0)
            new_value = current_value + quantity
            self._stats_cache['contribution'] = new_value
            await self._save_contribution()
            format_and_log(LogType.DEBUG, "数值更新 (增加)", {'项目': '宗门贡献', '数量': f'+{quantity}', '当前总量': new_value})

    async def remove_contribution(self, quantity: int):
        """减少贡献值并持久化"""
        if not isinstance(quantity, int) or quantity <= 0: return
        await self._load_contribution()
        async with self._lock:
            current_value = self._stats_cache.get('contribution', 0)
            new_value = max(0, current_value - quantity)
            self._stats_cache['contribution'] = new_value
            await self._save_contribution()
            format_and_log(LogType.DEBUG, "数值更新 (减少)", {'项目': '宗门贡献', '数量': f'-{quantity}', '剩余': new_value})

    async def set_contribution(self, value: int):
        """全量设置贡献值，用于校准"""
        if not isinstance(value, int): return
        async with self._lock:
            self._stats_cache['contribution'] = value
            await self._save_contribution()
            if not self._initialized.is_set():
                self._initialized.set()
            format_and_log(LogType.SYSTEM, "角色数值管理器", {'状态': '已全量更新贡献值', '新值': value})


# 创建全局单例
stats_manager = CharacterStatsManager()
