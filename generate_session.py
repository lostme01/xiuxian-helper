# -*- coding: utf-8 -*-
import asyncio
import os
from config import settings
from telethon import TelegramClient

async def main():
    print("--- 标准会话文件生成器 (v3.1) ---")
    print(f"此脚本将在 {settings.DATA_DIR}/ 目录下创建标准的 .session 文件。")

    os.makedirs(settings.DATA_DIR, exist_ok=True)

    client = TelegramClient(
        settings.SESSION_FILE_PATH, 
        settings.API_ID, 
        settings.API_HASH
    )

    try:
        print("\n正在连接到 Telegram...")
        await client.start()
        
        me = await client.get_me()
        print(f"\n✅ 登录成功! 您好, {me.first_name}.")
        print(f"✅ 会话文件已成功创建/更新于: {settings.SESSION_FILE_PATH}")
        print("\n现在您可以关闭此脚本，并运行 ./debug.sh 或 ./start.sh 启动主程序了。")

    except Exception as e:
        print(f"\n❌ 发生错误: {e}")
    finally:
        if client.is_connected():
            await client.disconnect()
            print("\n客户端已断开连接。")

if __name__ == "__main__":
    if not os.path.isdir('config'):
        print("错误：请在项目根目录 (tg-game-helper/) 中运行此脚本。")
    else:
        asyncio.run(main())
