# 🎵 Oopz Music Bot - 音乐机器人系统

一个功能完整的音乐机器人系统，支持网易云音乐、QQ 音乐和 Bilibili，具有队列管理、图片缓存、实时日志流和 Web 管理后台。

## ✨ 功能特性

### 🤖 机器人功能
- **多平台音乐支持**
  - 网易云音乐 (`/yun play`)
  - QQ 音乐 (`/qq play`)
  - Bilibili 视频/音乐 (`/bili play`)

- **播放队列管理**
  - 自动队列管理，支持多首歌曲排队
  - `/next` 命令切换到下一首
  - `/queue` 查看当前队列
  - `/stop` 停止播放
  - 自动播放下一首（播放完成后自动切换）
  - 🆕 **UUID 追踪系统** - 每首歌曲有唯一 UUID，精确追踪播放状态

- **🎯 智能状态管理** 🆕
  - **职责分离设计** - Python 和 AudioService 清晰的职责划分
  - **自动状态清理** - 播放完成后自动清空状态，避免卡住
  - **实时状态同步** - 通过 Redis 实现 Python 和 C# 之间的状态同步
  - **完整生命周期追踪** - 从播放开始到结束的完整日志链路

- **智能图片缓存**
  - 自动缓存歌曲封面，避免重复上传到 Oopz
  - 显著提升响应速度
  - 降低 API 调用次数

### 📊 Web 管理后台
- **实时仪表盘**
  - 当前播放状态（含封面图片）
  - 队列实时显示（含封面图片）
  - 今日播放统计
  - 缓存使用情况

- **数据统计**
  - 每日播放统计
  - 热门歌曲排行
  - 平台分布统计
  - 缓存命中率

- **🔥 实时日志流**
  - 📋 Server-Sent Events (SSE) 实时日志推送
  - 🎨 日志级别颜色高亮（ERROR/WARNING/INFO/DEBUG）
  - ⏸️ 暂停/继续日志流
  - 🧹 清空显示/清空日志文件
  - ✅ 自动滚动到最新日志
  - 📊 日志连接状态实时显示
  - 💾 日志自动轮转（最大 10MB，保留 5 个备份）

- **REST API**
  - 完整的 RESTful API
  - Swagger 文档自动生成
  - 支持队列操作、统计查询、日志查询等

- **身份认证**
  - Cookie-based 认证系统
  - 登录/登出功能
  - API 端点保护

## 🚀 快速开始

### 环境要求
- Python 3.10+
- Redis 服务器
- FFmpeg（用于 Bilibili 音频转换）

### 安装步骤

1. **克隆项目**
```bash
git clone <repository-url>
cd oopzBOTS
```

2. **安装依赖**
```bash
pip install -r requirements.txt
```

3. **配置文件**

复制配置示例文件：
```bash
cp config.example.py config.py
cp private_key.example.py private_key.py
```

编辑 `config.py` 配置以下内容：
- Redis 连接信息
- Oopz 平台配置
- AudioService 地址
- 音乐 API 配置
- Web 认证用户名密码

4. **初始化数据库**

首次运行会自动创建 SQLite 数据库和 logs 目录。

5. **启动服务**

**方式一：简单启动（推荐）**
```bash
# Windows
start_simple.bat

# Linux/macOS
./start_simple.sh
```

**方式二：分别启动**
```bash
# 终端 1: 启动 Web API
python -m uvicorn web_api:app --host 0.0.0.0 --port 8000

# 终端 2: 启动机器人
python main.py
```

6. **访问 Web 后台**

打开浏览器访问：`http://localhost:8000`

默认用户名和密码在 `config.py` 中配置。

## 📱 使用说明

### 机器人命令

在 Oopz 聊天频道中使用以下命令：

| 命令 | 说明 | 示例 |
|------|------|------|
| `/yun play <歌名>` | 播放网易云音乐 | `/yun play 不说` |
| `/qq play <歌名>` | 播放 QQ 音乐 | `/qq play 晴天` |
| `/bili play <BV号>` | 播放 Bilibili 视频 | `/bili play BV1xx411c7mD` |
| `/next` | 播放下一首 | `/next` |
| `/queue` | 查看播放队列 | `/queue` |
| `/stop` | 停止播放 | `/stop` |

