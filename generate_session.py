# -*- coding: utf-8 -*-
import asyncio
import os
from config import settings

async def main():
    print("--- 增强型会话文件生成器 (v4.0 - 带强制同步) ---")
    print(f"此脚本将在 {settings.DATA_DIR}/ 目录下创建全新的 .session 文件。")

    session_path = settings.SESSION_FILE_PATH
    if os.path.exists(session_path):
        print(f"\n警告: 发现旧的会话文件 '{session_path}'，将进行删除以确保全新登录。")
        os.remove(session_path)

    os.makedirs(settings.DATA_DIR, exist_ok=True)

    client = TelethonTgClient(
        session_path, 
        settings.API_ID, 
        settings.API_HASH
    )

    try:
        print("\n[步骤 1/2] 正在连接并登录 Telegram...")
        # 登录过程需要您输入手机号、验证码、两步验证密码等
        await client.start()
        
        me = await client.get_me()
        print(f"\n✅ 登录成功! 您好, {me.first_name}.")

        print("\n[步骤 2/2] 正在强制同步对话列表以确保会话激活...")
        dialog_count = 0
        async for dialog in client.iter_dialogs(limit=20): # 获取最近20个对话
            dialog_count += 1
            print(f"  - 同步: {dialog.name}")
        
        print(f"\n✅ 同步完成! 共处理 {dialog_count} 个对话。")
        print(f"✅ 会话文件已成功创建并激活于: {session_path}")
        print("\n现在您可以关闭此脚本，并运行 ./debug.sh 启动主程序了。")

    except Exception as e:
        print(f"\n❌ 发生错误: {e}")
    finally:
        if client.is_connected():
            await client.disconnect()
            print("\n客户端已断开连接。")

if __name__ == "__main__":
    from telethon import TelegramClient as TelethonTgClient
    if not os.path.isdir('config'):
        print("错误：请在项目根目录 (tg-game-helper/) 中运行此脚本。")
    else:
        asyncio.run(main())

