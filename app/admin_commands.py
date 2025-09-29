# -*- coding: utf-8 -*-
import sys
import asyncio
import os
import functools
from config import settings
from app import redis_client
from app.utils import mask_string, read_json_state
from app.config_manager import update_setting
from app.logger import format_and_log
from app.task_scheduler import scheduler
from app.plugins import common_tasks, huangfeng_valley, taiyi_sect, mojun_arrival

# --- 核心新增：创建一个装饰器来处理通用的 Redis 检查 ---
def redis_command(func):
    """
    一个装饰器，用于封装需要与 Redis 交互的指令。
    它会自动处理 Redis 客户端的可用性检查和通用的异常捕获。
    """
    @functools.wraps(func)
    async def wrapper(client, event, parts):
        if not redis_client.db:
            await event.reply("❌ 错误: Redis 客户端未初始化或连接失败。")
            return
        try:
            return await func(client, event, parts)
        except Exception as e:
            await event.reply(f"❌ 执行Redis指令时发生错误: {e}")
            format_and_log("SYSTEM", "Redis指令执行失败", {'指令': parts[0], '错误': str(e)})
    return wrapper

# --- 配置项 (保持不变) ---
CONFIG_WHITELIST = {'宗门': ('SECT_NAME', 'sect_name'),'药园播种': ('GARDEN_SOW_SEED', 'huangfeng_valley.garden_sow_seed'),}
TASK_RESET_CONFIG = {
    "闭关": {"job_id": common_tasks.TASK_ID_BIGUAN,"state_file": common_tasks.STATE_FILE_PATH_BIGUAN,"startup_func": common_tasks.check_biguan_startup},
    "点卯": {"job_id": common_tasks.TASK_ID_DIANMAO,"state_file": common_tasks.STATE_FILE_PATH_DIANMAO,"startup_func": common_tasks.check_dianmao_startup},
    "闯塔": {"job_id": [common_tasks.TASK_ID_CHUANG_TA_1, common_tasks.TASK_ID_CHUANG_TA_2],"state_file": common_tasks.STATE_FILE_PATH_CHUANG_TA,"startup_func": common_tasks.check_chuang_ta_startup},
    "药园": {"job_id": huangfeng_valley.TASK_ID_GARDEN,"state_file": None,"startup_func": huangfeng_valley.check_garden_startup},
    "引道": {"job_id": taiyi_sect.TASK_ID_YINDAO,"state_file": taiyi_sect.STATE_FILE_PATH_YINDAO,"startup_func": taiyi_sect.check_yindao_startup}
}
INVENTORY_FILE_PATH = f"{settings.DATA_DIR}/inventory.json"

async def _send_long_message(event, text: str, title: str = ""):
    max_length = 4000
    if len(text) <= max_length: await event.reply(text, parse_mode='md'); return
    full_message = f"{title}\n\n" if title else ""
    lines, current_part, part_num = text.split('\n'), "", 1
    for line in lines:
        if len(full_message + current_part + line + "\n") > max_length:
            await event.reply(full_message + current_part, parse_mode='md')
            current_part, part_num = "", part_num + 1
            full_message = f"{title} (第 {part_num} 部分)\n\n" if title else ""
        current_part += line + "\n"
    if current_part: await event.reply(full_message + current_part, parse_mode='md')

async def _cmd_restart(client, event, parts):
    await event.reply("✅ 好的，正在为您安排重启服务..."); await asyncio.sleep(1); sys.exit(0)

# --- 核心修改：为所有 Redis 指令应用装饰器 ---

@redis_command
async def _cmd_redis_status(client, event, parts):
    status_text = "🗄️ **Redis 连接状态**\n"
    if redis_client.db.ping():
        status_text += "  - `状态`: ✅ 连接成功\n"
        config, password = settings.REDIS_CONFIG, config.get('password')
        masked_pass = mask_string(password) if password else "未设置"
        status_text += f"  - `主机`: `{config.get('host')}`\n  - `端口`: `{config.get('port')}`\n  - `密码`: `{masked_pass}`\n  - `DB`: `{config.get('db')}`"
    else: status_text += "  - `状态`: ❌ 连接失败" # 理论上 ping 不会失败，因为装饰器已检查
    await event.reply(status_text, parse_mode='md')

@redis_command
async def _cmd_redis_type(client, event, parts):
    if len(parts) != 2: await event.reply(f"**用法**: `{settings.COMMAND_PREFIXES[0]}redis type <key>`"); return
    key_name = parts[1]
    key_type = redis_client.db.type(key_name)
    await event.reply(f"🔑 Key `{key_name}` 在 Redis 中的数据类型是: **{key_type}**")