### Web 后台功能

访问 `http://localhost:8000` 打开管理后台：

- **🏠 仪表盘**: 实时查看播放状态和统计数据
- **📋 播放队列**: 查看队列、播放下一首、清空队列
- **📊 当前播放**: 显示正在播放的歌曲（含封面）
- **📈 统计数据**: 今日播放、缓存命中率、队列长度
- **📋 实时日志**: 流式查看系统日志，支持暂停/继续
- **📚 API 文档**: `http://localhost:8000/docs`

### API 端点

#### 认证
- `POST /api/auth/login` - 用户登录
- `POST /api/auth/logout` - 用户登出
- `GET /api/auth/check` - 检查认证状态

#### 队列管理
- `GET /api/queue/status` - 获取播放器状态
- `GET /api/queue/list` - 获取队列列表
- `POST /api/queue/add` - 添加歌曲到队列
- `POST /api/queue/next` - 播放下一首
- `DELETE /api/queue/clear` - 清空队列
- `DELETE /api/queue/remove/{index}` - 移除指定歌曲

#### 日志管理 🆕
- `GET /api/logs` - 获取日志文件内容（分页）
- `GET /api/logs/stream` - 实时日志流（SSE）
- `DELETE /api/logs/clear` - 清空日志文件

#### 图片缓存
- `GET /api/cache/images` - 获取图片缓存列表
- `GET /api/cache/images/{type}/{id}` - 查询特定图片缓存

#### 统计数据
- `GET /api/statistics/today` - 今日统计
- `GET /api/statistics/recent` - 最近几天统计
- `GET /api/statistics/summary` - 汇总统计

#### 歌曲信息
- `GET /api/songs/top` - 热门歌曲
- `GET /api/songs/recent` - 最近播放

#### Bilibili 集成
- `GET /b2mp3/detail/{bvid}` - 获取视频详情
- `GET /b2mp3/{bvid}` - 转换为 MP3

## 🏗️ 系统架构

```
┌─────────────────────────────────────────────────────┐
│                  Oopz 聊天平台                       │
│                (WebSocket 连接)                      │
└───────────────────┬─────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────────┐
│              main.py (机器人核心)                     │
│  - WebSocket 消息处理                                │
│  - 命令解析和路由                                     │
│  - 队列管理集成                                       │
│  - 🆕 UUID 生成和管理                                │
│  - 日志记录 (logger)                                 │
└──────┬──────────────────────────────────────────────┘
       │
       ├─► database.py (SQLite)
       │   - 图片缓存 (image_cache)
       │   - 歌曲缓存 (song_cache)
       │   - 播放历史 (play_history)
       │   - 统计数据 (statistics)
       │
       ├─► queue_manager.py (Redis)
       │   - 播放队列管理
       │   - 当前播放状态 (含 play_uuid)
       │   - 播放历史
       │   - 日志记录 (logger)
       │
       ├─► oopz_sender.py
       │   - 消息发送
       │   - 文件上传
       │   - 日志记录 (logger)
       │
       └─► 音乐 API
           - netease.py (网易云)
           - qqmusic.py (QQ 音乐)
           - bilibili.py (Bilibili)

┌─────────────────────────────────────────────────────┐
│           web_api.py (FastAPI 后台)                  │
│  - REST API 端点                                     │
│  - Web 仪表盘                                        │
│  - 实时数据展示                                       │
│  - SSE 日志流 🆕                                     │
│  - 身份认证                                          │
└─────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────┐
│          logger_config.py (日志系统) 🆕              │
│  - 统一日志配置                                       │
│  - 文件日志 (logs/oopz_bot.log)                      │
│  - 控制台日志                                         │
│  - 日志轮转 (10MB, 5个备份)                          │
└─────────────────────────────────────────────────────┘
```

## 📦 核心模块说明

