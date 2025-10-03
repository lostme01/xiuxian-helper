# -*- coding: utf-8 -*-
import json
from config import settings
from app.context import get_application
from app import redis_client
from app.logger import format_and_log

def _normalize_formation_name(name: str) -> str:
    """
    标准化阵法名称，去除常见的后缀。
    例如: "三才微尘阵图" -> "三才微尘阵"
    """
    return name.replace("阵图", "").replace("阵法", "").replace("图", "")

async def logic_check_knowledge_all_accounts() -> str:
    """
    [最终修复版]
    遍历每个助手，使用其自身的宝库缓存，并通过名称标准化进行精确对比。
    """
    app = get_application()
    if not app.redis_db:
        return "❌ 错误: Redis 未连接。"

    my_id = str(app.client.me.id)
    report_lines = ["\n✨ **各助手学习进度盘点**\n---"]
    keys_found = [key async for key in app.redis_db.scan_iter("tg_helper:task_states:*")]
    
    other_accounts_count = 0
    for key in keys_found:
        account_id_str = key.split(':')[-1]
        if account_id_str == my_id:
            continue
        
        other_accounts_count += 1
        account_report = [f"**- 助手ID**: `...{account_id_str[-4:]}`"]
        
        account_state = await app.redis_db.hgetall(key)
        
        treasury_json = account_state.get("sect_treasury")
        if not treasury_json:
            account_report.append("  - `⚠️ 缺少宗门宝库缓存，无法对比。`")
            report_lines.append("\n".join(account_report))
            continue

        try:
            treasury_data = json.loads(treasury_json)
            # --- 核心修复：正确解析和分类宝库物品 ---
            all_recipes = set()
            all_blueprints = set()
            all_formations = set()

            for item in treasury_data.get("items", []):
                item_name = item.get("name", "")
                if "丹方" in item_name:
                    all_recipes.add(item_name)
                elif "图纸" in item_name:
                    all_blueprints.add(item_name)
                elif "阵" in item_name: # 泛匹配与阵法相关的物品
                    # --- 核心修复：对阵法名称进行标准化 ---
                    all_formations.add(_normalize_formation_name(item_name))

        except (json.JSONDecodeError, TypeError):
            account_report.append("  - `❌ 解析该助手的宗门宝库数据失败。`")
            report_lines.append("\n".join(account_report))
            continue

        # 对比丹方和图纸
        learned_recipes_json = account_state.get("learned_recipes")
        learned_recipes = set(json.loads(learned_recipes_json) if learned_recipes_json else [])
        
        unlearned_recipes = all_recipes - learned_recipes
        unlearned_blueprints = all_blueprints - learned_recipes
        
        if unlearned_recipes:
            account_report.append(f"  - **未学丹方**: `{', '.join(sorted(unlearned_recipes))}`")
        if unlearned_blueprints:
            account_report.append(f"  - **未学图纸**: `{', '.join(sorted(unlearned_blueprints))}`")

        # 对比阵法
        formation_info_json = account_state.get("formation_info")
        formation_info = json.loads(formation_info_json) if formation_info_json else {}
        learned_formations = set(formation_info.get("learned", [])) # 已学阵法名称已是标准格式
        
        unlearned_formations = all_formations - learned_formations
        if unlearned_formations:
            account_report.append(f"  - **未学阵法**: `{', '.join(sorted(unlearned_formations))}`")
            
        if len(account_report) == 1:
            account_report.append("  - `✅ 所有可学项目均已掌握。`")
            
        report_lines.append("\n".join(account_report))

    if other_accounts_count == 0:
        return "ℹ️ 未在 Redis 中找到任何其他助手的缓存数据。"

    return "\n\n".join(report_lines)
