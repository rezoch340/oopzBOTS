#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简化版Oopz消息发送器
使用固定配置，无需手动传入参数
"""
from PIL import Image
import io
import os
import hashlib
import base64
import uuid
import time
import json
import random
import requests
from typing import Dict, Optional
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.backends import default_backend

# 导入配置
from config import OOPZ_CONFIG, DEFAULT_HEADERS


def get_image_info(file_path: str):
    """获取图片宽高和文件大小"""
    with Image.open(file_path) as img:
        width, height = img.size
    file_size = os.path.getsize(file_path)
    return width, height, file_size


class SimpleClientMessageIdGenerator:
    """简化版客户端消息ID生成器"""

    def __init__(self):
        self.counter = 0

    def generate(self) -> str:
        """生成15位客户端消息ID（模拟真实格式）"""
        # 基于微秒时间戳生成15位ID
        timestamp_us = int(time.time() * 1000000)
        base_id = timestamp_us % 10000000000000  # 取13位
        random_suffix = random.randint(10, 99)  # 2位随机数
        client_id = base_id * 100 + random_suffix
        return str(client_id)


class SimpleSigner:
    """简化版签名器"""

    def __init__(self):
        self.private_key = self._create_test_key()
        self.id_generator = SimpleClientMessageIdGenerator()

    def _create_test_key(self):
        """加载真实RSA私钥"""
        try:
            from private_key import get_private_key
            return get_private_key()
        except ImportError:
            print("⚠️  private_key.py文件不存在，使用测试私钥")
            return rsa.generate_private_key(
                public_exponent=65537,
                key_size=2048,
                backend=default_backend()
            )

    def generate_request_id(self) -> str:
        """生成请求ID"""
        return str(uuid.uuid4())

    def generate_timestamp(self) -> str:
        """生成时间戳（毫秒）"""
        return str(int(time.time() * 1000))

    def generate_message_timestamp(self) -> str:
        """生成消息时间戳（微秒）"""
        return str(int(time.time() * 1000000))

    def generate_client_message_id(self) -> str:
        """生成客户端消息ID"""
        return self.id_generator.generate()

    def sign_data(self, data: str) -> str:
        """RSA签名 - 尝试PSS算法"""
        data_bytes = data.encode('utf-8')
        signature = self.private_key.sign(
            data_bytes,
            padding.PKCS1v15(),
            hashes.SHA256()
        )
        return base64.b64encode(signature).decode('utf-8')

    def create_oopz_headers(self, url_path: str, body_str: str) -> Dict[str, str]:
        """创建Oopz签名请求头（使用固定配置）"""
        import hashlib

        # 生成动态参数
        request_id = self.generate_request_id()
        timestamp = self.generate_timestamp()

        # 🎯 正确的签名方法（通过JS日志分析得出）：
        # 1. URL路径 + 请求体 -> MD5哈希
        # 2. MD5哈希 + 时间戳 -> 最终签名数据
        # 3. RSA签名最终数据
        hash_input = url_path + body_str
        md5_hash = hashlib.md5(hash_input.encode('utf-8')).hexdigest()
        sign_data = md5_hash + timestamp
        signature = self.sign_data(sign_data)
        # 使用配置中的固定参数
        return {
            'Oopz-Sign': signature,
            'Oopz-Request-Id': request_id,
            'Oopz-Time': timestamp,
            'Oopz-App-Version-Number': OOPZ_CONFIG["app_version"],
            'Oopz-Channel': OOPZ_CONFIG["channel"],
            'Oopz-Device-Id': OOPZ_CONFIG["device_id"],
            'Oopz-Platform': OOPZ_CONFIG["platform"],
            'Oopz-Web': str(OOPZ_CONFIG["web"]).lower(),
            'Oopz-Person': OOPZ_CONFIG["person_uid"],
            'Oopz-Signature': OOPZ_CONFIG["jwt_token"]
        }


class SimpleOopzSender:
    """简化版Oopz消息发送器"""

    def __init__(self):
        """初始化发送器（无需任何参数）"""
        self.signer = SimpleSigner()
        self.session = requests.Session()

        # 设置固定的HTTP请求头
        self.session.headers.update(DEFAULT_HEADERS)

        print("✅ Oopz消息发送器已初始化")
        print(f"👤 用户: {OOPZ_CONFIG['person_uid']}")
        print(f"📱 设备: {OOPZ_CONFIG['device_id']}")
        print(f"🌐 渠道: {OOPZ_CONFIG['channel']}")

    def send_message(self,
                     text: str,
                     area: str = None,
                     channel: str = None,
                     **kwargs) -> requests.Response:
        """
        发送消息（简化版）

        Args:
            text: 消息内容
            area: 区域ID（可选，默认使用配置中的值）
            channel: 频道ID（可选，默认使用配置中的值）
            **kwargs: 其他消息参数

        Returns:
            HTTP响应对象
        """
        # 使用默认值或传入的值
        area = area or OOPZ_CONFIG["default_area"]
        channel = channel or OOPZ_CONFIG["default_channel"]

        # 生成消息ID和时间戳
        client_message_id = self.signer.generate_client_message_id()
        message_timestamp = self.signer.generate_message_timestamp()

        # 构建消息数据
        message_data = {
            "area": area,
            "channel": channel,
            "target": kwargs.get("target", ""),
            "clientMessageId": client_message_id,
            "timestamp": message_timestamp,
            "isMentionAll": kwargs.get("isMentionAll", False),
            "mentionList": kwargs.get("mentionList", []),
            "styleTags": kwargs.get("styleTags", []),
            "referenceMessageId": kwargs.get("referenceMessageId", None),
            "animated": kwargs.get("animated", False),
            "displayName": kwargs.get("displayName", ""),
            "duration": kwargs.get("duration", 0),
            "text": text,
            "attachments": kwargs.get("attachments", [])
        }

        # 转换为JSON
        body_str = json.dumps(message_data, separators=(',', ':'), ensure_ascii=False)

        # 生成Oopz签名头
        url_path = "/im/session/v1/sendGimMessage"
        oopz_headers = self.signer.create_oopz_headers(url_path, body_str)

        # 合并请求头
        headers = self.session.headers.copy()
        headers.update(oopz_headers)

        # 构建完整URL
        url = OOPZ_CONFIG["base_url"] + url_path

        print(f"📤 发送消息: {text}")
        print(f"🆔 消息ID: {client_message_id}")
        print(f"📍 区域: {area}, 频道: {channel}")

        # 发送HTTP请求
        try:
            # 🔧 修复编码问题：确保请求体使用 UTF-8 编码
            response = self.session.post(url, headers=headers, data=body_str.encode('utf-8'))

            print(f"📥 响应状态: {response.status_code}")
            if response.text:
                print(f"📄 响应内容: {response.text}\n")

            return response

        except Exception as e:
            print(f"❌ 发送失败: {e}\n")
            raise

    def send_to_default(self, text: str) -> requests.Response:
        """发送到默认频道（最简单的方式）"""
        return self.send_message(text)

    def upload_file(self, file_path: str, file_type: str = "IMAGE", ext: str = ".webp") -> dict:
        """
        上传文件到 Oopz (先获取 signedUploadUrl，再 PUT 上传)
        Args:
            file_path: 本地文件路径
            file_type: 文件类型 (IMAGE / VIDEO / AUDIO)
            ext: 文件后缀
        Returns:
            dict: { "fileKey": str, "url": str }
        """
        url_path = "/rtc/v1/cos/v1/signedUploadUrl"
        url = OOPZ_CONFIG["base_url"] + url_path
        body = {"type": file_type, "ext": ext}

        # 转换为 JSON
        body_str = json.dumps(body, separators=(',', ':'), ensure_ascii=False)
        headers = self.session.headers.copy()
        headers.update(self.signer.create_oopz_headers(url_path, body_str))

        # 1. 获取 uploadUrl
        resp = self.session.put(url, headers=headers, data=body_str.encode('utf-8'))
        if resp.status_code != 200:
            raise Exception(f"获取上传URL失败: {resp.text}")

        resp_json = resp.json()
        print(resp_json)
        upload_url = resp_json["data"]["uploadUrl"]
        file_key = resp_json["data"]["fileKey"]

        # 2. 上传文件 (PUT)
        with open(file_path, "rb") as f:
            put_resp = requests.put(upload_url, data=f, headers={"Content-Type": "application/octet-stream"})
        if put_resp.status_code not in (200, 201):
            raise Exception(f"文件上传失败: {put_resp.text}")

        return {"fileKey": file_key, "url": upload_url.split("?")[0]}

    def send_multiple(self, messages: list, interval: float = 1.0):
        """批量发送消息"""
        print(f"📦 准备发送 {len(messages)} 条消息...")

        results = []
        for i, message in enumerate(messages, 1):
            print(f"\n[{i}/{len(messages)}] 发送中...")

            try:
                response = self.send_to_default(message)
                results.append({
                    'message': message,
                    'status_code': response.status_code,
                    'success': response.status_code == 200
                })

                if i < len(messages):  # 不是最后一条消息
                    print(f"⏳ 等待 {interval} 秒...")
                    time.sleep(interval)

            except Exception as e:
                print(f"💥 发送失败: {e}")
                results.append({
                    'message': message,
                    'status_code': None,
                    'success': False,
                    'error': str(e)
                })

        # 统计结果
        success_count = sum(1 for r in results if r['success'])
        print(f"\n📊 发送完成: {success_count}/{len(messages)} 成功")

        return results

    def upload_and_send_image(sender, file_path, text=""):
        # 自动检测宽高 & 文件大小
        width, height, file_size = get_image_info(file_path)

        # 1. 调 Oopz 获取 signedUrl
        url_path = "/rtc/v1/cos/v1/signedUploadUrl"
        url = OOPZ_CONFIG["base_url"] + url_path
        body = {"type": "IMAGE", "ext": os.path.splitext(file_path)[1]}
        body_str = json.dumps(body, separators=(',', ':'), ensure_ascii=False)

        headers = sender.session.headers.copy()
        headers.update(sender.signer.create_oopz_headers(url_path, body_str))

        resp = sender.session.put(url, headers=headers, data=body_str.encode('utf-8'))
        resp.raise_for_status()
        data = resp.json()["data"]

        signed_url = data["signedUrl"]
        file_key = data["file"]
        cdn_url = data["url"]

        # 2. 上传文件
        with open(file_path, "rb") as f:
            put_resp = requests.put(signed_url, data=f, headers={"Content-Type": "application/octet-stream"})
        put_resp.raise_for_status()

        # 3. 构造消息并发送
        attachments = [{
            "fileKey": file_key,
            "url": cdn_url,
            "width": width,
            "height": height,
            "fileSize": file_size,
            "hash": "",
            "animated": False,
            "displayName": "",
            "attachmentType": "IMAGE"
        }]

        msg_text = f"![IMAGEw{width}h{height}]({file_key})"
        if text:
            msg_text += f"\n{text}"

        return sender.send_message(text=msg_text, attachments=attachments)

    def upload_file_from_url(self, image_url: str):
        """
        从网络 URL 下载并上传图片到 Oopz，返回附件信息（不落地）
        """
        try:
            # 1. 下载图片到内存
            resp = requests.get(image_url, stream=True)
            resp.raise_for_status()
            image_bytes = resp.content

            # 2. 解析宽高 & 文件大小（内存操作）
            img = Image.open(io.BytesIO(image_bytes))
            width, height = img.size
            file_size = len(image_bytes)
            ext = "." + img.format.lower()  # ".webp" / ".png" / ".jpg"

            # 计算 md5
            md5 = hashlib.md5(image_bytes).hexdigest()

            # 3. 请求 Oopz 获取 signedUploadUrl
            url_path = "/rtc/v1/cos/v1/signedUploadUrl"
            url = OOPZ_CONFIG["base_url"] + url_path
            body = {"type": "IMAGE", "ext": ext}
            body_str = json.dumps(body, separators=(',', ':'), ensure_ascii=False)

            headers = self.session.headers.copy()
            headers.update(self.signer.create_oopz_headers(url_path, body_str))

            resp2 = self.session.put(url, headers=headers, data=body_str.encode('utf-8'))
            resp2.raise_for_status()
            data = resp2.json()["data"]

            signed_url = data["signedUrl"]
            file_key = data["file"]
            cdn_url = data["url"]

            # 4. 上传文件到 COS（直接传 bytes）
            put_resp = requests.put(
                signed_url,
                data=image_bytes,
                headers={"Content-Type": "application/octet-stream"}
            )
            put_resp.raise_for_status()

            # 5. 构造返回数据
            attachment = {
                "fileKey": file_key,
                "url": cdn_url,
                "width": width,
                "height": height,
                "fileSize": file_size,
                "hash": md5,
                "animated": False,
                "displayName": "",
                "attachmentType": "IMAGE"
            }

            return {"code": "success", "message": "✅ 获取成功", "data": attachment}

        except Exception as e:
            return {"code": "error", "message": f"❌ 上传失败: {e}", "data": None}


def demo():
    """演示简化版发送器"""
    print("=== 简化版Oopz消息发送器演示 ===\n")

    # 创建发送器（无需任何参数）
    sender = SimpleOopzSender()

    print("\n" + "=" * 50)
    print("🎯 演示功能:")

    # 1. 发送单条消息
    print("\n1. 发送单条消息到默认频道:")
    try:
        response = sender.send_to_default("Hello from Simple Sender! 🚀")
        if response.status_code == 200:
            print("✅ 发送成功!")
        else:
            print(f"⚠️ 发送状态: {response.status_code}")
    except Exception as e:
        print(f"❌ 发送失败: {e}")

    print("\n2. 发送到指定频道:")
    try:
        response = sender.send_message(
            text="指定频道消息 📍",
            area="01K5SCK1MJHS2WSFMK63X321G7",
            channel="01K5SCK1NK1ZXZAQE957RME3P2"
        )
    except Exception as e:
        print(f"❌ 发送失败: {e}")

    print("\n3. 批量发送演示:")
    messages = [
        "批量消息 1 📝",
        "批量消息 2 🎯",
        "批量消息 3 ✨"
    ]

    try:
        results = sender.send_multiple(messages, interval=0.5)
        print("批量发送结果:", results)
    except Exception as e:
        print(f"❌ 批量发送失败: {e}")


def interactive_mode():
    """交互模式"""
    print("💬 进入交互模式")
    print("输入消息内容，输入 'quit' 退出")
    print("=" * 50)

    sender = SimpleOopzSender()

    while True:
        try:
            message = input("\n💭 输入消息: ").strip()

            if message.lower() in ['quit', 'exit', '退出']:
                print("👋 再见!")
                break

            if not message:
                print("❌ 消息不能为空")
                continue

            response = sender.send_to_default(message)

            if response.status_code == 200:
                print("✅ 发送成功!")
            else:
                print(f"⚠️ 发送状态: {response.status_code}")

        except KeyboardInterrupt:
            print("\n\n👋 用户中断，再见!")
            break
        except Exception as e:
            print(f"💥 发送异常: {e}")


if __name__ == "__main__":
    sender = SimpleOopzSender()
    res = sender.upload_file_from_url("https://y.qq.com/music/photo_new/T002R300x300M000004IXV6J3kcvn1_2.jpg?max_age=2592000")
    print(res)
    # print("🎯 简化版Oopz消息发送器")
    # print("选择模式:")
    # print("1. 演示模式")
    # print("2. 交互模式")
    #
    # try:
    #     choice = input("\n请选择 (1-2): ").strip()
    #
    #     if choice == "1":
    #         demo()
    #     elif choice == "2":
    #         interactive_mode()
    #     else:
    #         print("❌ 无效选择，运行演示模式")
    #         demo()
    #
    # except KeyboardInterrupt:
    #     print("\n👋 用户取消，再见!")
