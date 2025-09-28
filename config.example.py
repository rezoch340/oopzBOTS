#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Oopz配置文件
包含所有固定的常量参数
"""

# 固定的请求头参数
OOPZ_CONFIG = {
    # 应用版本号（固定）
    "app_version": "69514",

    # 渠道（固定）
    "channel": "Web",

    # 设备ID（固定）
    "device_id": "",

    # 用户ID（固定）
    "person_uid": "",

    # JWT Token（固定，服务器下发的长期有效token）
    "jwt_token": "",

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
    return OOPZ_CONFIG["person_uid"]


def get_jwt_token():
    """获取JWT Token"""
    return OOPZ_CONFIG["jwt_token"]


def get_device_id():
    """获取设备ID"""
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

# 合并自定义配置
OOPZ_CONFIG.update(CUSTOM_CONFIG)
