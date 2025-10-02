# -*- coding: utf-8 -*-

# 这个文件用于存放全局的应用实例和核心组件，以解决循环导入问题。

_app_instance = None
_scheduler_instance = None

def set_application(app_instance):
    """由 app.core 在初始化时调用，用于设置全局实例。"""
    global _app_instance
    _app_instance = app_instance

def get_application():
    """由各个插件在需要时调用，用于获取全局实例。"""
    if _app_instance is None:
        raise RuntimeError("Application has not been initialized yet.")
    return _app_instance

def set_scheduler(scheduler_instance):
    """由 app.core 在初始化时调用，用于设置全局调度器实例。"""
    global _scheduler_instance
    _scheduler_instance = scheduler_instance

def get_scheduler():
    """由需要访问调度器的模块调用。"""
    if _scheduler_instance is None:
        raise RuntimeError("Scheduler has not been initialized yet.")
    return _scheduler_instance
