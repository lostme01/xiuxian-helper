# -*- coding: utf-8 -*-
from config import settings
from app.config_manager import update_setting

HELP_DETAILS = {
    "宗门设置": "设置或查看当前配置的宗门。\n用法: `,宗门设置 [<宗门名>]`",
    "药园种子": "设置或查看小药园优先播种的种子。\n用法: `,药园种子 [<种子名>]`",
    "自动删除": "开启、关闭或查看消息自动删除功能。\n用法: `,自动删除 [开|关]`",
}

async def _cmd_sect_config(client, event, parts):
    if len(parts) == 1:
        current_sect = settings.SECT_NAME or "未设置"
        await event.reply(f"当前配置的宗门是: **{current_sect}**", parse_mode='md')
        return
    
    new_sect = parts[1]
    supported_sects = ['太一门', '黄枫谷']
    if new_sect not in supported_sects:
        await event.reply(f"错误: 不支持的宗门 `{new_sect}`。\n目前仅支持: `{' | '.join(supported_sects)}`", parse_mode='md')
        return
        
    await update_setting(event, 
        root_key='sect_name', 
        value=new_sect, 
        success_message=f"宗门设置成功: **{new_sect}**。\n**请使用 `,重启` 指令**以加载新的宗门专属任务。"
    )

async def _cmd_garden_seed_config(client, event, parts):
    if len(parts) == 1:
        current_seed = settings.GARDEN_SOW_SEED or "未设置"
        await event.reply(f"当前配置的优先播种种子是: **{current_seed}**", parse_mode='md')
        return
    
    seed_name = " ".join(parts[1:])
    await update_setting(event,
        root_key='huangfeng_valley',
        sub_key='garden_sow_seed',
        value=seed_name,
        success_message=f"小药园将优先播种 **{seed_name}**"
    )

async def _cmd_auto_delete_toggle(client, event, parts):
    # *** 优化：使其逻辑与其他开关指令完全一致 ***
    if len(parts) == 1:
        current_status = "开启" if settings.AUTO_DELETE.get('enabled') else "关闭"
        await event.reply(f"当前 **自动删除** 功能状态: **{current_status}**", parse_mode='md')
        return

    if len(parts) == 2 and parts[1] in ["开", "关"]:
        switch_action = parts[1]
        new_status = (switch_action == "开")
        await update_setting(event,
            root_key='auto_delete',
            sub_key='enabled',
            value=new_status,
            success_message=f"**自动删除** 功能已 **{switch_action}**"
        )
    else:
        await event.reply(HELP_DETAILS["自动删除"], parse_mode='md')


def initialize_commands(client):
    client.register_admin_command("宗门设置", _cmd_sect_config, HELP_DETAILS["宗门设置"])
    client.register_admin_command("药园种子", _cmd_garden_seed_config, HELP_DETAILS["药园种子"])
    client.register_admin_command("自动删除", _cmd_auto_delete_toggle, HELP_DETAILS["自动删除"])
