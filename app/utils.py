# -*- coding: utf-8 -*-
import re
import json
import logging
from datetime import timedelta
from app.logger import format_and_log

def parse_cooldown_time(text: str) -> timedelta | None:
    """
    从游戏机器人的回复文本中解析出冷却时间。
    成功则返回一个 timedelta 对象，失败则返回 None。
    """
    cleaned_text = text.replace('**', '')

    # 优先匹配最复杂的格式: "X小时Y分钟"
    if match := re.search(r'(\d+)\s*小时\s*(\d+)\s*分钟', cleaned_text):
        return timedelta(hours=int(match.group(1)), minutes=int(match.group(2)))
    
    # 新增：匹配 "X分钟Y秒"
    if match := re.search(r'(\d+)\s*分钟\s*(\d+)\s*秒', cleaned_text):
        return timedelta(minutes=int(match.group(1)), seconds=int(match.group(2)))

    # 单独匹配 "X小时"
    if match := re.search(r'(\d+)\s*小时', cleaned_text):
        return timedelta(hours=int(match.group(1)))
        
    # 单独匹配 "Y分钟" 或 "Y分"
    if match := re.search(r'(\d+)\s*分钟', cleaned_text):
        return timedelta(minutes=int(match.group(1)))
    if match := re.search(r'(\d+)\s*分(?!\s*钟)', cleaned_text):
        return timedelta(minutes=int(match.group(1)))
    
    # 新增：单独匹配 "Z秒"
    if match := re.search(r'(\d+)\s*秒', cleaned_text):
        return timedelta(seconds=int(match.group(1)))
    
    return None

def write_state(file_path: str, content: str):
    """通用状态文件写入函数 (文本)"""
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
    except Exception as e:
        format_and_log("SYSTEM", "状态写入失败", {'文件': file_path, '错误': str(e)}, level=logging.ERROR)

def read_state(file_path: str) -> str | None:
    """通用状态文件读取函数 (文本)"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read().strip()
    except FileNotFoundError:
        return None
    except Exception as e:
        format_and_log("SYSTEM", "状态读取失败", {'文件': file_path, '错误': str(e)}, level=logging.ERROR)
        return None

def write_json_state(file_path: str, data: dict):
    """通用状态文件写入函数 (JSON)"""
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        format_and_log("SYSTEM", "JSON状态写入失败", {'文件': file_path, '错误': str(e)}, level=logging.ERROR)

def read_json_state(file_path: str) -> dict | None:
    """通用状态文件读取函数 (JSON)"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except json.JSONDecodeError:
        format_and_log("SYSTEM", "JSON状态读取失败", {'文件': file_path, '错误': '文件内容损坏'}, level=logging.ERROR)
        return None
    except Exception as e:
        format_and_log("SYSTEM", "JSON状态读取失败", {'文件': file_path, '错误': str(e)}, level=logging.ERROR)
        return None

def parse_inventory_text(reply_text: str) -> dict:
    """从储物袋回复文本中解析物品"""
    inventory = {}
    matches = re.findall(r'-\s*(.*?)\s*x\s*(\d+)', reply_text)
    for match in matches:
        inventory[match[0]] = int(match[1])
    return inventory

