# -*- coding: utf-8 -*-
import asyncio
from app.core import Application

if __name__ == "__main__":
    app = Application()
    try:
        # 运行主应用
        asyncio.run(app.run())
    except KeyboardInterrupt:
        # 当用户按下 Ctrl+C 时，程序会安静地退出
        pass
    # *** 修复：捕获 sys.exit() 抛出的 SystemExit 异常 ***
    # 这样，当执行 `,重启` 时，程序也能安静地退出，不再打印长长的错误信息
    except SystemExit:
        pass
