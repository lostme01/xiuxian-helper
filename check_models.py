# -*- coding: utf-8 -*-
import yaml
import google.generativeai as genai
import os

CONFIG_FILE_PATH = 'config/prod.yaml'

def run_check():
    """
    连接 Google API，列出当前 API Key 可用的所有模型。
    """
    print("--- 开始查询当前 API Key 可用的 Gemini 模型 ---")

    # 1. 从 config/prod.yaml 文件加载 API Key
    try:
        with open(CONFIG_FILE_PATH, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        api_key = config.get('exam_solver', {}).get('gemini_api_key')
        if not api_key:
            print(f"\n❌ 错误: 未在 {CONFIG_FILE_PATH} 文件中找到 gemini_api_key。")
            return
    except FileNotFoundError:
        print(f"\n❌ 错误: 配置文件 {CONFIG_FILE_PATH} 未找到。")
        return
    except Exception as e:
        print(f"\n❌ 读取或解析配置文件时发生错误: {e}")
        return

    print("✅ API Key 加载成功。正在连接 Google...")

    try:
        # 2. 配置并查询模型
        genai.configure(api_key=api_key)
        
        print("\n--- 您当前 API Key 可用的模型列表 (支持 generateContent) ---")
        found_model = False
        for m in genai.list_models():
            # 我们只关心支持生成内容的模型
            if 'generateContent' in m.supported_generation_methods:
                print(f"✅ 模型名称: {m.name}")
                found_model = True
        
        if not found_model:
            print("\n⚠️ 警告: 未找到任何支持 'generateContent' 的可用模型。")
            print("   请检查您的 Google AI Studio 或 Google Cloud 项目配置，确保已启用相关 API 服务。")

    except Exception as e:
        print(f"\n❌ API 调用过程中发生错误: {e}")
        print("   请检查您的 API Key 是否正确、是否已激活，以及网络连接是否正常。")

    print("\n--- 查询结束 ---")


if __name__ == "__main__":
    run_check()