@redis_command
async def _cmd_query_qa_db(client, event, parts):
    db_map = {"玄骨": settings.REDIS_CONFIG['xuangu_db_name'], "天机": settings.REDIS_CONFIG['tianji_db_name']}
    if len(parts) != 2 or parts[1] not in db_map: await event.reply(f"**用法**: `{settings.COMMAND_PREFIXES[0]}查询题库 <题库名>`\n**可选项**: `玄骨`, `天机`"); return
    db_key_name, redis_key = parts[1], db_map[parts[1]]
    qa_data = redis_client.db.hgetall(redis_key)
    if not qa_data: await event.reply(f"📚 **{db_key_name}** 知识库为空。"); return
    sorted_qa = sorted(qa_data.items())
    response_lines = [f"{i}. **问**: `{q}`\n   **答**: `{a}`" for i, (q, a) in enumerate(sorted_qa, 1)]
    title = f"📚 **{db_key_name}** 知识库 (共 {len(sorted_qa)} 条)"
    await _send_long_message(event, "\n\n".join(response_lines), title)

@redis_command
async def _cmd_modify_qa_db(client, event, parts):
    db_map = {"玄骨": settings.REDIS_CONFIG['xuangu_db_name'], "天机": settings.REDIS_CONFIG['tianji_db_name']}
    if len(parts) < 4: await event.reply(f"**用法**: `{settings.COMMAND_PREFIXES[0]}修改答案 <题库名> <题目ID> <新答案>`"); return
    db_key_name, item_id_str, new_answer_text = parts[1], parts[2], " ".join(parts[3:])
    if db_key_name not in db_map: await event.reply("❌ 错误: 无效的题库名。"); return
    try: item_id = int(item_id_str)
    except ValueError: await event.reply("❌ 错误: 题目ID必须是数字。"); return
    redis_key = db_map[db_key_name]
    qa_data = redis_client.db.hgetall(redis_key)
    if not qa_data: await event.reply(f"📚 **{db_key_name}** 知识库为空。"); return
    sorted_qa = sorted(qa_data.items())
    if not (1 <= item_id <= len(sorted_qa)): await event.reply(f"❌ 错误: 题目ID `{item_id}` 超出范围 (1-{len(sorted_qa)})。"); return
    question_to_modify, old_answer = sorted_qa[item_id - 1]
    redis_client.db.hset(redis_key, question_to_modify, new_answer_text)
    await event.reply(f"✅ 答案更新成功！\n\n**题库**: `{db_key_name}`\n**问题**: `{question_to_modify}`\n**旧**: `{old_answer}`\n**新**: `{new_answer_text}`", parse_mode='md')

@redis_command
async def _cmd_delete_qa_db(client, event, parts):
    db_map = {"玄骨": settings.REDIS_CONFIG['xuangu_db_name'], "天机": settings.REDIS_CONFIG['tianji_db_name']}
    if len(parts) != 3: await event.reply(f"**用法**: `{settings.COMMAND_PREFIXES[0]}删除答案 <题库名> <题目ID>`"); return
    db_key_name, item_id_str = parts[1], parts[2]
    if db_key_name not in db_map: await event.reply("❌ 错误: 无效的题库名。"); return
    try: item_id = int(item_id_str)
    except ValueError: await event.reply("❌ 错误: 题目ID必须是数字。"); return
    redis_key = db_map[db_key_name]
    qa_data = redis_client.db.hgetall(redis_key)
    if not qa_data: await event.reply(f"📚 **{db_key_name}** 知识库为空。"); return
    sorted_qa = sorted(qa_data.items())
    if not (1 <= item_id <= len(sorted_qa)): await event.reply(f"❌ 错误: 题目ID `{item_id}` 超出范围 (1-{len(sorted_qa)})。"); return
    question_to_delete, answer_to_delete = sorted_qa[item_id - 1]
    redis_client.db.hdel(redis_key, question_to_delete)
    await event.reply(f"🗑️ 问答已成功删除！\n\n**题库**: `{db_key_name}`\n**被删问题**: `{question_to_delete}`", parse_mode='md')

