# -*- coding: utf-8 -*-
import asyncio
from app.core import Application

if __name__ == "__main__":
    app = Application()
    try:
        # 运行主应用
        asyncio.run(app.run())
    except KeyboardInterrupt:
        # [修改] 为 print 增加 flush=True 参数，确保立即输出
        print("\n检测到 Ctrl+C，正在优雅关闭...", flush=True)
        pass
    except SystemExit:
        pass
