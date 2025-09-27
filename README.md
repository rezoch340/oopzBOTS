# 🤖 oopzBOTS - 多平台音乐聊天机器人

一个基于 WebSocket 的智能聊天机器人，支持网易云音乐、QQ音乐、Bilibili 等多平台音乐播放功能。通过 Oopz 平台实现实时聊天交互。

## ✨ 主要功能

### 🎵 多平台音乐支持
- **网易云音乐** - 搜索并播放网易云音乐
- **QQ音乐** - 支持多种音质的QQ音乐播放
- **Bilibili音频** - 从B站视频提取音频播放

### 💬 智能聊天交互
- 实时 WebSocket 连接
- 命令式交互界面
- 自动心跳保活机制
- 多频道消息支持

### 📸 多媒体消息
- 图片上传和发送
- 音乐封面展示
- 附件文件支持

## 🏗️ 项目架构

```
oopzBOTS/
├── main.py              # 主程序入口，WebSocket连接和消息处理
├── config.py            # 配置文件，包含所有平台的配置信息
├── oopz_sender.py       # Oopz平台消息发送器
├── netease.py           # 网易云音乐API封装
├── qqmusic.py           # QQ音乐API封装
├── bilibili.py          # Bilibili音频API封装
├── private_key.py       # RSA私钥配置（需自行创建）
├── requirements.txt     # 项目依赖
└── test.py             # 测试文件
```

## 🚀 快速开始

### 环境要求
- Python 3.8+
- Windows/Linux/macOS

### 安装依赖

```bash
# 创建虚拟环境（推荐）
python -m venv venv
source venv/bin/activate  # Linux/macOS
# 或
venv\Scripts\activate     # Windows

# 安装依赖
pip install -r requirements.txt
```

### 配置设置

1. **创建私钥文件** `private_key.py`：
```python
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend

def get_private_key():
    # 这里放置你的RSA私钥
    # 可以使用 rsa.generate_private_key() 生成测试密钥
    return rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend()
    )
```

2. **修改配置文件** `config.py`：
```python
# 更新你的Oopz账户信息
OOPZ_CONFIG = {
    "person_uid": "你的用户ID",
    "device_id": "你的设备ID", 
    "jwt_token": "你的JWT令牌",
    # ... 其他配置
}

# 更新音乐服务API地址
NETEASE_CLOUD = {
    "base_url": "你的网易云API地址",
    "cookie": "你的网易云Cookie"
}

QQ_MUSIC = {
    "base_url": "你的QQ音乐API地址"
}

BILIBILI = {
    "base_url": "你的Bilibili API地址"
}

AudioService = {
    "base_url": "你的音频播放服务地址"
}
```

### 运行程序

```bash
python main.py
```

## 📖 使用指南

### 支持的命令

| 命令 | 功能 | 示例 |
|------|------|------|
| `/yun play <歌名>` | 播放网易云音乐 | `/yun play 夜曲` |
| `/qq play <歌名>` | 播放QQ音乐 | `/qq play 告白气球` |
| `/bili play <关键词/链接>` | 播放B站音频 | `/bili play BV1234567890` |
| `/stop` | 停止当前播放 | `/stop` |
| `/sb` | 发送测试图片 | `/sb` |

### 消息格式示例

**音乐播放响应**：
```
🎵 歌曲: 夜曲
🎤 歌手: 周杰伦  
💽 专辑: 十一月的萧邦
⏱ 时长: 3分52秒
```

## 🔧 核心模块详解

### 1. WebSocket 连接管理 (`main.py`)
- 自动重连机制
- 心跳保活（10秒间隔）
- 消息事件处理
- 命令解析和路由

### 2. 音乐平台集成

#### 网易云音乐 (`netease.py`)
```python
# 搜索歌曲
result = neteaseAPI.search("歌曲名")

# 获取歌曲详情
detail = neteaseAPI.detail(song_id)

# 获取播放链接
song_url = neteaseAPI.song(song_id)
```

#### QQ音乐 (`qqmusic.py`)
```python
# 支持多种音质
quality_types = ["320", "128", "m4a", "flac", "ape"]

# 自动检测最佳音质
quality = detect_quality(song_data)
```

#### Bilibili (`bilibili.py`)
```python
# 支持BV号和关键词搜索
result = bilibiliAPI.summarize("BV1234567890")
```

### 3. 消息发送器 (`oopz_sender.py`)
- RSA数字签名
- 文件上传支持
- 多媒体消息处理
- 批量消息发送

## 🛠️ 高级配置

### 自定义音频服务
项目支持自定义音频播放服务，需要实现以下接口：
- `GET /play?url=<音频链接>` - 播放音频
- `GET /stop` - 停止播放

### 扩展新的音乐平台
1. 创建新的API封装类
2. 实现 `search()`, `detail()`, `summarize()` 方法
3. 在 `main.py` 中添加命令处理逻辑

### 消息处理自定义
在 `handle_command()` 函数中可以添加新的命令处理逻辑：

```python
def handle_command(msg_data, sender):
    content = msg_data.get("content", "").strip()
    
    if content.startswith("/custom"):
        # 处理自定义命令
        custom_handler(content, msg_data, sender)
```

## 🔐 安全说明

### JWT令牌管理
- JWT令牌有过期时间，需要定期更新
- 建议使用环境变量存储敏感信息
- 不要将配置文件提交到公共代码仓库

### RSA密钥安全
- 私钥文件应该妥善保管
- 建议使用强随机数生成密钥
- 定期轮换密钥对

## 🐛 故障排除

### 常见问题

1. **连接失败**
   - 检查网络连接
   - 验证JWT令牌是否过期
   - 确认WebSocket地址正确

2. **音乐播放失败**
   - 检查音乐API服务状态
   - 验证Cookie有效性
   - 确认音频服务地址可访问

3. **消息发送失败**
   - 检查RSA签名配置
   - 验证用户权限
   - 确认频道ID正确

### 调试模式
```python
# 开启WebSocket调试
websocket.enableTrace(True)

# 查看详细日志
import logging
logging.basicConfig(level=logging.DEBUG)
```

## 📝 开发计划

- [ ] 支持更多音乐平台（Apple Music、Spotify等）
- [ ] 添加歌词显示功能
- [ ] 实现播放列表管理
- [ ] 支持语音消息
- [ ] 添加用户权限管理
- [ ] 优化音频质量选择算法

## 🤝 贡献指南

欢迎提交 Issue 和 Pull Request！

1. Fork 本仓库
2. 创建功能分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启 Pull Request

## 📄 许可证

本项目采用 MIT 许可证 - 查看 [LICENSE](LICENSE) 文件了解详情。

## 🙏 致谢

- [网易云音乐API](https://github.com/Binaryify/NeteaseCloudMusicApi) - 提供网易云音乐接口
- [Oopz平台](https://oopz.cn) - 提供聊天平台支持
- 所有贡献者和使用者

---

<div align="center">

**[⬆ 回到顶部](#-oopzbots---多平台音乐聊天机器人)**

Made with ❤️ by oopzBOTS Team

</div>