async def _cmd_set_config(client, event, parts):
    # ... (此函数内容未改变)
    prefix = settings.COMMAND_PREFIXES[0]
    if len(parts) == 1:
        available_keys = ' '.join([f"`{key}`" for key in CONFIG_WHITELIST.keys()])
        help_text = (f"**在线配置指令**\n\n"
                     f"**查看帮助**: `{prefix}设置`\n"
                     f"**查看当前值**: `{prefix}设置 <配置名>`\n"
                     f"**修改配置值**: `{prefix}设置 <配置名> <新值>`\n\n"
                     f"**`<配置名>` 可选项**:\n{available_keys}\n\n"
                     f"**注意**: 修改 `宗门` 等配置后，需要使用 `{prefix}重启` 指令才能完全生效。")
        await event.reply(help_text, parse_mode='md'); return
    config_name = parts[1]
    if config_name not in CONFIG_WHITELIST: await event.reply(f"❌ 错误: '{config_name}' 是一个无效或不允许在线修改的配置项。"); return
    settings_attr, yaml_key = CONFIG_WHITELIST[config_name]
    if len(parts) == 2:
        current_value = "未设置"
        if '.' in yaml_key:
            root_key, sub_key = yaml_key.split('.', 1)
            root_obj = getattr(settings, root_key.upper(), {})
            current_value = root_obj.get(sub_key, "未设置")
        else: current_value = getattr(settings, settings_attr, "未设置")
        await event.reply(f"当前 **{config_name}** 的配置值为: `{current_value}`", parse_mode='md'); return
    if len(parts) >= 3:
        new_value = ' '.join(parts[2:])
        root_key, sub_key = (yaml_key.split('.', 1) + [None])[:2] if '.' in yaml_key else (yaml_key, None)
        try:
            target_obj = getattr(settings, settings_attr, None)
            if isinstance(target_obj, bool): new_value = new_value.lower() in ['true', '1', 'yes', 'on', '开']
            elif isinstance(target_obj, int): new_value = int(new_value)
        except (ValueError, TypeError): await event.reply(f"❌ 错误: 提供的值 '{new_value}' 类型不正确。"); return
        response_msg = update_setting(root_key=root_key, sub_key=sub_key, value=new_value, success_message=f"**{config_name}** 配置已更新为 `{new_value}`")
        await event.reply(response_msg, parse_mode='md')

async def _cmd_reset_task(client, event, parts):
    # ... (此函数内容未改变)
    if len(parts) != 2 or parts[1] not in TASK_RESET_CONFIG:
        valid_tasks = ' '.join([f"`{task}`" for task in TASK_RESET_CONFIG.keys()])
        await event.reply(f"**用法**: `{settings.COMMAND_PREFIXES[0]}重置任务 <任务名>`\n**可重置的任务**: {valid_tasks}"); return
    task_name = parts[1]
    config = TASK_RESET_CONFIG[task_name]
    file_path, job_id, startup_func = config["state_file"], config["job_id"], config["startup_func"]
    progress_message = await event.reply(f"⏳ 正在准备重置 **{task_name}**...")
    try:
        if file_path and os.path.exists(file_path): os.remove(file_path); await progress_message.edit(f"⏳ 正在重置 **{task_name}**...\n- 状态文件已删除。")
        else: await progress_message.edit(f"⏳ 正在重置 **{task_name}**...\n- 无需删除状态文件。")
        await asyncio.sleep(1)
        job_ids_to_remove = job_id if isinstance(job_id, list) else [job_id]
        for j_id in job_ids_to_remove:
            if scheduler.get_job(j_id): scheduler.remove_job(j_id)
        await progress_message.edit(f"⏳ 正在重置 **{task_name}**...\n- 旧的调度计划已移除。"); await asyncio.sleep(1)
        await startup_func()
        await progress_message.edit(f"✅ **{task_name}** 任务已成功重置，并已根据逻辑重新调度或立即触发。")
    except Exception as e:
        await progress_message.edit(f"❌ 重置 **{task_name}** 任务时发生错误: `{e}`")
        format_and_log("SYSTEM", "任务重置失败", {'任务': task_name, '错误': str(e)}, level=logging.ERROR)

async def _cmd_view_inventory(client, event, parts):
    # ... (此函数内容未改变)
    inventory = read_json_state(INVENTORY_FILE_PATH)
    if not inventory: await event.reply("🎒 背包缓存为空或不存在。"); return
    items = [f"- `{name}` x {quantity}" for name, quantity in inventory.items()]
    await _send_long_message(event, "🎒 **当前背包缓存内容**:\n" + "\n".join(items))

def initialize_admin_commands(client):
    client.register_admin_command("重启", _cmd_restart, "🔄 重启助手服务。", category="系统管理")
    client.register_admin_command("查询redis", _cmd_redis_status, "🗄️ 检查Redis连接状态。", category="系统管理")
    client.register_admin_command("redis", _cmd_redis_type, "🩺 (调试) 查询Redis中指定Key的数据类型。", category="系统管理", aliases=["rdt"])
    client.register_admin_command("查询题库", _cmd_query_qa_db, "📚 查询指定知识库的全部内容。", category="系统管理")
    client.register_admin_command("修改答案", _cmd_modify_qa_db, "✍️ 根据ID修改知识库中的答案。", category="系统管理")
    client.register_admin_command("删除答案", _cmd_delete_qa_db, "🗑️ 根据ID删除知识库中的问答对。", category="系统管理")
    client.register_admin_command("设置", _cmd_set_config, "⚙️ 在线查看或修改部分安全配置。", category="系统管理")
    client.register_admin_command("重置任务", _cmd_reset_task, "🛠️ 智能重置任务状态并重新调度。", category="系统管理")
    client.register_admin_command("查看背包", _cmd_view_inventory, "🎒 查看当前缓存的背包内容。", category="系统管理")
