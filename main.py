# -*- coding: utf-8 -*-
import asyncio
from app.core import Application

if __name__ == "__main__":
    app = Application()
    try:
        # 运行主应用
        asyncio.run(app.run())
    except KeyboardInterrupt:
        # --- 修改：增加友好提示 ---
        print("\n检测到 Ctrl+C，正在优雅关闭...")
        pass
    except SystemExit:
        pass