### `logger_config.py` 🆕
统一日志管理模块：
- **统一配置**: 所有模块使用相同的日志配置
- **文件日志**: 自动写入 `logs/oopz_bot.log`
- **日志轮转**: 文件达到 10MB 自动轮转，保留 5 个备份
- **多级别**: 支持 DEBUG/INFO/WARNING/ERROR 级别
- **格式化**: 统一的时间戳和格式

### `database.py`
数据库管理模块，使用 SQLite 存储：
- **ImageCache**: 图片缓存管理
- **SongCache**: 歌曲信息缓存
- **Statistics**: 播放统计数据

### `queue_manager.py`
队列管理模块，使用 Redis 实现：
- 播放队列 FIFO 管理
- 当前播放状态追踪
- 播放历史记录
- 默认频道缓存

### `web_api.py`
Web API 和管理后台：
- FastAPI 框架
- RESTful API 端点
- 响应式仪表盘
- Swagger 文档
- SSE 实时日志流 🆕
- Cookie 认证系统

### `main.py`
机器人核心程序：
- WebSocket 连接管理
- 命令处理和分发
- 音乐播放控制
- 队列集成
- 自动播放监控 🆕

### `oopz_sender.py`
Oopz 平台消息发送器：
- RSA 签名认证
- 消息发送
- 文件上传
- 批量操作

### `auth.py` 🆕
Web 后台认证模块：
- 密码哈希验证
- Token 生成和验证
- Cookie 管理
- 装饰器保护

## 🎯 工作流程

### 播放歌曲流程

1. **用户发送命令** `/yun play 不说`
2. **搜索歌曲**: 调用网易云 API 搜索
3. **检查缓存**: 查询 SQLite 中是否有封面缓存
4. **上传封面**: 
   - 缓存命中：直接使用缓存的 attachment 数据
   - 缓存未命中：上传到 Oopz 并保存到缓存
5. **添加到队列**: 歌曲信息存入 Redis 队列
6. **生成 UUID**: 🆕 为播放生成唯一标识符
7. **开始播放**: 
   - 如果是第一首，立即播放（传递 UUID）
   - 否则排队等待
8. **写入状态**: 🆕 将歌曲信息（含 UUID）写入 `music:current`
9. **记录统计**: 更新数据库中的播放次数和统计数据
10. **发送消息**: 回复用户歌曲信息和队列位置（带封面）
11. **日志记录**: 记录所有操作和 UUID 到日志文件

### 自动播放流程 🆕

```
播放监控线程 (每 5 秒检查一次)
    │
    ├─► 检查播放器状态 (从 Redis)
    │   - playing: false/true
    │   - playUuid: null/uuid
    │
    ├─► 正在播放 (playing=true) → 继续监控
    │
    └─► 未播放 (playing=false)
        │
        ├─► music:current 存在 + playUuid=null → 播放完成
        │   │
        │   └─► 队列不为空
        │       ├─► 从队列取出下一首
        │       ├─► 生成新的 UUID 🆕
        │       ├─► 写入 music:current (含 UUID) 🆕
        │       ├─► 调用 AudioService 播放 (传递 UUID) 🆕
        │       └─► 发送播放通知
        │
        └─► music:current 不存在 + 队列有歌曲
            └─► 开始播放第一首 (同上流程)

AudioService 播放完成时:
    ├─► 清理临时文件
    ├─► playUuid = null 🆕
    ├─► 同步状态到 Redis (playing=false, playUuid=null) 🆕
    └─► 删除 music:current 键 🆕
        └─► Python 监控检测到 → 触发下一首播放
```

### 日志流工作原理 🆕

```
客户端浏览器
    │
    └─► EventSource('/api/logs/stream')
         │
         ▼
    FastAPI SSE 端点
         │
         ├─► 发送现有日志（最后 50 行）
         │
         └─► 循环监控日志文件
             │
             ├─► 检测新日志
             │   └─► 实时推送到客户端
             │
             └─► 客户端断开 → 关闭连接
```

## 🔧 高级配置

### 自定义 Redis 配置

编辑 `config.py`:
```python
REDIS_CONFIG = {
    "host": "localhost",
    "port": 6379,
    "db": 0,
    "password": "your_password",
    "decode_responses": True
}
```

