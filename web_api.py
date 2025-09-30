#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FastAPI Web 后台
提供 REST API 和管理界面
"""

import json
import hashlib
import time
import subprocess
from contextlib import asynccontextmanager
from typing import Optional, List

import requests
from fastapi import FastAPI, HTTPException, Query, Request, Form
from fastapi.responses import StreamingResponse, HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis

from database import init_database, ImageCache, SongCache, Statistics
from queue_manager import QueueManager
from config import REDIS_CONFIG, AudioService
import oopz_sender
from auth import require_auth, verify_credentials, create_login_response, create_logout_response, get_token_from_request, verify_token

# Bilibili 相关配置
QC_SALT = "6HTugjCXxR"
LOCALE = "zh"
CACHE_TTL = 600

proxies = {
    "http": "http://Clash:q9uD0AOf@192.168.1.2:7890",
    "https": "http://Clash:q9uD0AOf@192.168.1.2:7890",
}

# AudioService 配置
AUDIOSERVICE_URL = AudioService["base_url"]

# 全局变量
redis_client: Optional[Redis] = None
queue_manager: Optional[QueueManager] = None
sender = oopz_sender.SimpleOopzSender()  # Oopz 消息发送器


def _detail_key(bvid: str) -> str:
    return f"detail:{bvid}"


async def set_detail_cache(bvid: str, data: dict):
    """直接传 dict，内部转 JSON 存 Redis，带 TTL"""
    await redis_client.set(
        _detail_key(bvid),
        json.dumps(data),
        ex=CACHE_TTL
    )


async def get_detail_cache(bvid: str) -> dict | None:
    """取出来直接还原成 dict"""
    raw = await redis_client.get(_detail_key(bvid))
    return json.loads(raw) if raw else None


def build_snapany_headers(bvid: str):
    l = f"https://www.bilibili.com/video/{bvid}/"
    m = str(int(time.time() * 1000))
    raw = l + LOCALE + m + QC_SALT
    g_footer = hashlib.md5(raw.encode("utf-8")).hexdigest()
    return {
        "accept": "*/*",
        "accept-language": "zh",
        "cache-control": "no-cache",
        "content-type": "application/json",
        "g-footer": g_footer,
        "g-timestamp": m,
        "origin": "https://snapany.com",
        "referer": "https://snapany.com/",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
    }


def build_bilibili_headers(video_url: str):
    """构造完整 bilibili 请求头"""
    return {
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "Pragma": "no-cache",
        "Range": "bytes=0-",
        "Referer": video_url.split("?")[0],
        "Sec-Fetch-Dest": "video",
        "Sec-Fetch-Mode": "no-cors",
        "Sec-Fetch-Site": "same-origin",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
        "sec-ch-ua": '"Chromium";v="140", "Not=A?Brand";v="24", "Google Chrome";v="140"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
    }


# ========= 生命周期管理 =========
@asynccontextmanager
async def lifespan(app: FastAPI):
    global redis_client, queue_manager
    
    # 初始化数据库
    init_database()
    
    # 初始化 Redis（从配置文件读取）
    redis_client = Redis(
        host=REDIS_CONFIG["host"],
        port=REDIS_CONFIG["port"],
        db=REDIS_CONFIG["db"],
        decode_responses=REDIS_CONFIG["decode_responses"],
        password=REDIS_CONFIG["password"]
    )
    
    # 初始化队列管理器（使用配置）
    queue_manager = QueueManager(redis_config=REDIS_CONFIG)
    
    print("Web API 启动完成")
    
    try:
        yield
    finally:
        await redis_client.aclose()
        print("Redis 连接已关闭")


app = FastAPI(
    title="Oopz Music Bot API",
    description="音乐机器人 Web 后台管理系统",
    version="1.0.0",
    lifespan=lifespan
)

# 允许跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ========= Bilibili API =========
@app.get("/b2mp3/detail/{bvid}")
async def bvid_detail(bvid: str, force_refresh: bool = False):
    """获取 Bilibili 视频详情"""
    # Step 1: 先查缓存
    detail = None if force_refresh else await get_detail_cache(bvid)

    if not detail:
        # Step 2: 未命中缓存，去 API 拿数据
        snapany_headers = build_snapany_headers(bvid)
        json_data = {"link": f"https://www.bilibili.com/video/{bvid}/"}
        res = requests.post(
            "https://mute-flower-7108.q9474145906.workers.dev/v1/extract",
            headers=snapany_headers,
            json=json_data,
            proxies=proxies
        )
        res.raise_for_status()
        data = res.json()

        if "medias" not in data or not data["medias"]:
            return {"status": "error", "msg": "snapany 返回无 medias", "data": data}

        text = data.get("text", "")
        preview_url = data["medias"][0].get("preview_url")

        # 优先选择 audio 流，否则取第一个视频
        resource_url = next(
            (m["resource_url"] for m in data["medias"] if m.get("media_type") == "audio"),
            data["medias"][0]["resource_url"]
        )

        # Step 3: 组装 dict，写缓存
        detail = {
            "text": text,
            "preview_url": preview_url,
            "resource_url": resource_url
        }
        await set_detail_cache(bvid, detail)

    # Step 4: 返回数据
    return {
        "status": "success",
        "msg": "获取成功（来自缓存或API）",
        "data": {
            "text": detail["text"],
            "preview_url": detail["preview_url"],
            "resource_url": detail["resource_url"]
        }
    }


@app.get("/b2mp3/{bvid}")
async def bvid_to_mp3(bvid: str, bitrate: str = "192k"):
    """转换 Bilibili 视频为 MP3"""
    detail = await get_detail_cache(bvid)
    if not detail:
        raise HTTPException(status_code=404, detail="未找到缓存，请先调用 /api/bilibili/detail/{bvid}")

    # 构造 bilibili headers 给 ffmpeg
    bili_headers = build_bilibili_headers(detail["resource_url"])
    headers_str = "".join([f"{k}: {v}\r\n" for k, v in bili_headers.items()])

    # 调 ffmpeg 转码
    process = subprocess.Popen(
        ["ffmpeg",
         "-headers", headers_str,
         "-i", detail["resource_url"],
         "-vn",
         "-acodec", "libmp3lame", "-b:a", bitrate,
         "-f", "mp3", "pipe:1"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
    )

    # 返回流
    return StreamingResponse(
        process.stdout,
        media_type="audio/mpeg",
        headers={"Content-Disposition": f'attachment; filename="{bvid}.mp3"'}
    )


# ========= 队列管理 API =========
@app.get("/api/player/status")
def get_audio_player_status():
    """获取 AudioService 播放器状态（优先从 Redis 读取）"""
    # 先尝试从 Redis 缓存读取
    cached_status = queue_manager.get_player_status()
    if cached_status:
        return cached_status
    
    # 缓存不存在或过期，从 AudioService 获取并更新到 Redis
    return queue_manager.update_player_status_from_service(AUDIOSERVICE_URL)


@app.get("/api/queue/status")
@require_auth
async def get_queue_status(request: Request):
    """获取播放器队列状态"""
    return queue_manager.get_status()


@app.get("/api/queue/list")
@require_auth
async def get_queue_list(request: Request, limit: int = Query(50, ge=1, le=100)):
    """获取队列列表"""
    queue = queue_manager.get_queue(0, limit - 1)
    return {
        "total": queue_manager.get_queue_length(),
        "queue": queue
    }


@app.post("/api/queue/add")
def add_to_queue(song_data: dict):
    """添加歌曲到队列"""
    position = queue_manager.add_to_queue(song_data)
    return {
        "status": "success",
        "message": f"已添加到队列位置 {position}",
        "position": position
    }


@app.post("/api/queue/next")
@require_auth
async def play_next(request: Request, channel: Optional[str] = None):
    """播放下一首
    
    Args:
        channel: 可选的频道ID，如果未提供则使用 Redis 缓存的默认频道
    """
    next_song = queue_manager.play_next()
    if next_song:
        # 调用 AudioService 播放
        try:
            import requests as req
            url = next_song.get('url')
            model = 'qq' if next_song.get('platform') == 'qq' else None
            
            params = {"url": url}
            if model:
                params["model"] = model
            
            play_response = req.get(f"{AUDIOSERVICE_URL}/play", params=params, timeout=5)
            
            # 如果没有提供 channel，尝试从 Redis 获取默认频道
            if not channel:
                channel = queue_manager.get_default_channel()
            
            # 如果有频道，发送消息到 Oopz
            if channel:
                try:
                    platform = next_song.get('platform')
                    platform_name = {
                        'netease': '网易云',
                        'qq': 'QQ音乐',
                        'bilibili': 'B站'
                    }.get(platform, '未知')
                    
                    text = f"⏭️ 切换到下一首 (Web):\n来自于{platform_name}:\n"
                    
                    # B站特殊处理
                    if platform == 'bilibili':
                        text += f"🎵 标题: {next_song['name']}\n"
                        text += f"📺 视频链接: https://www.bilibili.com/video/{next_song.get('song_id')}\n"
                        text += f"🎧 音质: 标准"
                    else:
                        text += f"🎵 歌曲: {next_song['name']}\n"
                        text += f"🎤 歌手: {next_song.get('artists', '未知')}\n"
                        if next_song.get('album'):
                            text += f"💽 专辑: {next_song['album']}\n"
                        if next_song.get('duration'):
                            text += f"⏱ 时长: {next_song['duration']}"
                    
                    # 获取附件
                    attachments = next_song.get('attachments', [])
                    if attachments and len(attachments) > 0:
                        att = attachments[0]
                        text = f"![IMAGEw{att['width']}h{att['height']}]({att['fileKey']})\n" + text
                    
                    sender.send_message(text=text.rstrip(), attachments=attachments, channel=channel)
                except Exception as e:
                    print(f"发送 Oopz 消息失败: {e}")
            
            return {
                "status": "success",
                "message": "已切换到下一首",
                "song": next_song,
                "play_status": play_response.json() if play_response.status_code == 200 else None
            }
        except Exception as e:
            return {
                "status": "error",
                "message": f"播放失败: {str(e)}",
                "song": next_song
            }
    else:
        return {
            "status": "info",
            "message": "队列为空",
            "song": None
        }


@app.delete("/api/queue/clear")
@require_auth
async def clear_queue(request: Request):
    """清空队列"""
    queue_manager.clear_queue()
    return {"status": "success", "message": "队列已清空"}


@app.delete("/api/queue/remove/{index}")
def remove_from_queue(index: int):
    """从队列移除指定位置的歌曲"""
    if queue_manager.remove_from_queue(index):
        return {"status": "success", "message": f"已移除位置 {index} 的歌曲"}
    else:
        raise HTTPException(status_code=404, detail="移除失败，位置不存在")


@app.get("/api/queue/history")
def get_play_history(limit: int = Query(20, ge=1, le=100)):
    """获取播放历史"""
    history = queue_manager.get_history(limit)
    return {
        "total": len(history),
        "history": history
    }


# ========= 图片缓存 API =========
@app.get("/api/cache/images")
def get_image_cache(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    """获取图片缓存列表"""
    images = ImageCache.get_all(limit, offset)
    stats = ImageCache.get_stats()
    return {
        "total": stats['total'],
        "images": images,
        "stats": stats
    }


@app.get("/api/cache/images/{source_type}/{source_id}")
def get_image_by_source(source_type: str, source_id: str):
    """根据源 ID 获取缓存图片"""
    cache = ImageCache.get_by_source(source_id, source_type)
    if cache:
        return {"status": "hit", "data": cache}
    else:
        return {"status": "miss", "data": None}


# ========= 歌曲统计 API =========
@app.get("/api/songs/top")
def get_top_songs(platform: Optional[str] = None, limit: int = Query(20, ge=1, le=100)):
    """获取热门歌曲"""
    songs = SongCache.get_top_songs(platform, limit)
    return {
        "total": len(songs),
        "songs": songs
    }


@app.get("/api/songs/recent")
def get_recent_songs(limit: int = Query(20, ge=1, le=100)):
    """获取最近播放的歌曲"""
    songs = SongCache.get_recent_songs(limit)
    return {
        "total": len(songs),
        "songs": songs
    }


# ========= 统计数据 API =========
@app.get("/api/statistics/today")
def get_today_statistics():
    """获取今日统计"""
    return Statistics.get_today()


@app.get("/api/statistics/recent")
def get_recent_statistics(days: int = Query(7, ge=1, le=30)):
    """获取最近几天的统计"""
    stats = Statistics.get_recent_days(days)
    return {
        "days": days,
        "data": stats
    }


@app.get("/api/statistics/summary")
@require_auth
async def get_summary_statistics(request: Request):
    """获取汇总统计"""
    today = Statistics.get_today()
    image_stats = ImageCache.get_stats()
    queue_length = queue_manager.get_queue_length()
    
    return {
        "today": today,
        "queue_length": queue_length,
        "image_cache": image_stats,
        "current_playing": queue_manager.get_current()
    }


# ========= 日志相关 API =========
@app.get("/api/logs")
@require_auth
async def get_logs(request: Request, lines: int = Query(100, ge=1, le=1000)):
    """获取日志文件内容
    
    Args:
        lines: 返回最后多少行日志（默认 100 行）
    """
    import os
    log_file = "logs/oopz_bot.log"
    
    if not os.path.exists(log_file):
        return {"status": "error", "message": "日志文件不存在", "logs": []}
    
    try:
        with open(log_file, 'r', encoding='utf-8') as f:
            # 读取所有行
            all_lines = f.readlines()
            # 返回最后 N 行
            last_lines = all_lines[-lines:] if len(all_lines) > lines else all_lines
            
            # 解析每一行日志
            logs = []
            for line in last_lines:
                line = line.strip()
                if line:
                    logs.append(line)
            
            return {
                "status": "success",
                "total": len(all_lines),
                "returned": len(logs),
                "logs": logs
            }
    except Exception as e:
        return {"status": "error", "message": str(e), "logs": []}


@app.get("/api/logs/stream")
@require_auth
async def stream_logs(request: Request):
    """实时流式输出日志（SSE）"""
    import os
    import asyncio
    
    async def log_generator():
        log_file = "logs/oopz_bot.log"
        
        # 先发送现有日志的最后 50 行
        if os.path.exists(log_file):
            try:
                with open(log_file, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                    last_lines = lines[-50:] if len(lines) > 50 else lines
                    for line in last_lines:
                        line = line.strip()
                        if line:
                            yield f"data: {line}\n\n"
                    
                    # 记录当前文件位置
                    last_pos = f.tell()
            except Exception as e:
                yield f"data: [ERROR] 读取日志失败: {e}\n\n"
                return
        else:
            yield f"data: [INFO] 等待日志文件创建...\n\n"
            last_pos = 0
        
        # 实时监控新日志
        while True:
            # 检查客户端是否断开连接
            if await request.is_disconnected():
                break
            
            try:
                if os.path.exists(log_file):
                    with open(log_file, 'r', encoding='utf-8') as f:
                        # 跳到上次读取的位置
                        f.seek(last_pos)
                        
                        # 读取新内容
                        new_lines = f.readlines()
                        if new_lines:
                            for line in new_lines:
                                line = line.strip()
                                if line:
                                    yield f"data: {line}\n\n"
                        
                        # 更新位置
                        last_pos = f.tell()
                
                # 等待 1 秒后继续检查
                await asyncio.sleep(1)
                
            except Exception as e:
                yield f"data: [ERROR] 读取日志失败: {e}\n\n"
                await asyncio.sleep(5)
    
    return StreamingResponse(
        log_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )



@app.delete("/api/logs/clear")
@require_auth
async def clear_logs(request: Request):
    """清空日志文件"""
    import os
    log_file = "logs/oopz_bot.log"
    
    try:
        if os.path.exists(log_file):
            with open(log_file, 'w', encoding='utf-8') as f:
                f.write("")
            return {"status": "success", "message": "日志已清空"}
        else:
            return {"status": "error", "message": "日志文件不存在"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ========= 认证相关 API =========
@app.post("/api/auth/login")
async def login(username: str = Form(...), password: str = Form(...)):
    """用户登录"""
    if verify_credentials(username, password):
        return create_login_response(username)
    else:
        raise HTTPException(status_code=401, detail="用户名或密码错误")


@app.post("/api/auth/logout")
async def logout():
    """用户登出"""
    return create_logout_response()


@app.get("/api/auth/check")
async def check_auth(request: Request):
    """检查认证状态"""
    token = get_token_from_request(request)
    if token and verify_token(token):
        return {"authenticated": True}
    else:
        return {"authenticated": False}


# ========= 简单的 Web 界面 =========
@app.get("/login", response_class=HTMLResponse)
async def login_page():
    """登录页面"""
    return """
    <!DOCTYPE html>
    <html lang="zh-CN">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>登录 - Oopz Music Bot</title>
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body {
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                min-height: 100vh;
                display: flex;
                align-items: center;
                justify-content: center;
            }
            .login-container {
                background: white;
                padding: 40px;
                border-radius: 16px;
                box-shadow: 0 20px 60px rgba(0,0,0,0.3);
                width: 90%;
                max-width: 400px;
            }
            .login-title {
                font-size: 28px;
                font-weight: bold;
                color: #333;
                margin-bottom: 30px;
                text-align: center;
            }
            .form-group {
                margin-bottom: 20px;
            }
            label {
                display: block;
                margin-bottom: 8px;
                color: #555;
                font-weight: 500;
            }
            input {
                width: 100%;
                padding: 12px;
                border: 2px solid #ddd;
                border-radius: 8px;
                font-size: 16px;
                transition: border-color 0.3s;
            }
            input:focus {
                outline: none;
                border-color: #667eea;
            }
            button {
                width: 100%;
                padding: 14px;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 16px;
                font-weight: bold;
                cursor: pointer;
                transition: transform 0.2s, box-shadow 0.2s;
            }
            button:hover {
                transform: translateY(-2px);
                box-shadow: 0 8px 20px rgba(102, 126, 234, 0.4);
            }
            button:active {
                transform: translateY(0);
            }
            .error-message {
                color: #e74c3c;
                margin-top: 15px;
                text-align: center;
                display: none;
            }
        </style>
    </head>
    <body>
        <div class="login-container">
            <div class="login-title">🎵 Oopz Music Bot</div>
            <form id="loginForm">
                <div class="form-group">
                    <label for="username">用户名</label>
                    <input type="text" id="username" name="username" required autocomplete="username">
                </div>
                <div class="form-group">
                    <label for="password">密码</label>
                    <input type="password" id="password" name="password" required autocomplete="current-password">
                </div>
                <button type="submit">登录</button>
                <div class="error-message" id="errorMessage"></div>
            </form>
        </div>

        <script>
            document.getElementById('loginForm').addEventListener('submit', async (e) => {
                e.preventDefault();
                
                const username = document.getElementById('username').value;
                const password = document.getElementById('password').value;
                const errorMessage = document.getElementById('errorMessage');
                
                try {
                    const formData = new FormData();
                    formData.append('username', username);
                    formData.append('password', password);
                    
                    const res = await fetch('/api/auth/login', {
                        method: 'POST',
                        body: formData
                    });
                    
                    const data = await res.json();
                    
                    if (res.ok) {
                        // 登录成功，跳转到首页
                        window.location.href = '/';
                    } else {
                        // 登录失败，显示错误
                        errorMessage.textContent = data.detail || '登录失败';
                        errorMessage.style.display = 'block';
                    }
                } catch (err) {
                    errorMessage.textContent = '网络错误，请重试';
                    errorMessage.style.display = 'block';
                }
            });
        </script>
    </body>
    </html>
    """


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """简单的仪表盘"""
    # 检查认证状态
    token = get_token_from_request(request)
    if not token or not verify_token(token):
        # 未登录，重定向到登录页
        return HTMLResponse(content="""
            <script>
                window.location.href = '/login';
            </script>
        """)
    
    return """
    <!DOCTYPE html>
    <html lang="zh-CN">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Oopz Music Bot - 仪表盘</title>
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body {
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: #333;
                padding: 20px;
            }
            .container {
                max-width: 1400px;
                margin: 0 auto;
            }
            .header {
                background: white;
                padding: 30px;
                border-radius: 15px;
                box-shadow: 0 10px 30px rgba(0,0,0,0.2);
                margin-bottom: 20px;
                display: flex;
                justify-content: space-between;
                align-items: center;
            }
            .header-content {
                flex: 1;
                text-align: center;
            }
            .header h1 {
                color: #667eea;
                font-size: 2.5em;
                margin-bottom: 10px;
            }
            .logout-btn {
                background: linear-gradient(135deg, #e74c3c 0%, #c0392b 100%);
                color: white;
                border: none;
                padding: 12px 24px;
                border-radius: 8px;
                cursor: pointer;
                font-size: 14px;
                font-weight: bold;
                transition: transform 0.2s, box-shadow 0.2s;
            }
            .logout-btn:hover {
                transform: translateY(-2px);
                box-shadow: 0 8px 20px rgba(231, 76, 60, 0.4);
            }
            .stats-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
                gap: 20px;
                margin-bottom: 20px;
            }
            .stat-card {
                background: white;
                padding: 25px;
                border-radius: 15px;
                box-shadow: 0 5px 15px rgba(0,0,0,0.1);
                transition: transform 0.3s ease;
            }
            .stat-card:hover {
                transform: translateY(-5px);
                box-shadow: 0 10px 25px rgba(0,0,0,0.2);
            }
            .stat-card h3 {
                color: #667eea;
                margin-bottom: 15px;
                font-size: 1.2em;
            }
            .stat-value {
                font-size: 2.5em;
                font-weight: bold;
                color: #764ba2;
                margin-bottom: 10px;
            }
            .stat-label {
                color: #666;
                font-size: 0.9em;
            }
            .panel {
                background: white;
                padding: 25px;
                border-radius: 15px;
                box-shadow: 0 5px 15px rgba(0,0,0,0.1);
                margin-bottom: 20px;
            }
            .panel h2 {
                color: #667eea;
                margin-bottom: 20px;
                padding-bottom: 10px;
                border-bottom: 2px solid #f0f0f0;
            }
            .current-song {
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                padding: 30px;
                border-radius: 15px;
                margin-bottom: 20px;
            }
            .current-song h2 {
                color: white;
                border-bottom: 2px solid rgba(255,255,255,0.3);
            }
            .queue-item {
                padding: 15px;
                margin: 10px 0;
                background: #f8f9fa;
                border-radius: 10px;
                border-left: 4px solid #667eea;
                transition: all 0.3s ease;
            }
            .queue-item:hover {
                background: #e9ecef;
                transform: translateX(5px);
            }
            .queue-item strong {
                color: #667eea;
            }
            .btn {
                background: #667eea;
                color: white;
                border: none;
                padding: 12px 24px;
                border-radius: 8px;
                cursor: pointer;
                font-size: 1em;
                transition: all 0.3s ease;
                margin: 5px;
            }
            .btn:hover {
                background: #764ba2;
                transform: translateY(-2px);
                box-shadow: 0 5px 15px rgba(0,0,0,0.2);
            }
            .btn-danger {
                background: #dc3545;
            }
            .btn-danger:hover {
                background: #c82333;
            }
            .empty-state {
                text-align: center;
                padding: 40px;
                color: #999;
                font-size: 1.1em;
            }
            .api-links {
                background: #f8f9fa;
                padding: 20px;
                border-radius: 10px;
                margin-top: 20px;
            }
            .api-links a {
                color: #667eea;
                text-decoration: none;
                margin-right: 15px;
                padding: 8px 16px;
                background: white;
                border-radius: 5px;
                display: inline-block;
                margin-bottom: 10px;
                transition: all 0.3s ease;
            }
            .api-links a:hover {
                background: #667eea;
                color: white;
            }
            .loading {
                text-align: center;
                padding: 20px;
                color: #667eea;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <div class="header-content">
                    <h1>🎵 Oopz Music Bot</h1>
                    <p>音乐机器人管理后台</p>
                </div>
                <button class="logout-btn" onclick="logout()">退出登录</button>
            </div>

            <div class="stats-grid">
                <div class="stat-card">
                    <h3>📊 今日播放</h3>
                    <div class="stat-value" id="todayPlays">-</div>
                    <div class="stat-label">总播放次数</div>
                </div>
                <div class="stat-card">
                    <h3>📝 队列长度</h3>
                    <div class="stat-value" id="queueLength">-</div>
                    <div class="stat-label">待播放歌曲</div>
                </div>
                <div class="stat-card">
                    <h3>🖼️ 图片缓存</h3>
                    <div class="stat-value" id="cacheCount">-</div>
                    <div class="stat-label">缓存命中率: <span id="cacheHitRate">-</span></div>
                </div>
                <div class="stat-card">
                    <h3>💾 缓存使用</h3>
                    <div class="stat-value" id="cacheUses">-</div>
                    <div class="stat-label">节省上传次数</div>
                </div>
            </div>

            <div class="current-song">
                <h2>🎶 当前播放</h2>
                <div id="currentSong" class="loading">加载中...</div>
            </div>

            <div class="panel">
                <h2>📋 播放队列</h2>
                <div style="margin-bottom: 15px;">
                    <button class="btn" onclick="playNext()">⏭️ 下一首</button>
                    <button class="btn btn-danger" onclick="clearQueue()">🗑️ 清空队列</button>
                    <button class="btn" onclick="loadQueue()">🔄 刷新</button>
                </div>
                <div id="queueList" class="loading">加载中...</div>
            </div>

            <div class="panel">
                <h2>🔗 API 文档</h2>
                <div class="api-links">
                    <a href="/docs" target="_blank">📚 Swagger 文档</a>
                    <a href="/api/queue/status" target="_blank">📊 队列状态</a>
                    <a href="/api/statistics/today" target="_blank">📈 今日统计</a>
                    <a href="/api/songs/top" target="_blank">🎵 热门歌曲</a>
                    <a href="/api/cache/images" target="_blank">🖼️ 图片缓存</a>
                </div>
            </div>

            <div class="panel">
                <h2>📋 系统日志 <span id="logStatus" style="font-size: 0.6em; color: #4ec9b0;">● 实时</span></h2>
                <div style="margin-bottom: 15px;">
                    <button class="btn" onclick="toggleLogStream()" id="streamToggle">⏸️ 暂停</button>
                    <button class="btn btn-danger" onclick="clearLogs()">🗑️ 清空日志</button>
                    <button class="btn" onclick="clearLogDisplay()">🧹 清空显示</button>
                    <label style="margin-left: 10px;">
                        <input type="checkbox" id="autoScroll" checked> 自动滚动
                    </label>
                </div>
                <div id="logContainer" style="background: #1e1e1e; color: #d4d4d4; padding: 15px; border-radius: 10px; max-height: 600px; overflow-y: auto; font-family: 'Consolas', 'Monaco', monospace; font-size: 13px; line-height: 1.6;">
                    <div style="color: #667eea;">正在连接日志流...</div>
                </div>
            </div>
        </div>

        <script>
            async function loadSummary() {
                try {
                    const res = await fetch('/api/statistics/summary');
                    const data = await res.json();
                    
                    document.getElementById('todayPlays').textContent = data.today.total_plays;
                    document.getElementById('queueLength').textContent = data.queue_length;
                    document.getElementById('cacheCount').textContent = data.image_cache.total || 0;
                    document.getElementById('cacheUses').textContent = data.image_cache.total_uses || 0;
                    
                    const hits = data.today.cache_hits || 0;
                    const misses = data.today.cache_misses || 0;
                    const total = hits + misses;
                    const hitRate = total > 0 ? ((hits / total) * 100).toFixed(1) + '%' : '0%';
                    document.getElementById('cacheHitRate').textContent = hitRate;
                    
                    const current = data.current_playing;
                    const currentDiv = document.getElementById('currentSong');
                    if (current) {
                        // 获取封面图片
                        let coverHtml = '';
                        if (current.attachments && current.attachments.length > 0) {
                            const cover = current.attachments[0];
                            coverHtml = `
                                <div style="text-align: center; margin-bottom: 15px;">
                                    <img src="${cover.url}" 
                                         alt="封面" 
                                         style="max-width: 200px; max-height: 200px; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.3);">
                                </div>
                            `;
                        }
                        
                        currentDiv.innerHTML = `
                            ${coverHtml}
                            <div style="font-size: 1.5em; margin: 10px 0;">
                                <strong>${current.name}</strong>
                            </div>
                            <div style="margin: 5px 0;">🎤 ${current.artists || '未知歌手'}</div>
                            <div style="margin: 5px 0;">💿 ${current.album || '未知专辑'}</div>
                            <div style="margin: 5px 0;">📱 平台: ${current.platform}</div>
                            ${current.duration ? `<div style="margin: 5px 0;">⏱ 时长: ${current.duration}</div>` : ''}
                        `;
                    } else {
                        currentDiv.innerHTML = '<div class="empty-state">暂无播放</div>';
                    }
                } catch (e) {
                    console.error('加载统计失败:', e);
                }
            }

            async function loadQueue() {
                try {
                    const res = await fetch('/api/queue/list?limit=20');
                    const data = await res.json();
                    
                    const queueDiv = document.getElementById('queueList');
                    if (data.queue && data.queue.length > 0) {
                        queueDiv.innerHTML = data.queue.map((song, idx) => {
                            // 获取封面图片
                            let coverHtml = '';
                            if (song.attachments && song.attachments.length > 0) {
                                const cover = song.attachments[0];
                                coverHtml = `
                                    <img src="${cover.url}" 
                                         alt="封面" 
                                         style="width: 60px; height: 60px; border-radius: 8px; margin-right: 15px; object-fit: cover; box-shadow: 0 2px 8px rgba(0,0,0,0.2);">
                                `;
                            } else {
                                // 如果没有封面，显示占位图标
                                coverHtml = `
                                    <div style="width: 60px; height: 60px; border-radius: 8px; margin-right: 15px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); display: flex; align-items: center; justify-content: center; font-size: 24px;">
                                        🎵
                                    </div>
                                `;
                            }
                            
                            return `
                                <div class="queue-item" style="display: flex; align-items: center;">
                                    ${coverHtml}
                                    <div style="flex: 1;">
                                        <div><strong>${idx + 1}. ${song.name}</strong></div>
                                        <div>🎤 ${song.artists || '未知'} | 💿 ${song.album || '未知'}</div>
                                        <div style="font-size: 0.9em; color: #666; margin-top: 5px;">
                                            📱 ${song.platform} | ⏱️ ${song.duration || '-'}
                                        </div>
                                    </div>
                                </div>
                            `;
                        }).join('');
                    } else {
                        queueDiv.innerHTML = '<div class="empty-state">队列为空</div>';
                    }
                } catch (e) {
                    console.error('加载队列失败:', e);
                    document.getElementById('queueList').innerHTML = '<div class="empty-state">加载失败</div>';
                }
            }

            async function playNext() {
                try {
                    // 调用下一首API（会自动使用 Redis 缓存的默认频道）
                    const res = await fetch('/api/queue/next', { method: 'POST' });
                    const data = await res.json();
                    alert(data.message);
                    loadSummary();
                    loadQueue();
                } catch (e) {
                    alert('操作失败: ' + e.message);
                }
            }

            async function clearQueue() {
                if (!confirm('确定要清空队列吗？')) return;
                try {
                    await fetch('/api/queue/clear', { method: 'DELETE' });
                    alert('队列已清空');
                    loadQueue();
                    loadSummary();
                } catch (e) {
                    alert('操作失败: ' + e.message);
                }
            }

            // 退出登录
            async function logout() {
                try {
                    await fetch('/api/auth/logout', { method: 'POST' });
                    window.location.href = '/login';
                } catch (e) {
                    alert('退出登录失败');
                }
            }

            // 日志流相关
            let logEventSource = null;
            let logStreamPaused = false;
            let logLineCount = 0;
            const MAX_LOG_LINES = 500; // 最多保留的日志行数

            function getLogColor(log) {
                if (log.includes('[ERROR]')) return { color: '#f48771', icon: '❌' };
                if (log.includes('[WARNING]')) return { color: '#dcdcaa', icon: '⚠️' };
                if (log.includes('[INFO]')) return { color: '#4ec9b0', icon: 'ℹ️' };
                if (log.includes('[DEBUG]')) return { color: '#9cdcfe', icon: '🔍' };
                return { color: '#d4d4d4', icon: '' };
            }

            function appendLog(log) {
                if (logStreamPaused) return;
                
                const logContainer = document.getElementById('logContainer');
                const { color, icon } = getLogColor(log);
                
                const logLine = document.createElement('div');
                logLine.style.color = color;
                logLine.style.marginBottom = '3px';
                logLine.textContent = `${icon} ${log}`;
                
                logContainer.appendChild(logLine);
                logLineCount++;
                
                // 限制日志行数，删除旧的
                if (logLineCount > MAX_LOG_LINES) {
                    logContainer.removeChild(logContainer.firstChild);
                    logLineCount--;
                }
                
                // 自动滚动
                if (document.getElementById('autoScroll').checked) {
                    logContainer.scrollTop = logContainer.scrollHeight;
                }
            }

            function startLogStream() {
                if (logEventSource) {
                    logEventSource.close();
                }
                
                logEventSource = new EventSource('/api/logs/stream');
                
                logEventSource.onopen = () => {
                    document.getElementById('logStatus').innerHTML = '● 实时';
                    document.getElementById('logStatus').style.color = '#4ec9b0';
                    console.log('日志流已连接');
                };
                
                logEventSource.onmessage = (event) => {
                    appendLog(event.data);
                };
                
                logEventSource.onerror = (error) => {
                    console.error('日志流错误:', error);
                    document.getElementById('logStatus').innerHTML = '● 断开';
                    document.getElementById('logStatus').style.color = '#f48771';
                    
                    // 5秒后尝试重连
                    setTimeout(() => {
                        if (!logStreamPaused) {
                            console.log('尝试重连日志流...');
                            startLogStream();
                        }
                    }, 5000);
                };
            }

            function toggleLogStream() {
                const btn = document.getElementById('streamToggle');
                if (logStreamPaused) {
                    // 恢复
                    logStreamPaused = false;
                    startLogStream();
                    btn.textContent = '⏸️ 暂停';
                } else {
                    // 暂停
                    logStreamPaused = true;
                    if (logEventSource) {
                        logEventSource.close();
                    }
                    document.getElementById('logStatus').innerHTML = '● 暂停';
                    document.getElementById('logStatus').style.color = '#dcdcaa';
                    btn.textContent = '▶️ 继续';
                }
            }

            function clearLogDisplay() {
                document.getElementById('logContainer').innerHTML = '';
                logLineCount = 0;
            }

            // 清空日志文件
            async function clearLogs() {
                if (!confirm('确定要清空日志文件吗？此操作不可恢复！')) return;
                try {
                    const res = await fetch('/api/logs/clear', { method: 'DELETE' });
                    const data = await res.json();
                    if (data.status === 'success') {
                        alert('日志文件已清空');
                        clearLogDisplay();
                    } else {
                        alert('清空失败: ' + data.message);
                    }
                } catch (e) {
                    alert('操作失败: ' + e.message);
                }
            }

            // 初始加载
            loadSummary();
            loadQueue();
            startLogStream(); // 启动日志流

            // 自动刷新统计和队列
            setInterval(() => {
                loadSummary();
                loadQueue();
            }, 10000); // 每 10 秒刷新
            
            // 页面关闭时断开日志流
            window.addEventListener('beforeunload', () => {
                if (logEventSource) {
                    logEventSource.close();
                }
            });
        </script>
    </body>
    </html>
    """


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
