# -*- coding: utf-8 -*-
import json
from config import settings
from app.context import get_application
from app import redis_client
from app.logger import format_and_log

async def logic_check_knowledge_all_accounts() -> str:
    """
    [修改版]
    遍历每个助手，并使用其自身的宗门宝库缓存作为标准进行对比。
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
        
        # 1. 获取该助手的全部状态数据
        account_state = await app.redis_db.hgetall(key)
        
        # 2. 从该助手的状态中，获取其自己的宗门宝库作为“总纲”
        treasury_json = account_state.get("sect_treasury")
        if not treasury_json:
            account_report.append("  - `⚠️ 缺少宗门宝库缓存，无法对比。`")
            report_lines.append("\n".join(account_report))
            continue

        try:
            treasury_data = json.loads(treasury_json)
            all_recipes = set(treasury_data.get("丹方", []))
            all_blueprints = set(treasury_data.get("图纸", []))
            all_formations = set(treasury_data.get("阵法", []))
        except (json.JSONDecodeError, TypeError):
            account_report.append("  - `❌ 解析宗门宝库数据失败。`")
            report_lines.append("\n".join(account_report))
            continue

        # 3. 对比丹方和图纸
        learned_recipes_json = account_state.get("learned_recipes")
        learned_recipes = set(json.loads(learned_recipes_json) if learned_recipes_json else [])
        
        unlearned_recipes = all_recipes - learned_recipes
        unlearned_blueprints = all_blueprints - learned_recipes
        
        if unlearned_recipes:
            account_report.append(f"  - **未学丹方**: `{', '.join(sorted(unlearned_recipes))}`")
        if unlearned_blueprints:
            account_report.append(f"  - **未学图纸**: `{', '.join(sorted(unlearned_blueprints))}`")

        # 4. 对比阵法
        formation_info_json = account_state.get("formation_info")
        formation_info = json.loads(formation_info_json) if formation_info_json else {}
        learned_formations = set(formation_info.get("learned", []))
        
        unlearned_formations = all_formations - learned_formations
        if unlearned_formations:
            account_report.append(f"  - **未学阵法**: `{', '.join(sorted(unlearned_formations))}`")
            
        # 如果该号全部学完
        if len(account_report) == 1:
            account_report.append("  - `✅ 所有项目均已学习完毕。`")
            
        report_lines.append("\n".join(account_report))

    if other_accounts_count == 0:
        return "ℹ️ 未在 Redis 中找到任何其他助手的缓存数据。"

    return "\n\n".join(report_lines)
