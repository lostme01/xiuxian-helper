# -*- coding: utf-8 -*-
import json
import os
import sys
import redis
from config import settings

def colored_text(text, color_code):
    """用于在终端显示带颜色的文本"""
    return f"\033[{color_code}m{text}\033[0m"

def get_redis_connection(manual_host=None):
    """建立并测试 Redis 连接"""
    host = manual_host if manual_host else settings.REDIS_CONFIG.get('host', 'localhost')
    port = settings.REDIS_CONFIG.get('port', 6379)
    password = settings.REDIS_CONFIG.get('password')
    db_num = settings.REDIS_CONFIG.get('db', 0)

    print("-" * 50)
    print(f"正在尝试连接到 Redis 服务器...")
    print(f"  - Host: {colored_text(host, '1;36')}") # 青色
    print(f"  - Port: {port}")
    
    try:
        r = redis.Redis(
            host=host,
            port=port,
            password=password,
            db=db_num,
            decode_responses=True,
            socket_connect_timeout=5
        )
        r.ping()
        print(colored_text("✅ 连接成功！", '1;32')) # 绿色
        return r
    except Exception as e:
        print(colored_text(f"❌ 连接失败: {e}", '1;31')) # 红色
        return None

def migrate(redis_db, json_path, redis_key):
    """迁移单个知识库的函数"""
    print("-" * 50)
    print(f"处理知识库: {colored_text(redis_key, '1;33')}") # 黄色

    if not os.path.exists(json_path):
        print(f"源文件 {json_path} 不存在，跳过。")
        return

    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data_from_json = json.load(f)
        
        if not data_from_json:
            print("源文件为空，无需迁移。")
            return
            
        json_count = len(data_from_json)
        redis_count = redis_db.hlen(redis_key)
        
        print(f"源文件 ({json_path}) 中包含 {colored_text(json_count, '1;32')} 条记录。")
        print(f"当前 Redis ({redis_key}) 中已有 {colored_text(redis_count, '1;32')} 条记录。")

        user_input = input("确认要用源文件内容【覆盖】Redis中的数据吗？(y/n): ").lower()
        if user_input == 'y':
            print("正在写入数据...")
            pipe = redis_db.pipeline()
            pipe.delete(redis_key) # 先清空旧数据
            pipe.hset(redis_key, mapping=data_from_json)
            pipe.execute()
            final_count = redis_db.hlen(redis_key)
            print(colored_text(f"✅ 迁移成功！现在 Redis ({redis_key}) 中有 {final_count} 条记录。", '1;32'))
        else:
            print("操作已取消。")
            
    except Exception as e:
        print(colored_text(f"迁移过程中发生错误: {e}", '1;31'))

if __name__ == "__main__":
    print("=" * 50)
    print(colored_text("  TG 助手知识库迁移工具 (v2.0)", '1;35')) # 紫色
    print("=" * 50)
    
    # 允许用户手动输入IP，如果留空则使用配置文件中的
    host_from_config = settings.REDIS_CONFIG.get('host', 'localhost')
    manual_ip = input(f"请输入 Redis 服务器 IP 地址 [默认为: {host_from_config}]: ").strip()
    
    redis_connection = get_redis_connection(manual_ip)
    
    if redis_connection:
        migrate(redis_connection, f"{settings.DATA_DIR}/qa_database.json", settings.REDIS_CONFIG['xuangu_db_name'])
        migrate(redis_connection, f"{settings.DATA_DIR}/tianji_qa.json", settings.REDIS_CONFIG['tianji_db_name'])
        print("-" * 50)
        print(colored_text("所有任务已完成。", "1;35"))
    else:
        print(colored_text("无法连接到 Redis，迁移中止。", "1;31"))
        sys.exit(1)
