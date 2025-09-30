#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Oopz配置文件
包含所有固定的常量参数
"""

import winreg
import base64
import json

# 固定的请求头参数
OOPZ_CONFIG = {
    # 应用版本号（固定）
    "app_version": "69514",

    # 渠道（固定）
    "channel": "Web",

    # 设备ID（动态从注册表读取）
    "device_id": None,
    # 用户ID（动态从注册表读取）
    "person_uid": None,

    # JWT Token（动态从注册表读取）
    "jwt_token": None,

    # 平台信息（固定）
    "platform": "windows",

    # 是否为Web端（固定）
    "web": True,

    # API基础URL
    "base_url": "https://gateway.oopz.cn",

    # 默认的区域和频道ID（可根据需要修改）
    "default_area": "",
    "default_channel": ""
}



# Web API 认证配置
WEB_AUTH = {
    "username": "admin",  # 修改为你的用户名
    "password": "oopz2025",  # 修改为你的密码
    "jwt_secret": "oopz_music_bot_secret_key_2025",  # 修改为随机生成的密钥
    "jwt_algorithm": "HS256",
    "token_expire_hours": 24
}


# Redis 配置
REDIS_CONFIG = {
    "host": "127.0.0.1",  # Redis 服务器地址
    "port": 6379,  # Redis 端口
    "password": "",  # Redis 密码（如果有）
    "db": 0,
    "decode_responses": True
}


# HTTP请求头模板（固定的浏览器请求头）
DEFAULT_HEADERS = {
    'Accept': '*/*',
    'Accept-Encoding': 'gzip, deflate, br, zstd',
    'Accept-Language': 'zh-CN,zh;q=0.9',
    'Cache-Control': 'no-cache',
    'Content-Type': 'application/json;charset=utf-8',
    'Origin': 'https://web.oopz.cn',
    'Pragma': 'no-cache',
    'Priority': 'u=1, i',
    'Sec-Ch-Ua': '"Chromium";v="140", "Not=A?Brand";v="24", "Google Chrome";v="140"',
    'Sec-Ch-Ua-Mobile': '?0',
    'Sec-Ch-Ua-Platform': '"Windows"',
    'Sec-Fetch-Dest': 'empty',
    'Sec-Fetch-Mode': 'cors',
    'Sec-Fetch-Site': 'same-site',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36'
}

NETEASE_CLOUD = {
    "base_url": "",
    "cookie": "",
    "default_channel": "0"
}

QQ_MUSIC = {
    "base_url": "",
}

AudioService = {
    "base_url": ""
}

BILIBILI = {
    "base_url": ""
}


# 快捷访问函数
def get_config(key: str = None):
    """获取配置项"""
    if key is None:
        return OOPZ_CONFIG
    return OOPZ_CONFIG.get(key)


def get_person_uid():
    """获取用户ID"""
    # 如果配置中没有数据，尝试从注册表读取
    if not OOPZ_CONFIG["person_uid"]:
        update_config_with_login_data()
    return OOPZ_CONFIG["person_uid"]


def get_jwt_token():
    """获取JWT Token"""
    # 如果配置中没有数据，尝试从注册表读取
    if not OOPZ_CONFIG["jwt_token"]:
        update_config_with_login_data()
    return OOPZ_CONFIG["jwt_token"]


def get_device_id():
    """获取设备ID"""
    # 如果配置中没有数据，尝试从注册表读取
    if not OOPZ_CONFIG["device_id"]:
        update_config_with_login_data()
    return OOPZ_CONFIG["device_id"]


def get_default_area():
    """获取默认区域ID"""
    return OOPZ_CONFIG["default_area"]


def get_default_channel():
    """获取默认频道ID"""
    return OOPZ_CONFIG["default_channel"]


# 如果需要修改配置，可以在这里添加新的值
# 例如：如果要使用不同的区域或频道，可以修改这些值
CUSTOM_CONFIG = {
    # "default_area": "你的区域ID",
    # "default_channel": "你的频道ID",
}


def quick_read_oopz_login():
    """快速读取 Oopz 登录数据"""
    try:
        # 直接读取注册表
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"SOFTWARE\Oopz\OopzData", 0, winreg.KEY_READ) as key:
            login_data, _ = winreg.QueryValueEx(key, "login")

            # 解码 Base64
            decoded = base64.b64decode(login_data)

            # 解析 JSON
            json_data = json.loads(decoded.decode('utf-8'))

            return json_data

    except Exception as e:
        print(f"读取失败: {e}")
        return None


def get_dynamic_config():
    """获取动态配置数据"""
    login_data = quick_read_oopz_login()
    if login_data:
        return {
            "device_id": login_data.get("deviceId"),
            "person_uid": login_data.get("uid"),
            "jwt_token": login_data.get("signature"),
            "base_url": login_data.get("endpoint", "https://gateway.oopz.cn")
        }
    return None


def update_config_with_login_data():
    """使用登录数据更新配置"""
    dynamic_config = get_dynamic_config()
    if dynamic_config:
        OOPZ_CONFIG.update(dynamic_config)
        return True
    return False


# 合并自定义配置
OOPZ_CONFIG.update(CUSTOM_CONFIG)

# 在模块导入时自动更新配置
update_config_with_login_data()

# 测试函数
if __name__ == "__main__":
    data = quick_read_oopz_login()
    if data:
        print("登录数据:")
        print(json.dumps(data, indent=2, ensure_ascii=False))

        # 测试动态配置更新
        if update_config_with_login_data():
            print("\n配置更新成功:")
            print(f"设备ID: {get_device_id()}")
            print(f"用户ID: {get_person_uid()}")
            print(f"JWT Token: {get_jwt_token()}")
        else:
            print("配置更新失败")
    else:
        print("无法读取登录数据")


