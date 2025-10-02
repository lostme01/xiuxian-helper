# -*- coding: utf-8 -*-
import yaml
import google.generativeai as genai
import os

CONFIG_FILE_PATH = 'config/prod.yaml'

def run_check():
    """
    连接 Google API，列出当前配置文件中所有 API Key 可用的模型。
    """
    print("--- 开始查询配置文件中所有 Gemini API Key 的可用模型 ---")

    # 1. 从 config/prod.yaml 文件加载 API Keys 列表
    try:
        with open(CONFIG_FILE_PATH, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        # --- 核心修改：读取 gemini_api_keys 列表 ---
        api_keys = config.get('exam_solver', {}).get('gemini_api_keys', [])
        if not api_keys or not isinstance(api_keys, list):
            print(f"\n❌ 错误: 未在 {CONFIG_FILE_PATH} 文件中找到 gemini_api_keys 列表。")
            return
    except FileNotFoundError:
        print(f"\n❌ 错误: 配置文件 {CONFIG_FILE_PATH} 未找到。")
        return
    except Exception as e:
        print(f"\n❌ 读取或解析配置文件时发生错误: {e}")
        return

    print(f"✅ 成功加载 {len(api_keys)} 个 API Key。开始逐一检查...")

    # 2. 遍历并检查每一个 Key
    for i, key in enumerate(api_keys):
        # 对Key进行脱敏处理，只显示前后几位
        masked_key = f"{key[:6]}...{key[-4:]}"
        print(f"\n--- [检查第 {i+1}/{len(api_keys)} 个 Key: {masked_key}] ---")
        
        try:
            genai.configure(api_key=key)
            
            found_model = False
            for m in genai.list_models():
                if 'generateContent' in m.supported_generation_methods:
                    print(f"  ✅ 可用模型: {m.name}")
                    found_model = True
            
            if not found_model:
                print(f"  ⚠️ 警告: 此 Key 未找到任何支持 'generateContent' 的可用模型。")
                print("     请检查您的 Google AI Studio 或 Google Cloud 项目配置。")

        except Exception as e:
            print(f"  ❌ API 调用失败: {e}")
            print("     请检查此 API Key 是否正确、是否已激活，以及网络连接是否正常。")

    print("\n--- 所有 Key 查询结束 ---")


if __name__ == "__main__":
    if not os.path.isdir('config'):
        print("❌ 错误：请在项目根目录中运行此脚本。")
    else:
        run_check()
