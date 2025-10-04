from app.context import get_application
from .logic import service_logic

async def _cmd_restart(event, parts):
    await get_application().client.reply_to_admin(event, await service_logic.logic_restart_service())

async def _cmd_task_list(event, parts):
    await get_application().client.reply_to_admin(event, await service_logic.logic_get_task_list())
    
async def _cmd_reload_tasks(event, parts):
    await get_application().client.reply_to_admin(event, await service_logic.logic_reload_tasks())

def initialize(app):
    app.register_command(
        name="重启", handler=_cmd_restart, help_text="🔄 重启服务", category="系统",
        usage="🔄 **重启助手服务**\n\n该指令会使程序优雅退出。如果使用 Docker 或其他守护进程部署，程序将自动重启。"
    )
    app.register_command(
        name="任务列表", handler=_cmd_task_list, help_text="🗓️ 查询计划任务", category="系统", aliases=['tasks']
    )
    app.register_command(
        name="重载任务", handler=_cmd_reload_tasks, help_text="🔄 重载周期性任务", category="系统", aliases=['reloadtasks'],
        usage="""🔄 **重载所有计划任务**
**说明**: 当您在 `prod.yaml` 文件中修改了任何与**周期任务调度**相关的设置后，执行此命令可使新配置生效，无需重启整个程序。"""
    )
