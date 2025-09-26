# -*- coding: utf-8 -*-
import asyncio
from app.core import Application

if __name__ == "__main__":
    app = Application()
    try:
        # 运行主应用
        asyncio.run(app.run())
    except KeyboardInterrupt:
        # 当用户按下 Ctrl+C 时，asyncio.run 会抛出 KeyboardInterrupt
        # 我们在这里捕获它，但不做任何事 (pass)
        # 因为 app.run() 的 finally 块已经处理了关闭日志
        # 这样程序就会安静地退出，不会再打印长长的错误信息
        pass
