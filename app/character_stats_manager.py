# -*- coding: utf-8 -*-
from app.state_manager import get_state, set_state
from app.logger import format_and_log

# 贡献值目前存储在宝库状态中
STATE_KEY_TREASURY = "sect_treasury"

class CharacterStatsManager:
    def __init__(self):
        self._stats_cache = {}

    async def _load_contribution(self):
        """从宗门宝库状态中加载贡献值到内存"""
        if 'contribution' not in self._stats_cache:
            treasury_data = await get_state(STATE_KEY_TREASURY, is_json=True, default={})
            self._stats_cache['contribution'] = treasury_data.get('contribution', 0)
            format_and_log("SYSTEM", "角色数值管理器", {'状态': '已从State加载贡献值到内存'})

    async def get_contribution(self) -> int:
        """获取当前的宗门贡献值"""
        await self._load_contribution()
        return self._stats_cache.get('contribution', 0)

    async def _save_contribution(self):
        """将内存中的贡献值写回宗门宝库状态"""
        treasury_data = await get_state(STATE_KEY_TREASURY, is_json=True, default={})
        treasury_data['contribution'] = self._stats_cache.get('contribution', 0)
        await set_state(STATE_KEY_TREASURY, treasury_data)

    async def add_contribution(self, quantity: int):
        """增加贡献值并持久化"""
        if not isinstance(quantity, int) or quantity <= 0:
            return
        
        await self._load_contribution()
        current_value = self._stats_cache.get('contribution', 0)
        new_value = current_value + quantity
        self._stats_cache['contribution'] = new_value
        await self._save_contribution()
        format_and_log("DEBUG", "数值更新 (增加)", {'项目': '宗门贡献', '数量': f'+{quantity}', '当前总量': new_value})

    async def remove_contribution(self, quantity: int):
        """减少贡献值并持久化"""
        if not isinstance(quantity, int) or quantity <= 0:
            return

        await self._load_contribution()
        current_value = self._stats_cache.get('contribution', 0)
        new_value = max(0, current_value - quantity) # 贡献不会是负数
        self._stats_cache['contribution'] = new_value
        await self._save_contribution()
        format_and_log("DEBUG", "数值更新 (减少)", {'项目': '宗门贡献', '数量': f'-{quantity}', '剩余': new_value})

    async def set_contribution(self, value: int):
        """全量设置贡献值，用于校准"""
        if not isinstance(value, int):
            return
            
        self._stats_cache['contribution'] = value
        await self._save_contribution()
        format_and_log("SYSTEM", "角色数值管理器", {'状态': '已全量更新贡献值', '新值': value})

# 创建一个全局单例
stats_manager = CharacterStatsManager()
