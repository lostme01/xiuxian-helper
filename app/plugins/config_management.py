# -*- coding: utf-8 -*-
from config import settings
from app.context import get_application
from .logic import config_logic
from app.config_manager import update_setting
from app.logger import LOG_DESC_TO_SWITCH, LOG_SWITCH_TO_DESC

HELP_TEXT_GET_CONFIG = """🔍 **查看当前配置**
**用法**:
  `,`查看配置 —— 显示所有可查询的配置项。
  `,`查看配置 <中文配置名> —— 显示指定项的值。
**示例**: `,查看配置 AI模型`"""
HELP_TEXT_TOGGLE_LOG = "📝 **管理日志开关**\n**用法**: `,日志开关 <类型|全部消息> <开|关>`"
HELP_TEXT_TOGGLE_TASK = "🔧 **管理功能开关**\n**用法**: `,任务开关 <功能名> [<开|关>]`"

def _get_settings_object(root_key: str) -> dict | None:
    """
    [修复版]
    一个健壮的函数，用于在settings模块中根据不同的命名模式查找配置对象。
    """
    # 模式1: 直接匹配大写变量名 (例如, TASK_SWITCHES)
    if hasattr(settings, root_key.upper()):
        return getattr(settings, root_key.upper())
    
    # 模式2: 匹配 _CONFIG 后缀 (例如, TRADE_COORDINATION_CONFIG)
    if hasattr(settings, f"{root_key.upper()}_CONFIG"):
        return getattr(settings, f"{root_key.upper()}_CONFIG")
        
    # 模式3: 针对 solver 的特殊模式 (例如, XUANGU_EXAM_CONFIG)
    if root_key.endswith('_solver'):
        base_name = root_key.replace('_solver', '')
        if hasattr(settings, f"{base_name.upper()}_CONFIG"):
            return getattr(settings, f"{base_name.upper()}_CONFIG")
            
    return None

async def _cmd_get_config(event, parts):
    key_to_query = parts[1] if len(parts) > 1 else None
    await get_application().client.reply_to_admin(event, await config_logic.logic_get_config_item(key_to_query))

async def _cmd_toggle_log(event, parts):
    client = get_application().client
    if len(parts) == 1:
        status_text = "📝 **各模块日志开关状态**:\n\n"
        switches = []
        for switch_name, desc in LOG_SWITCH_TO_DESC.items():
            is_enabled = settings.LOGGING_SWITCHES.get(switch_name, False)
            status = "✅ 开启" if is_enabled else "❌ 关闭"
            switches.append(f"- **{desc}**: {status}")
        status_text += "\n".join(sorted(switches))
        status_text += f"\n\n**用法**: `,日志开关 <类型|全部消息> <开|关>`"
        await client.reply_to_admin(event, status_text)
        return

    if len(parts) != 3 or parts[2] not in ["开", "关"]:
        await client.reply_to_admin(event, f"❌ 参数格式错误！\n\n{HELP_TEXT_TOGGLE_LOG}")
        return

    _, log_type_desc, switch = parts
    new_status = (switch == "开")

    if log_type_desc == "全部消息":
        response_msg = await config_logic.logic_toggle_all_logs(new_status)
        await client.reply_to_admin(event, response_msg)
        return

    log_switch_name = LOG_DESC_TO_SWITCH.get(log_type_desc)
    if not log_switch_name:
        available_types = ' '.join([f"`{d}`" for d in sorted(LOG_DESC_TO_SWITCH.keys())])
        await client.reply_to_admin(event, f"❌ 未知的日志类型: `{log_type_desc}`\n\n**可用类型**: {available_types}")
        return
        
    await client.reply_to_admin(event, update_setting(root_key='logging_switches', sub_key=log_switch_name, value=new_status, success_message=f"**{log_type_desc}** 日志已 **{switch}**"))

async def _cmd_toggle_task(event, parts):
    client = get_application().client
    task_map = {
        '玄骨': ('玄骨考校', 'xuangu_exam_solver', 'enabled'),
        '天机': ('天机考验', 'tianji_exam_solver', 'enabled'),
        '闭关': ('自动闭关', 'task_switches', 'biguan'),
        '点卯': ('自动点卯', 'task_switches', 'dianmao'),
        '学习': ('自动学习', 'task_switches', 'learn_recipes'),
        '药园': ('自动药园', 'task_switches', 'garden_check'),
        '背包': ('自动刷新背包', 'task_switches', 'inventory_refresh'),
        '闯塔': ('自动闯塔', 'task_switches', 'chuang_ta'),
        '宝库': ('自动宗门宝库', 'task_switches', 'sect_treasury'),
        '阵法': ('自动更新阵法', 'task_switches', 'formation_update'),
        '魔君': ('自动应对魔君', 'task_switches', 'mojun_arrival'),
        '自动删除': ('消息自动删除', 'auto_delete', 'enabled'),
        '集火下架': ('集火后自动下架', 'trade_coordination', 'focus_fire_auto_delist'),
    }
    
    if len(parts) == 1:
        status_lines = ["🔧 **各功能开关状态**:\n"]
        for key, (friendly_name, root_key, sub_key) in sorted(task_map.items()):
            # --- 核心修改：使用新的健壮的查找函数 ---
            config_obj = _get_settings_object(root_key) or {}
            is_enabled = config_obj.get(sub_key, False)
            status = "✅ 开启" if is_enabled else "❌ 关闭"
            status_lines.append(f"- **{friendly_name}** (`{key}`): {status}")
        
        status_lines.append(f"\n**用法**: `,任务开关 <功能名> [<开|关>]`")
        await client.reply_to_admin(event, "\n".join(status_lines))
        return

    task_name = parts[1]
    if task_name not in task_map:
        await client.reply_to_admin(event, f"❌ 未知的功能名: `{task_name}`。")
        return
        
    friendly_name, root_key, sub_key = task_map[task_name]
    
    config_obj = _get_settings_object(root_key) or {}
        
    if len(parts) == 2:
        current_value = config_obj.get(sub_key)
        await client.reply_to_admin(event, f"ℹ️ 当前 **{friendly_name}** 功能状态: **{'开启' if current_value else '关闭'}**")
        return
        
    if len(parts) == 3 and parts[2] in ["开", "关"]:
        new_status = (parts[2] == "开")
        await client.reply_to_admin(event, update_setting(root_key=root_key, sub_key=sub_key, value=new_status, success_message=f"**{friendly_name}** 功能已 **{parts[2]}**"))
    else:
        await client.reply_to_admin(event, f"❌ 参数格式错误！\n\n{HELP_TEXT_TOGGLE_TASK}")

def initialize(app):
    app.register_command("查看配置", _cmd_get_config, help_text="🔍 查看当前配置项。", category="系统配置", aliases=['getconfig'], usage=HELP_TEXT_GET_CONFIG)
    app.register_command("日志开关", _cmd_toggle_log, help_text="📝 管理日志模块开关。", category="系统配置", usage=HELP_TEXT_TOGGLE_LOG)
    app.register_command("任务开关", _cmd_toggle_task, help_text="🔧 管理后台功能开关。", category="系统配置", usage=HELP_TEXT_TOGGLE_TASK)