### 自定义日志配置 🆕

编辑 `logger_config.py`:
```python
# 日志级别
setup_logger("OopzBot", level=logging.DEBUG)

# 日志文件大小和备份数量
RotatingFileHandler(
    LOG_FILE,
    maxBytes=10 * 1024 * 1024,  # 10MB
    backupCount=5  # 保留 5 个备份
)
```

### 自定义 Web 认证 🆕

编辑 `config.py`:
```python
WEB_AUTH = {
    "username": "admin",
    "password": "your_secure_password",
    "secret_key": "your-secret-key-here",
    "algorithm": "HS256",
    "access_token_expire_minutes": 60
}
```

### 配置 Bilibili 代理

编辑 `web_api.py`:
```python
proxies = {
    "http": "http://user:pass@host:port",
    "https": "http://user:pass@host:port",
}
```

## 📊 数据库表结构

### image_cache
```sql
- id: 主键
- source_id: 源 ID (歌曲 ID/BV号)
- source_type: 源类型 (netease/qq/bilibili)
- source_url: 原始图片 URL
- file_key: Oopz 文件 key
- oopz_url: Oopz CDN URL
- attachment_data: 完整的 attachment JSON
- width, height: 图片尺寸
- use_count: 使用次数
- created_at: 创建时间
- last_used_at: 最后使用时间
```

### song_cache
```sql
- id: 主键
- song_id: 歌曲 ID
- platform: 平台 (netease/qq/bilibili)
- song_name: 歌曲名
- artist: 歌手
- album: 专辑
- play_count: 播放次数
- image_cache_id: 关联的图片缓存 ID
- created_at, last_played_at: 时间戳
```

### statistics
```sql
- id: 主键
- date: 日期
- total_plays: 总播放次数
- unique_songs: 不重复歌曲数
- cache_hits, cache_misses: 缓存统计
- platform_breakdown: 平台分布 (JSON)
```

## 📁 目录结构

```
oopzBOTS/
├── main.py                 # 机器人主程序
├── web_api.py              # Web API 和管理后台
├── config.py               # 配置文件
├── config.example.py       # 配置示例
├── auth.py                 # 认证模块 🆕
├── database.py             # 数据库管理
├── queue_manager.py        # 队列管理
├── logger_config.py        # 日志配置 🆕
├── oopz_sender.py          # Oopz 消息发送
├── netease.py              # 网易云 API
├── qqmusic.py              # QQ音乐 API
├── bilibili.py             # Bilibili API
├── private_key.py          # RSA 私钥
├── private_key.example.py  # 私钥示例
├── requirements.txt        # 依赖列表
├── start_simple.bat        # Windows 启动脚本
├── oopz_cache.db           # SQLite 数据库
├── logs/                   # 日志目录 🆕
│   └── oopz_bot.log       # 主日志文件
└── doc/                    # 文档和示例图片
    └── Example Image/
```

## 🐛 故障排除

### 机器人无法连接
- 检查 Oopz 登录状态
- 确认 `config.py` 中的配置正确
- 查看 JWT Token 是否过期
- 查看实时日志排查问题 🆕

### Redis 连接失败
- 确认 Redis 服务运行中
- 检查防火墙设置
- 验证密码是否正确
- 查看日志中的连接错误 🆕

### 歌曲无法播放
- 检查 AudioService 是否运行
- 确认音频 API 可访问
- 查看实时日志中的错误信息 🆕

### Web 界面无法访问
- 确认端口 8000 未被占用
- 检查防火墙设置
- 查看 uvicorn 日志
- 验证登录凭据是否正确

### 日志相关问题 🆕
- **日志不显示**: 检查 `logs/` 目录权限
- **日志流断开**: 刷新页面重新连接
- **日志文件过大**: 使用清空日志功能
- **日志轮转失败**: 检查磁盘空间

### UUID 播放状态问题 🆕
- **播放完成后卡住**
  - 检查 AudioService 是否连接 Redis
  - 查看 AudioService 日志是否有 "已清空 music:current"
  - 验证 Redis 中 `music:current` 是否被删除
  - 确认 `music:player_status` 中 `playUuid` 是否为 null
  
