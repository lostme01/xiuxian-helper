# -*- coding: utf-8 -*-
"""
游戏行为适配层 (Game Adaptor) - 工厂模块

该模块作为适配器的统一入口。它会根据配置动态加载并实例化
一个具体功能的游戏适配器类，供项目中所有插件统一调用。
"""
from config import settings
from app.game_adaptors.mortal_cultivation_adaptor import MortalCultivationAdaptor

def _create_adaptor():
    """
    工厂函数，根据配置创建并返回一个游戏适配器实例。
    未来可在此处扩展，以支持加载不同的适配器。
    """
    # 当前只支持一个适配器，未来可以从 settings.py 读取配置来决定加载哪个
    # game_adaptor_name = settings.GAME_ADAPTOR
    # if game_adaptor_name == 'MortalCultivation':
    #     return MortalCultivationAdaptor()
    # else:
    #     raise NotImplementedError(f"未实现的游戏适配器: {game_adaptor_name}")
    
    return MortalCultivationAdaptor()

# --- 全局单例 ---
# 在模块加载时，立即创建一个适配器实例，项目中所有地方都将导入并使用这个实例。
# 这确保了所有插件调用的都是同一个对象，且符合我们之前函数式调用的习惯。
game_adaptor = _create_adaptor()

# --- 动态代理 ---
# 为了让插件的代码完全无需修改 (例如，继续使用 `game_adaptor.get_profile()`)
# 我们将实例的方法暴露在模块级别。
# 注意：这是一种为了保持向后兼容的技巧，新代码应优先使用 game_adaptor 实例。

# --- [核心修复] 新增 divination 指令的代理 ---
divination = game_adaptor.divination

parse_profile = game_adaptor.parse_profile
list_item = game_adaptor.list_item
buy_item = game_adaptor.buy_item
unlist_item = game_adaptor.unlist_item
get_my_stall = game_adaptor.get_my_stall
craft_item = game_adaptor.craft_item
get_crafting_list = game_adaptor.get_crafting_list
learn_recipe = game_adaptor.learn_recipe
get_inventory = game_adaptor.get_inventory
meditate = game_adaptor.meditate
challenge_tower = game_adaptor.challenge_tower
get_profile = game_adaptor.get_profile
get_formation_info = game_adaptor.get_formation_info
get_sect_treasury = game_adaptor.get_sect_treasury
sect_check_in = game_adaptor.sect_check_in
sect_contribute_skill = game_adaptor.sect_contribute_skill
sect_donate = game_adaptor.sect_donate
sect_exchange = game_adaptor.sect_exchange
huangfeng_garden = game_adaptor.huangfeng_garden
huangfeng_water = game_adaptor.huangfeng_water
huangfeng_remove_pests = game_adaptor.huangfeng_remove_pests
huangfeng_weed = game_adaptor.huangfeng_weed
huangfeng_harvest = game_adaptor.huangfeng_harvest
huangfeng_sow = game_adaptor.huangfeng_sow
mojun_hide_presence = game_adaptor.mojun_hide_presence
