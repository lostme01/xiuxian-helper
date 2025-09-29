# -*- coding: utf-8 -*-
import os
import asyncio
import re
import yaml
import google.generativeai as genai

# --- 内置的测试题目 ---
TEST_QUESTION = "以下哪件物品，不属于“结丹三宝”？"
TEST_OPTIONS = {
    "A": "天火液",
    "B": "凝魂丹",
    "C": "筑基丹",
    "D": "三转重元丹"
}
CONFIG_FILE_PATH = 'config/prod.yaml'

async def run_test():
    """
    执行一次独立的 Gemini API 调用测试，使用最终选定的模型和配置。
    """
    # --- 最终配置 ---
    # 根据您的可用列表和决定，我们使用 gemini-1.5-pro
    # 修正：根据您的最新指示和列表，我们使用 gemini-2.5-pro
    model_name = 'gemini-2.5-pro'
    
    print(f"--- 开始 Gemini API 最终测试 (模型: {model_name}) ---")

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

    print("✅ API Key 从 prod.yaml 加载成功。")

    try:
        # 2. 配置 Gemini
        genai.configure(api_key=api_key)
        
        # 使用字典格式禁用思考/工具调用功能
        tool_config = {
            "function_calling_config": {
                "mode": "none"
            }
        }
        
        model = genai.GenerativeModel(model_name=model_name, tool_config=tool_config)
        print(f"✅ Gemini 模型 ({model_name}) 初始化成功 (思考功能已禁用)。")

        # 3. 构建 Prompt
        prompt = (
            f"请根据以下单项选择题，仅返回正确答案的字母（A, B, C, D）。不要解释。\n"
            f"问题：{TEST_QUESTION}\n"
            f"A. {TEST_OPTIONS['A']}\n"
            f"B. {TEST_OPTIONS['B']}\n"
            f"C. {TEST_OPTIONS['C']}\n"
            f"D. {TEST_OPTIONS['D']}"
        )
        print("\n--- 正在发送以下 Prompt 给 API ---")
        print(prompt)
        print("---------------------------------")

        # 4. 发送异步请求
        print("\n⏳ 正在请求 API，请稍候...")
        response = await model.generate_content_async(prompt)
        
        # 5. 处理并打印结果
        print("✅ API 成功返回响应！")
        print("\n--- API 原始响应文本 ---")
        print(response.text)
        print("--------------------------")

        parsed_answer = re.sub(r'[^A-D]', '', response.text.upper())
        if parsed_answer in TEST_OPTIONS:
            print(f"\n✅ 解析出的最终答案: {parsed_answer} ({TEST_OPTIONS[parsed_answer]})")
        else:
            print(f"\n⚠️ 警告: 未能从AI响应中解析出有效的选项字母 (A,B,C,D)。")

    except Exception as e:
        print(f"\n❌ API 调用过程中发生错误: {e}")

    print("\n--- 测试结束 ---")


if __name__ == "__main__":
    asyncio.run(run_test())