- **UUID 追踪失败**
  - 检查 Python 日志是否显示 "播放响应 (UUID: xxx)"
  - 检查 AudioService 日志是否显示 "正在播放: xxx (UUID: xxx)"
  - 确认调用了 `queue_manager.set_current(next_song)`
  
- **自动播放不工作**
  - 验证监控线程是否运行
  - 检查 `music:player_status` 状态是否正确更新
  - 查看是否有 "自动播放: 开始播放" 日志
  
**调试命令：**
```bash
# 检查 Redis 状态
redis-cli -h 192.168.1.4 -p 6379 -a redis_ywKGBX

# 查看当前播放
GET music:current

# 查看播放器状态
GET music:player_status

# 查看队列
LRANGE music:queue 0 -1
```

## 📝 更新日志

### v1.2.0 (2025-09-30) 🎯 重大更新
- 🔥 **UUID 播放状态管理系统** - 解决播放完成卡住的关键 bug
- ✅ **职责分离设计** - Python 写入，AudioService 清空，责任明确
- 🎯 **精确状态追踪** - 每首歌曲有唯一 UUID 标识
- ⚡ **自动状态清理** - 播放完成后自动清空 `music:current`
- 📊 **实时状态同步** - `music:player_status` 实时更新
- 🐛 修复自动播放失效问题
- 🐛 修复状态同步不一致问题
- 📝 新增 `UUID播放状态管理说明.md` 技术文档

### v1.1.0 (2025-10-01)
- ✨ 新增统一日志系统
- ✨ 新增实时日志流（SSE）
- ✨ 新增 Web 身份认证
- ✨ 新增自动播放监控
- ✨ 新增队列列表封面显示
- ✨ 优化自动播放逻辑
- 🐛 修复当前播放状态丢失问题
- 📝 完善 README 文档

### v1.0.0 (2025-09-30)
- ✨ 添加播放队列管理
- ✨ 添加图片缓存系统
- ✨ 添加 Web 管理后台
- ✨ 添加统计仪表盘
- ✨ 集成 Bilibili API
- ✨ 自动从注册表读取登录信息
- 🎨 改进用户交互体验
- 📊 添加详细的数据统计

## 🎓 使用技巧

### 查看实时日志 🆕
1. 打开 Web 后台
2. 滚动到"系统日志"面板
3. 日志会实时流式更新
4. 可以暂停/继续查看
5. 支持自动滚动到最新

### UUID 播放追踪 🆕
1. **查看播放 UUID**
   - Python 日志: `播放响应 (UUID: xxx)`
   - AudioService 日志: `正在播放: ... (UUID: xxx)`
   - Redis 中 `music:current` 包含 `play_uuid` 字段

2. **追踪完整生命周期**
   ```
   [Python] 生成 UUID → 播放开始
   [AudioService] 接收 UUID → 播放中
   [AudioService] 播放完成 (UUID: xxx)
   [AudioService] 已清空 music:current
   [Python] 自动播放: 开始播放下一首
   ```

3. **调试技巧**
   - 对比 Python 和 AudioService 的 UUID 日志
   - 确认 UUID 在整个流程中保持一致
   - 播放完成后 UUID 应变为 null

### 队列管理技巧
1. 添加多首歌曲会自动排队
2. 使用 `/next` 跳过当前歌曲
3. Web 后台可以查看队列顺序
4. 自动播放完会切换下一首
5. 🆕 每首歌都有唯一 UUID，便于追踪

### 缓存优化
1. 常播放的歌曲会自动缓存封面
2. 缓存命中率在仪表盘显示
3. 缓存可以显著提升响应速度

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

## 📄 许可证

本项目使用 MIT 许可证。

## 🙏 致谢

- Oopz 平台
- 网易云音乐 API
- QQ 音乐 API
- Bilibili API
- FastAPI 框架
- Redis

---

<div align="center">

**Made with ❤️ by oopzBOTS Team**

</div>
