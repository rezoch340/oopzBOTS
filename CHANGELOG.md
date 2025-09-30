# 更新日志

## 2025-09-30 - v1.0.0

### ✨ 新功能

1. **播放队列系统**
   - 基于 Redis 的播放队列管理
   - 支持多首歌曲排队
   - `/next` 命令切换下一首
   - `/queue` 命令查看队列

2. **图片缓存系统**
   - 自动缓存歌曲封面到 SQLite 数据库
   - 避免重复上传相同图片到 Oopz
   - 显著提升响应速度
   - 缓存命中率统计

3. **自动播放监控**
   - 监控 AudioService 播放状态
   - 歌曲播放完成后自动播放下一首
   - 每 3 秒检查一次播放状态

4. **Web 管理后台**
   - 实时仪表盘展示
   - 播放队列管理
   - 统计数据可视化
   - REST API 接口

5. **数据统计**
   - 每日播放统计
   - 平台使用统计
   - 热门歌曲排行
   - 缓存使用统计

### 🔧 改进

1. **配置管理**
   - 自动从 Windows 注册表读取 Oopz 登录信息
   - 无需手动配置 device_id、person_uid、jwt_token

2. **AudioService 增强**
   - 添加 `/status` 端点查询播放状态
   - 返回当前播放文件和播放状态

3. **错误处理**
   - 改进编码处理，避免 GBK 编码问题
   - 添加超时处理

### 📦 新增文件

- `database.py` - 数据库管理
- `queue_manager.py` - 队列管理器
- `web_api.py` - Web API 服务
- `start_all.py` - 一键启动脚本
- `start_simple.bat` - Windows 批处理启动脚本
- `test_system.py` - 系统测试脚本
- `README_NEW.md` - 新版完整文档
- `USAGE_GUIDE.md` - 使用指南

### 🎯 工作流程

#### 播放歌曲流程
1. 用户发送命令（如 `/yun play 不说`）
2. 搜索歌曲
3. 检查图片缓存
4. 如果缓存命中：使用缓存的附件数据
5. 如果缓存未命中：上传图片并保存到缓存
6. 添加歌曲到 Redis 队列
7. 如果是第一首：立即播放
8. 否则：排队等待
9. 记录播放历史和统计数据

#### 自动播放流程
1. 后台监控线程每 3 秒检查 AudioService 状态
2. 如果检测到播放完成（有当前歌曲但未在播放）
3. 从队列中取出下一首歌曲
4. 自动开始播放
5. 更新当前播放状态

### 🔌 API 端点

#### 队列管理
- `GET /api/player/status` - AudioService 播放器状态
- `GET /api/queue/status` - 队列状态
- `GET /api/queue/list` - 队列列表
- `POST /api/queue/add` - 添加到队列
- `POST /api/queue/next` - 播放下一首
- `DELETE /api/queue/clear` - 清空队列

#### 图片缓存
- `GET /api/cache/images` - 图片缓存列表
- `GET /api/cache/images/{type}/{id}` - 查询特定缓存

#### 统计数据
- `GET /api/statistics/today` - 今日统计
- `GET /api/statistics/recent` - 最近统计
- `GET /api/statistics/summary` - 汇总统计

#### 歌曲信息
- `GET /api/songs/top` - 热门歌曲
- `GET /api/songs/recent` - 最近播放

### 🚀 快速开始

#### 方式一：一键启动
```bash
python start_all.py
```

#### 方式二：Windows 批处理
```bash
start_simple.bat
```

#### 方式三：分别启动
```bash
# 终端 1: Web API
python -m uvicorn web_api:app --host 0.0.0.0 --port 8000

# 终端 2: 机器人
python main.py
```

### 📋 依赖要求

新增依赖：
- `redis` - Redis 客户端
- `fastapi` - Web 框架
- `uvicorn[standard]` - ASGI 服务器
- `aiohttp` - 异步 HTTP 客户端

### 🐛 已修复问题

1. GBK 编码问题
   - 修复 emoji 字符导致的编码错误
   - 改进子进程输出处理

2. 进程管理问题
   - 修复启动脚本误判进程退出
   - 改进进程监控逻辑

3. 配置读取问题
   - 添加从注册表自动读取配置
   - 支持动态更新配置

### 📝 注意事项

1. **Redis 服务**
   - 需要安装并运行 Redis 服务器
   - 默认连接：`192.168.1.4:6379`
   - 可在 `queue_manager.py` 中修改配置

2. **AudioService**
   - 需要重新编译 AudioService（添加了 `/status` 端点）
   - 确保 AudioService 在 `http://192.168.1.21:5000` 运行

3. **数据库**
   - 首次运行会自动创建 `oopz_cache.db` 数据库
   - 包含图片缓存、歌曲信息、播放历史等表

### 🎉 致谢

感谢所有贡献者和用户的支持！
