# -*- coding: utf-8 -*-
from app.config_manager import update_nested_setting, update_setting
from app.context import get_application
from app.logging_service import LogType
from config import settings
from .logic import config_logic
# [重构] 从元数据中心导入配置定义
from app.config_meta import MODIFIABLE_CONFIGS, LOGGING_SWITCHES_META, TASK_SWITCHES_META

HELP_TEXT_GET_CONFIG = """🔍 **查看当前配置**
**用法**:
  `,`查看配置 —— 显示所有可查询的配置项。
  `,`查看配置 <中文配置名> —— 显示指定项的值。
**示例**: `,查看配置 AI模型`"""

HELP_TEXT_TOGGLE_LOG = """📝 **动态管理日志开关**
**说明**: 无需重启，即时开启或关闭不同模块的日志记录。
- 不带参数发送可查看所有日志的当前状态。
- 使用`,日志开关 全部消息 <开|关>`可批量操作。
**用法**: `,日志开关 <类型> <开|关>`"""

HELP_TEXT_TOGGLE_TASK = """🔧 **动态管理功能开关**
**说明**: 无需重启，即时开启或关闭各项后台功能。
- 不带参数发送可查看所有开关的当前状态。
**用法**: `,任务开关 <功能名> [<开|关>]`"""

HELP_TEXT_SET_CONFIG = """⚙️ **动态修改详细配置**
**说明**: 无需重启，即时修改 `prod.yaml` 中的指定参数。
- 不带参数发送可查看所有支持动态修改的配置项。
**用法**: `,修改配置 <配置别名> <新值>`"""

# [重构] 动态生成反向映射
LOG_DESC_TO_SWITCH = {v: k for k, v in LOGGING_SWITCHES_META.items()}

async def _cmd_get_config(event, parts):
    key_to_query = parts[1] if len(parts) > 1 else None
    await get_application().client.reply_to_admin(event, await config_logic.logic_get_config_item(key_to_query))


async def _cmd_toggle_log(event, parts):
    client = get_application().client
    if len(parts) == 1:
        status_text = "📝 **各模块日志开关状态**:\n\n"
        switches = []
        # [重构] 从元数据生成列表
        for switch_name, desc in LOGGING_SWITCHES_META.items():
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

    # [重构] 调用 update_setting
    msg = await update_setting('logging_switches', log_switch_name, new_status, f"**{log_type_desc}** 日志已 **{switch}**")
    await client.reply_to_admin(event, msg)


async def _cmd_toggle_task(event, parts):
    client = get_application().client

    if len(parts) == 1:
        status_lines = ["🔧 **各功能开关状态**:\n"]
        # [重构] 从元数据生成
        for key, (friendly_name, path) in sorted(TASK_SWITCHES_META.items()):
            root_key, sub_key = path.split('.', 1)
            # 使用 getattr 安全地访问 settings 模块中的配置字典
            config_obj = getattr(settings, root_key.upper(), {})
            if not isinstance(config_obj, dict):
                config_obj = getattr(settings, f"{root_key.upper()}_CONFIG", {})
            
            is_enabled = config_obj.get(sub_key, False)
            status = "✅ 开启" if is_enabled else "❌ 关闭"
            status_lines.append(f"- **{friendly_name}** (`{key}`): {status}")
        status_lines.append(f"\n**用法**: `,任务开关 <功能名> [<开|关>]`")
        await client.reply_to_admin(event, "\n".join(status_lines))
        return

    task_name = parts[1]
    if task_name not in TASK_SWITCHES_META:
        await client.reply_to_admin(event, f"❌ 未知的功能名: `{task_name}`。")
        return

    friendly_name, path = TASK_SWITCHES_META[task_name]
    root_key, sub_key = path.split('.', 1)

    if len(parts) == 2:
        config_obj = getattr(settings, root_key.upper(), {})
        if not isinstance(config_obj, dict):
             config_obj = getattr(settings, f"{root_key.upper()}_CONFIG", {})
        current_value = config_obj.get(sub_key)
        await client.reply_to_admin(event, f"ℹ️ 当前 **{friendly_name}** 功能状态: **{'开启' if current_value else '关闭'}**")
        return

    if len(parts) == 3 and parts[2] in ["开", "关"]:
        new_status = (parts[2] == "开")
        success_msg = f"**{friendly_name}** 功能已 **{parts[2]}**"
        
        # [重构] 调用 update_setting
        root_key_for_update = root_key.replace('_enabled', '') # 适配 update_setting 的逻辑
        msg = await update_setting(root_key_for_update, sub_key, new_status, success_msg)
        await client.reply_to_admin(event, msg)
    else:
        await client.reply_to_admin(event, f"❌ 参数格式错误！\n\n{HELP_TEXT_TOGGLE_TASK}")


async def _cmd_set_config(event, parts):
    client = get_application().client

    if len(parts) == 1:
        header = "⚙️ **可动态修改的配置项如下 (使用别名修改):**\n"
        # [重构] 从元数据生成
        items = [f"- **{alias}**: {desc}" for alias, (_, desc) in sorted(MODIFIABLE_CONFIGS.items())]
        usage = f"\n\n**用法**: `,修改配置 <配置别名> <新值>`"
        await client.reply_to_admin(event, header + '\n'.join(items) + usage)
        return

    if len(parts) < 3:
        await client.reply_to_admin(event, f"❌ 参数格式错误！\n\n{HELP_TEXT_SET_CONFIG}")
        return

    alias, value = parts[1], " ".join(parts[2:])

    if alias not in MODIFIABLE_CONFIGS:
        await client.reply_to_admin(event, f"❌ 未知的配置别名: `{alias}`")
        return

    path, _ = MODIFIABLE_CONFIGS[alias]
    result = await update_nested_setting(path, value)
    await client.reply_to_admin(event, result)


def initialize(app):
    app.register_command("查看配置", _cmd_get_config, help_text="🔍 查看当前配置项。", category="系统", aliases=['getconfig'],
                         usage=HELP_TEXT_GET_CONFIG)
    app.register_command("日志开关", _cmd_toggle_log, help_text="📝 动态管理日志开关。", category="系统",
                         usage=HELP_TEXT_TOGGLE_LOG)
    app.register_command("任务开关", _cmd_toggle_task, help_text="🔧 动态管理功能开关。", category="系统",
                         usage=HELP_TEXT_TOGGLE_TASK)
    app.register_command("修改配置", _cmd_set_config, help_text="⚙️ 动态修改详细配置。", category="系统", aliases=['setconfig'],
                         usage=HELP_TEXT_SET_CONFIG)

