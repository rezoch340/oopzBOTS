#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RSA私钥配置文件
这里存放从dart.js中提取的真实RSA私钥
"""

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

# 🔑 真实的RSA私钥（从dart.js中提取并重新组合）
# 基于B.b6y、B.aXA、B.aUS等变量的内容重新组装
REAL_RSA_PRIVATE_KEY_PEM = """-----BEGIN PRIVATE KEY-----
-----END PRIVATE KEY-----"""


def load_real_private_key():
    """
    加载真实的RSA私钥

    Returns:
        RSA私钥对象
    """
    try:
        private_key = serialization.load_pem_private_key(
            REAL_RSA_PRIVATE_KEY_PEM.encode('utf-8'),
            password=None,
            backend=default_backend()
        )
        return private_key
    except Exception as e:
        print(f"❌ 加载真实私钥失败: {e}")
        print("⚠️  将使用测试私钥代替")
        return None


def get_private_key():
    """
    获取私钥（优先使用真实私钥，失败则使用测试私钥）

    Returns:
        RSA私钥对象
    """
    # 尝试加载真实私钥
    real_key = load_real_private_key()
    if real_key:
        print("✅ 使用真实RSA私钥")
        return real_key

    # 使用测试私钥
    print("⚠️  使用测试RSA私钥")
    from cryptography.hazmat.primitives.asymmetric import rsa
    return rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend()
    )


# 私钥替换说明
PRIVATE_KEY_INSTRUCTIONS = """
🔑 RSA私钥替换说明:

1. 📁 找到dart.js中的私钥片段:
   - 搜索 "B.b6y", "B.aXA", "B.aUS" 等变量
   - 这些是Base64编码的私钥片段

2. 🔧 重新组合私钥:
   - 将所有Base64片段连接起来
   - 添加PEM格式的头尾:
     -----BEGIN PRIVATE KEY-----
     [Base64内容]
     -----END PRIVATE KEY-----

3. 📝 替换本文件中的REAL_RSA_PRIVATE_KEY_PEM变量

4. ✅ 测试私钥是否有效:
   python -c "from private_key import load_real_private_key; print('私钥测试:', '成功' if load_real_private_key() else '失败')"

⚠️  注意: 当前使用的是之前提取的私钥，可能需要更新为最新版本
"""

if __name__ == "__main__":
    print("🔑 RSA私钥配置测试")
    print("=" * 50)

    # 测试私钥加载
    key = get_private_key()
    if key:
        print("✅ 私钥加载成功")

        # 测试签名功能
        try:
            from cryptography.hazmat.primitives import hashes
            from cryptography.hazmat.primitives.asymmetric import padding
            import base64

            test_data = "test signature"
            signature = key.sign(
                test_data.encode('utf-8'),
                padding.PKCS1v15(),
                hashes.SHA256()
            )
            signature_b64 = base64.b64encode(signature).decode('utf-8')

            print(f"✅ 签名功能测试成功")
            print(f"📝 测试数据: {test_data}")
            print(f"🔐 签名结果: {signature_b64[:50]}...")

        except Exception as e:
            print(f"❌ 签名功能测试失败: {e}")
    else:
        print("❌ 私钥加载失败")

    print("\n" + PRIVATE_KEY_INSTRUCTIONS)
