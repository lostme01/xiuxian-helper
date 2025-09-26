# -*- coding: utf-8 -*-
from config import settings
from app.config_manager import update_setting
# *** 新增导入 ***
from app.utils import mask_string

HELP_DETAILS = {
    "玄骨校考": "开启、关闭或查看玄骨校考自动作答功能。\n用法: `,玄骨校考 [开|关]`",
    "天机考验": "开启、关闭或查看天机考验自动作答功能。\n用法: `,天机考验 [开|关]`",
    "设置AIKey": "设置或查看Google Gemini的API密钥。\n用法: `,设置AIKey [<你的API密钥>]`",
    "闭关任务": "开启、关闭或查看后台自动闭关修炼任务。\n用法: `,闭关任务 [开|关]`",
    "点卯任务": "开启、关闭或查看后台自动宗门点卯任务。\n用法: `,点卯任务 [开|关]`",
    "学习任务": "开启、关闭或查看后台自动学习图纸任务。\n用法: `,学习任务 [开|关]`",
    "药园任务": "开启、关闭或查看后台自动药园管理任务。\n用法: `,药园任务 [开|关]`",
    "背包任务": "开启、关闭或查看后台自动刷新背包任务。\n用法: `,背包任务 [开|关]`",
}

# --- 答题功能开关 ---
async def _cmd_xuanggu_exam_toggle(client, event, parts):
    current_value = settings.EXAM_SOLVER_CONFIG.get('enabled')
    await _toggle_handler(event, parts, '玄骨校考', 'exam_solver', 'enabled', current_value)

async def _cmd_tianji_exam_toggle(client, event, parts):
    current_value = settings.TIANJI_EXAM_CONFIG.get('enabled')
    await _toggle_handler(event, parts, '天机考验', 'tianji_exam_solver', 'enabled', current_value)

# --- 后台任务开关 ---
async def _cmd_task_toggle(client, event, parts):
    command_map = {
        "闭关任务": ('闭关修炼', 'biguan'),
        "点卯任务": ('宗门点卯', 'dianmao'),
        "学习任务": ('自动学习', 'learn_recipes'),
        "药园任务": ('自动药园', 'garden_check'),
        "背包任务": ('自动刷新背包', 'inventory_refresh'),
    }
    command = parts[0]
    friendly_name, config_key = command_map[command]
    current_value = settings.TASK_SWITCHES.get(config_key)
    await _toggle_handler(event, parts, friendly_name, 'task_switches', config_key, current_value)

# --- 通用处理器与指令注册 ---
async def _toggle_handler(event, parts, name, root_key, sub_key, current_value):
    """一个通用的、支持状态查询的开关处理器"""
    if len(parts) == 1:
        current_status_str = "开启" if current_value else "关闭"
        await event.reply(f"当前 **{name}** 功能状态: **{current_status_str}**", parse_mode='md')
        return

    if len(parts) == 2 and parts[1] in ["开", "关"]:
        switch_action = parts[1]
        new_status = (switch_action == "开")
        await update_setting(event,
            root_key=root_key,
            sub_key=sub_key,
            value=new_status,
            success_message=f"**{name}** 功能已 **{switch_action}**"
        )
    else:
        await event.reply(f"用法: `,{parts[0]} [开|关]`", parse_mode='md')


async def _cmd_set_gemini_key(client, event, parts):
    """设置或查看 Gemini API Key，需要重启生效"""
    # *** 优化：当不带参数时，显示脱敏后的当前 Key ***
    if len(parts) == 1:
        current_key = settings.EXAM_SOLVER_CONFIG.get('gemini_api_key')
        if current_key:
            masked_key = mask_string(current_key)
            await event.reply(f"当前设置的 Gemini API Key: `{masked_key}`", parse_mode='md')
        else:
            await event.reply("当前未设置 Gemini API Key。")
        return

    if len(parts) != 2:
        await event.reply(HELP_DETAILS["设置AIKey"], parse_mode='md')
        return

    new_api_key = parts[1]
    await update_setting(event,
        root_key='exam_solver',
        sub_key='gemini_api_key',
        value=new_api_key,
        success_message=f"✅ Gemini API Key 设置成功。\n**请使用 `,重启` 指令以使新密钥生效**"
    )

def initialize_commands(client):
    client.register_admin_command("玄骨校考", _cmd_xuanggu_exam_toggle, HELP_DETAILS["玄骨校考"])
    client.register_admin_command("天机考验", _cmd_tianji_exam_toggle, HELP_DETAILS["天机考验"])
    client.register_admin_command("设置AIKey", _cmd_set_gemini_key, HELP_DETAILS["设置AIKey"])
    client.register_admin_command("闭关任务", _cmd_task_toggle, HELP_DETAILS["闭关任务"])
    client.register_admin_command("点卯任务", _cmd_task_toggle, HELP_DETAILS["点卯任务"])
    client.register_admin_command("学习任务", _cmd_task_toggle, HELP_DETAILS["学习任务"])
    client.register_admin_command("药园任务", _cmd_task_toggle, HELP_DETAILS["药园任务"])
    client.register_admin_command("背包任务", _cmd_task_toggle, HELP_DETAILS["背包任务"])
