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
import psutil
import os
import threading
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from typing import Optional, List

import requests
from fastapi import FastAPI, HTTPException, Query, Request, Form
from fastapi.responses import StreamingResponse, HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis
from starlette.responses import Response

from database import init_database, ImageCache, SongCache, Statistics
from queue_manager import QueueManager
from config import REDIS_CONFIG, AudioService
import oopz_sender
from auth import require_auth, verify_credentials, create_login_response, create_logout_response, \
    get_token_from_request, verify_token
from netease import NeteaseCloud
from bilibili import Bilibili
from qqmusic import QQmusic

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

# 初始化音乐API
try:
    netease_api = NeteaseCloud()
except Exception as e:
    print(f"[WARNING] 网易云API初始化失败: {e}")
    netease_api = None

try:
    bilibili_api = Bilibili()
except Exception as e:
    print(f"[WARNING] B站API初始化失败: {e}")
    bilibili_api = None

try:
    qq_api = QQmusic()
except Exception as e:
    print(f"[WARNING] QQ音乐API初始化失败: {e}")
    qq_api = None

# 系统监控 - 记录启动时间
app_start_time = datetime.now()
process = psutil.Process()

# 网络流量监控 - 记录上次数据用于计算速度，使用锁保证线程安全
last_network_data = {"timestamp": datetime.now(), "bytes_sent": 0, "bytes_recv": 0}
network_data_lock = threading.Lock()

# 系统监控缓存
system_info_cache = {"data": None, "timestamp": None, "lock": threading.Lock()}
CACHE_DURATION = 2  # 缓存2秒


# CPU监控预热任务
def cpu_warmup_task():
    """定期调用CPU监控以获得准确的使用率数据"""
    while True:
        try:
            psutil.cpu_percent(interval=1)  # 1秒间隔，保持数据新鲜
            time.sleep(5)  # 每5秒执行一次
        except Exception:
            time.sleep(10)  # 出错时延长等待


# 启动CPU预热线程
cpu_warmup_thread = threading.Thread(target=cpu_warmup_task, daemon=True)
cpu_warmup_thread.start()


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

    # 初始化系统监控 - 预热网络数据
    try:
        net_io = psutil.net_io_counters()
        global last_network_data
        last_network_data.update({
            "timestamp": datetime.now(),
            "bytes_sent": net_io.bytes_sent,
            "bytes_recv": net_io.bytes_recv
        })
    except Exception as e:
        print(f"系统监控初始化警告: {e}")

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
    # allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def custom_cors(request: Request, call_next):
    origin = request.headers.get("origin")
    response: Response = await call_next(request)
    if origin:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,DELETE,OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Authorization,Content-Type"
    return response

# @app.middleware("http")
# async def custom_cors_middleware(request: Request, call_next):
#     origin = request.headers.get("origin")
#     response: Response = await call_next(request)
#
#     if origin:
#         response.headers["Access-Control-Allow-Origin"] = origin
#         response.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,DELETE,OPTIONS"
#         response.headers["Access-Control-Allow-Headers"] = "Authorization,Content-Type"
#         response.headers["Access-Control-Allow-Credentials"] = "true"
#     return response


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
    cached_status = queue_manager.player_status_from_service()
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


def refetch_play_url(song_data: dict) -> Optional[str]:
    """重新获取播放URL（当URL缺失或过期时）
    
    Args:
        song_data: 歌曲数据，需包含 song_id 和 platform
    
    Returns:
        播放URL，如果获取失败返回 None
    """
    platform = song_data.get('platform')
    song_id = song_data.get('song_id')
    
    if not platform or not song_id:
        print(f"[ERROR] 无法重新获取URL: 缺少 platform 或 song_id")
        return None
    
    try:
        if platform == 'netease' and netease_api:
            result = netease_api.song(song_id)
            if result['code'] == 'success':
                url = result['data']['url'].get('url')
                print(f"[INFO] 成功重新获取网易云播放URL: {song_id}")
                return url
                
        elif platform == 'bilibili' and bilibili_api:
            result = bilibili_api.summarize(song_id)
            if result['code'] == 'success':
                url = result['data']['url']
                print(f"[INFO] 成功重新获取B站播放URL: {song_id}")
                return url
                
        elif platform == 'qq' and qq_api:
            # QQ音乐需要额外的参数
            print(f"[WARNING] QQ音乐需要 songmid 和 strMediaMid，无法从 song_id 直接获取")
            return None
            
        print(f"[ERROR] 不支持的平台或API未初始化: {platform}")
        return None
        
    except Exception as e:
        print(f"[ERROR] 重新获取播放URL失败: {e}")
        return None


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
            import uuid

            # 生成播放UUID并保存到歌曲数据
            play_uuid = str(uuid.uuid4())
            next_song['play_uuid'] = play_uuid
            queue_manager.set_current(next_song)

            # 🔥 更新播放统计（实际播放时）
            SongCache.update_play_stats(
                song_id=next_song.get('song_id'),
                platform=next_song.get('platform'),
                channel_id=channel or next_song.get('channel'),
                user_id=None  # Web API 调用时没有用户信息
            )

            # 更新平台统计
            Statistics.update_today(next_song.get('platform'), cache_hit=False)

            # 检查URL是否存在，如果不存在则重新获取
            url = next_song.get('url')
            if not url:
                print(f"[WARNING] 歌曲缺少播放URL，尝试重新获取: {next_song.get('name')}")
                url = refetch_play_url(next_song)
                if url:
                    next_song['url'] = url  # 更新歌曲数据
                    print(f"[INFO] 已更新播放URL")
                else:
                    raise ValueError("无法获取播放URL，歌曲链接可能已过期")
            
            model = 'qq' if next_song.get('platform') == 'qq' else None

            params = {"url": url, "uuid": play_uuid}
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
    """获取汇总统计（包含系统监控信息）"""
    today = Statistics.get_today()
    image_stats = ImageCache.get_stats()
    queue_length = queue_manager.get_queue_length()
    system_info = get_cached_system_info()  # 获取缓存的系统信息

    return {
        "today": today,
        "queue_length": queue_length,
        "image_cache": image_stats,
        "current_playing": queue_manager.get_current(),
        "system": system_info  # 添加系统监控信息
    }


def get_china_time() -> str:
    """获取中国时区的当前时间字符串 (UTC+8)"""
    china_tz = timezone(timedelta(hours=8))
    return datetime.now(china_tz).strftime('%Y-%m-%d %H:%M:%S')


def format_bytes(bytes_value: int) -> str:
    """格式化字节数为可读格式"""
    if bytes_value == 0:
        return "0 B"

    units = ['B', 'KB', 'MB', 'GB', 'TB']
    i = 0
    while bytes_value >= 1024 and i < len(units) - 1:
        bytes_value /= 1024.0
        i += 1

    return f"{bytes_value:.1f} {units[i]}"


def format_duration(seconds: float) -> str:
    """格式化秒数为可读的时长格式"""
    if seconds < 60:
        return f"{int(seconds)}秒"
    elif seconds < 3600:
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}分{secs}秒"
    elif seconds < 86400:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{hours}小时{minutes}分"
    else:
        days = int(seconds // 86400)
        hours = int((seconds % 86400) // 3600)
        return f"{days}天{hours}小时"


def get_cached_system_info() -> dict:
    """获取缓存的系统监控信息"""
    global system_info_cache

    with system_info_cache["lock"]:
        now = datetime.now()

        # 检查缓存是否有效
        if (system_info_cache["data"] is not None and
                system_info_cache["timestamp"] is not None and
                (now - system_info_cache["timestamp"]).total_seconds() < CACHE_DURATION):
            return system_info_cache["data"]

        # 缓存过期或不存在，重新获取
        try:
            # 运行时长
            uptime_seconds = (now - app_start_time).total_seconds()

            # CPU信息 - 非阻塞
            cpu_percent = psutil.cpu_percent(interval=0)
            cpu_count = psutil.cpu_count()

            # 内存信息
            memory = psutil.virtual_memory()

            # 网络信息（简化版）
            net_io = psutil.net_io_counters()

            # 计算网络速度
            global last_network_data
            with network_data_lock:
                time_diff = (now - last_network_data["timestamp"]).total_seconds()

                if time_diff > 0 and last_network_data["bytes_sent"] > 0:
                    bytes_sent_per_sec = max(0, (net_io.bytes_sent - last_network_data["bytes_sent"]) / time_diff)
                    bytes_recv_per_sec = max(0, (net_io.bytes_recv - last_network_data["bytes_recv"]) / time_diff)
                else:
                    bytes_sent_per_sec = 0
                    bytes_recv_per_sec = 0

                # 更新上次数据
                last_network_data = {
                    "timestamp": now,
                    "bytes_sent": net_io.bytes_sent,
                    "bytes_recv": net_io.bytes_recv
                }

            # 进程信息 - 带错误处理
            global process
            try:
                process_memory = process.memory_info()
                process_cpu = process.cpu_percent()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                # 如果进程出错，重新获取
                try:
                    process = psutil.Process()
                    process_memory = process.memory_info()
                    process_cpu = process.cpu_percent()
                except Exception:
                    # 如果还是出错，使用默认值
                    process_memory = type('obj', (object,), {'rss': 0, 'vms': 0})
                    process_cpu = 0.0

            # 构建返回数据
            data = {
                "timestamp": get_china_time(),
                "uptime_formatted": format_duration(uptime_seconds),
                "cpu_usage": round(cpu_percent, 1),
                "cpu_count": cpu_count,
                "memory_usage": round(memory.percent, 1),
                "memory_used_formatted": format_bytes(memory.used),
                "memory_total_formatted": format_bytes(memory.total),
                "network_speed_up": format_bytes(bytes_sent_per_sec) + "/s",
                "network_speed_down": format_bytes(bytes_recv_per_sec) + "/s",
                "process_memory_formatted": format_bytes(process_memory.rss),
                "process_cpu": round(process_cpu, 1)
            }

            # 更新缓存
            system_info_cache["data"] = data
            system_info_cache["timestamp"] = now

            return data

        except Exception as e:
            # 如果获取失败，返回错误信息
            error_data = {
                "error": str(e),
                "timestamp": get_china_time()
            }
            return error_data


# ========= 系统监控 API =========
@app.get("/api/system/info")
@require_auth
async def get_system_info(request: Request):
    """获取系统监控信息"""
    try:
        # 运行时长
        uptime_seconds = (datetime.now() - app_start_time).total_seconds()

        # CPU 信息 - 非阻塞获取（使用上次调用的结果）
        cpu_percent = psutil.cpu_percent(interval=0)
        cpu_count = psutil.cpu_count()
        cpu_freq = psutil.cpu_freq()

        # 内存信息 - 实时
        memory = psutil.virtual_memory()

        # 磁盘信息 - 实时
        disk = psutil.disk_usage('.')

        # 网络信息 - 计算实时速度
        net_io = psutil.net_io_counters()
        current_time = datetime.now()

        # 计算网络速度（线程安全）
        global last_network_data
        with network_data_lock:
            time_diff = (current_time - last_network_data["timestamp"]).total_seconds()

            if time_diff > 0 and last_network_data["bytes_sent"] > 0:
                bytes_sent_per_sec = max(0, (net_io.bytes_sent - last_network_data["bytes_sent"]) / time_diff)
                bytes_recv_per_sec = max(0, (net_io.bytes_recv - last_network_data["bytes_recv"]) / time_diff)
            else:
                bytes_sent_per_sec = 0
                bytes_recv_per_sec = 0

            # 更新上次数据
            last_network_data = {
                "timestamp": current_time,
                "bytes_sent": net_io.bytes_sent,
                "bytes_recv": net_io.bytes_recv
            }

        # 进程信息 - 实时获取当前进程资源使用
        global process
        try:
            process_memory = process.memory_info()
            process_cpu = process.cpu_percent()
        except psutil.NoSuchProcess:
            # 如果进程不存在，重新获取当前进程
            process = psutil.Process()
            process_memory = process.memory_info()
            process_cpu = process.cpu_percent()

        return {
            "timestamp": get_china_time(),
            "uptime": {
                "seconds": int(uptime_seconds),
                "formatted": format_duration(uptime_seconds)
            },
            "cpu": {
                "usage_percent": round(cpu_percent, 1),
                "count": cpu_count,
                "frequency_mhz": round(cpu_freq.current, 1) if cpu_freq else None
            },
            "memory": {
                "total": memory.total,
                "available": memory.available,
                "used": memory.used,
                "usage_percent": round(memory.percent, 1),
                "total_formatted": format_bytes(memory.total),
                "available_formatted": format_bytes(memory.available),
                "used_formatted": format_bytes(memory.used)
            },
            "disk": {
                "total": disk.total,
                "used": disk.used,
                "free": disk.free,
                "usage_percent": round((disk.used / disk.total) * 100, 1),
                "total_formatted": format_bytes(disk.total),
                "used_formatted": format_bytes(disk.used),
                "free_formatted": format_bytes(disk.free)
            },
            "network": {
                "bytes_sent": net_io.bytes_sent,
                "bytes_recv": net_io.bytes_recv,
                "packets_sent": net_io.packets_sent,
                "packets_recv": net_io.packets_recv,
                "bytes_sent_formatted": format_bytes(net_io.bytes_sent),
                "bytes_recv_formatted": format_bytes(net_io.bytes_recv),
                "speed_sent_per_sec": bytes_sent_per_sec,
                "speed_recv_per_sec": bytes_recv_per_sec,
                "speed_sent_formatted": format_bytes(bytes_sent_per_sec) + "/s",
                "speed_recv_formatted": format_bytes(bytes_recv_per_sec) + "/s"
            },
            "process": {
                "memory_rss": process_memory.rss,
                "memory_vms": process_memory.vms,
                "cpu_percent": round(process_cpu, 1),
                "memory_rss_formatted": format_bytes(process_memory.rss),
                "memory_vms_formatted": format_bytes(process_memory.vms)
            }
        }
    except Exception as e:
        return {"error": str(e), "timestamp": get_china_time()}


@app.get("/api/system/stats")
@require_auth
async def get_system_stats(request: Request):
    """获取简化的系统统计信息"""
    try:
        # 运行时长
        uptime_seconds = (datetime.now() - app_start_time).total_seconds()

        # 快速获取实时关键指标
        cpu_percent = psutil.cpu_percent(interval=0.1)  # 快速获取实时CPU
        memory = psutil.virtual_memory()

        return {
            "uptime": format_duration(uptime_seconds),
            "cpu_usage": f"{cpu_percent}%",
            "memory_usage": f"{memory.percent}%",
            "memory_used": format_bytes(memory.used),
            "memory_total": format_bytes(memory.total),
            "timestamp": get_china_time()
        }
    except Exception as e:
        return {"error": str(e)}


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


@app.get("/system", response_class=HTMLResponse)
async def system_monitoring():
    """系统监控页面"""
    return HTMLResponse(content="""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🖥️ 系统监控 - Oopz Music Bot</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; 
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: #333;
            min-height: 100vh;
        }
        .container { 
            max-width: 1200px; 
            margin: 0 auto; 
            padding: 20px;
        }
        .header {
            text-align: center;
            color: white;
            margin-bottom: 30px;
        }
        .header h1 { 
            font-size: 2.5rem; 
            margin-bottom: 10px;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
        }
        .last-update {
            background: rgba(255,255,255,0.2);
            padding: 5px 15px;
            border-radius: 20px;
            display: inline-block;
            font-size: 0.9rem;
        }
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
        }
        .card {
            background: white;
            border-radius: 15px;
            padding: 25px;
            box-shadow: 0 8px 32px rgba(0,0,0,0.1);
            backdrop-filter: blur(10px);
            transition: transform 0.3s ease, box-shadow 0.3s ease;
        }
        .card:hover {
            transform: translateY(-5px);
            box-shadow: 0 12px 40px rgba(0,0,0,0.15);
        }
        .card-title {
            font-size: 1.3rem;
            font-weight: 600;
            margin-bottom: 20px;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .card-title .icon { font-size: 1.5rem; }
        .metric {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 15px;
            padding: 10px 0;
            border-bottom: 1px solid #f0f0f0;
        }
        .metric:last-child { 
            border-bottom: none; 
            margin-bottom: 0;
        }
        .metric-label {
            font-weight: 500;
            color: #666;
        }
        .metric-value {
            font-weight: 600;
            font-size: 1.1rem;
            color: #333;
        }
        .progress-bar {
            width: 100%;
            height: 20px;
            background: #f0f0f0;
            border-radius: 10px;
            overflow: hidden;
            margin-top: 5px;
            position: relative;
        }
        .progress-fill {
            height: 100%;
            border-radius: 10px;
            transition: width 0.5s ease;
            position: relative;
            overflow: hidden;
        }
        .progress-cpu { background: linear-gradient(45deg, #4facfe 0%, #00f2fe 100%); }
        .progress-memory { background: linear-gradient(45deg, #43e97b 0%, #38f9d7 100%); }
        .progress-disk { background: linear-gradient(45deg, #fa709a 0%, #fee140 100%); }
        .status-good { color: #28a745; }
        .status-warning { color: #ffc107; }
        .status-danger { color: #dc3545; }
        .loading {
            text-align: center;
            color: #666;
            padding: 40px;
            font-size: 1.1rem;
        }
        .error {
            background: #f8d7da;
            color: #721c24;
            padding: 15px;
            border-radius: 10px;
            margin: 20px 0;
            border: 1px solid #f5c6cb;
        }
        .nav-btn {
            position: fixed;
            top: 20px;
            background: rgba(255,255,255,0.2);
            border: 2px solid white;
            color: white;
            padding: 12px 20px;
            border-radius: 25px;
            cursor: pointer;
            font-weight: 600;
            transition: all 0.3s ease;
            backdrop-filter: blur(10px);
            text-decoration: none;
            display: inline-block;
        }
        .nav-btn:hover {
            background: white;
            color: #667eea;
        }
        .refresh-btn { right: 20px; }
        .back-btn { left: 20px; }
        .auto-refresh {
            text-align: center;
            color: white;
            margin-top: 20px;
            font-size: 0.9rem;
            opacity: 0.8;
        }
        @media (max-width: 768px) {
            .container { padding: 10px; }
            .header h1 { font-size: 2rem; }
            .grid { grid-template-columns: 1fr; }
            .nav-btn { 
                position: static; 
                margin: 10px;
                display: inline-block;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <a href="/" class="nav-btn back-btn">🏠 返回</a>
        <button class="nav-btn refresh-btn" onclick="loadSystemInfo()">🔄 刷新</button>
        
        <div class="header">
            <h1>🖥️ 系统监控</h1>
            <div class="last-update">最后更新: <span id="lastUpdate">--</span></div>
        </div>
        
        <div id="content">
            <div class="loading">📊 正在加载实时系统监控数据...</div>
        </div>
        
        <div class="auto-refresh">
            ⏱️ 每5秒自动更新，显示实时占用情况
        </div>
    </div>

    <script>
        let authToken = localStorage.getItem('authToken');
        let updateInterval;

        function getStatusClass(percent) {
            if (percent < 50) return 'status-good';
            if (percent < 80) return 'status-warning';
            return 'status-danger';
        }

        async function loadSystemInfo() {
            try {
                const response = await fetch('/api/system/info', {
                    headers: authToken ? { 'Authorization': `Bearer ${authToken}` } : {}
                });
                
                if (response.status === 401) {
                    document.getElementById('content').innerHTML = `
                        <div class="error">
                            🔐 需要登录才能查看系统监控信息
                            <br><br>
                            <a href="/login" style="color: #721c24; font-weight: bold;">前往登录</a>
                        </div>
                    `;
                    return;
                }

                const data = await response.json();
                
                if (data.error) {
                    document.getElementById('content').innerHTML = `
                        <div class="error">❌ 获取系统信息失败: ${data.error}</div>
                    `;
                    return;
                }

                document.getElementById('lastUpdate').textContent = data.timestamp;
                
                document.getElementById('content').innerHTML = `
                    <div class="grid">
                        <!-- CPU卡片 -->
                        <div class="card">
                            <div class="card-title">
                                <span class="icon">🖥️</span>
                                CPU 实时监控
                            </div>
                            <div class="metric">
                                <span class="metric-label">实时使用率</span>
                                <span class="metric-value ${getStatusClass(data.cpu.usage_percent)}">${data.cpu.usage_percent}%</span>
                            </div>
                            <div class="progress-bar">
                                <div class="progress-fill progress-cpu" style="width: ${data.cpu.usage_percent}%"></div>
                            </div>
                            <div class="metric">
                                <span class="metric-label">核心数</span>
                                <span class="metric-value">${data.cpu.count} 核</span>
                            </div>
                            ${data.cpu.frequency_mhz ? `
                            <div class="metric">
                                <span class="metric-label">频率</span>
                                <span class="metric-value">${data.cpu.frequency_mhz} MHz</span>
                            </div>
                            ` : ''}
                        </div>

                        <!-- 内存卡片 -->
                        <div class="card">
                            <div class="card-title">
                                <span class="icon">🧠</span>
                                内存实时监控
                            </div>
                            <div class="metric">
                                <span class="metric-label">实时使用率</span>
                                <span class="metric-value ${getStatusClass(data.memory.usage_percent)}">${data.memory.usage_percent}%</span>
                            </div>
                            <div class="progress-bar">
                                <div class="progress-fill progress-memory" style="width: ${data.memory.usage_percent}%"></div>
                            </div>
                            <div class="metric">
                                <span class="metric-label">已使用</span>
                                <span class="metric-value">${data.memory.used_formatted}</span>
                            </div>
                            <div class="metric">
                                <span class="metric-label">可用</span>
                                <span class="metric-value">${data.memory.available_formatted}</span>
                            </div>
                            <div class="metric">
                                <span class="metric-label">总内存</span>
                                <span class="metric-value">${data.memory.total_formatted}</span>
                            </div>
                        </div>

                        <!-- 磁盘卡片 -->
                        <div class="card">
                            <div class="card-title">
                                <span class="icon">💾</span>
                                磁盘使用情况
                            </div>
                            <div class="metric">
                                <span class="metric-label">使用率</span>
                                <span class="metric-value ${getStatusClass(data.disk.usage_percent)}">${data.disk.usage_percent}%</span>
                            </div>
                            <div class="progress-bar">
                                <div class="progress-fill progress-disk" style="width: ${data.disk.usage_percent}%"></div>
                            </div>
                            <div class="metric">
                                <span class="metric-label">已使用</span>
                                <span class="metric-value">${data.disk.used_formatted}</span>
                            </div>
                            <div class="metric">
                                <span class="metric-label">可用空间</span>
                                <span class="metric-value">${data.disk.free_formatted}</span>
                            </div>
                            <div class="metric">
                                <span class="metric-label">总容量</span>
                                <span class="metric-value">${data.disk.total_formatted}</span>
                            </div>
                        </div>

                        <!-- 网络卡片 -->
                        <div class="card">
                            <div class="card-title">
                                <span class="icon">🌐</span>
                                网络流量统计
                            </div>
                            <div class="metric">
                                <span class="metric-label">发送流量</span>
                                <span class="metric-value">${data.network.bytes_sent_formatted}</span>
                            </div>
                            <div class="metric">
                                <span class="metric-label">接收流量</span>
                                <span class="metric-value">${data.network.bytes_recv_formatted}</span>
                            </div>
                            <div class="metric">
                                <span class="metric-label">发送包数</span>
                                <span class="metric-value">${data.network.packets_sent.toLocaleString()}</span>
                            </div>
                            <div class="metric">
                                <span class="metric-label">接收包数</span>
                                <span class="metric-value">${data.network.packets_recv.toLocaleString()}</span>
                            </div>
                        </div>

                        <!-- 进程信息卡片 -->
                        <div class="card">
                            <div class="card-title">
                                <span class="icon">⚙️</span>
                                Bot进程实时监控
                            </div>
                            <div class="metric">
                                <span class="metric-label">CPU使用率</span>
                                <span class="metric-value ${getStatusClass(data.process.cpu_percent)}">${data.process.cpu_percent}%</span>
                            </div>
                            <div class="metric">
                                <span class="metric-label">物理内存</span>
                                <span class="metric-value">${data.process.memory_rss_formatted}</span>
                            </div>
                            <div class="metric">
                                <span class="metric-label">虚拟内存</span>
                                <span class="metric-value">${data.process.memory_vms_formatted}</span>
                            </div>
                        </div>

                        <!-- 系统信息卡片 -->
                        <div class="card">
                            <div class="card-title">
                                <span class="icon">📊</span>
                                运行状态
                            </div>
                            <div class="metric">
                                <span class="metric-label">运行时长</span>
                                <span class="metric-value">${data.uptime.formatted}</span>
                            </div>
                            <div class="metric">
                                <span class="metric-label">更新时间</span>
                                <span class="metric-value">${data.timestamp}</span>
                            </div>
                        </div>
                    </div>
                `;
                
            } catch (error) {
                console.error('加载系统信息失败:', error);
                document.getElementById('content').innerHTML = `
                    <div class="error">❌ 连接失败: ${error.message}</div>
                `;
            }
        }

        // 页面加载时获取认证信息
        window.addEventListener('load', () => {
            // 尝试从URL参数获取token
            const urlParams = new URLSearchParams(window.location.search);
            const tokenFromUrl = urlParams.get('token');
            if (tokenFromUrl) {
                authToken = tokenFromUrl;
                localStorage.setItem('authToken', authToken);
            }

            // 初始加载
            loadSystemInfo();
            
            // 设置定时更新 - 每5秒更新一次确保实时性
            updateInterval = setInterval(loadSystemInfo, 5000);
        });

        // 页面离开时清理定时器
        window.addEventListener('beforeunload', () => {
            if (updateInterval) {
                clearInterval(updateInterval);
            }
        });
    </script>
</body>
</html>
""")


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
                <div class="stat-card">
                    <h3>🖥️ CPU使用率</h3>
                    <div class="stat-value" id="cpuUsage">-</div>
                    <div class="stat-label">实时监控</div>
                </div>
                <div class="stat-card">
                    <h3>🧠 内存使用</h3>
                    <div class="stat-value" id="memoryUsage">-</div>
                    <div class="stat-label">实时监控</div>
                </div>
                <div class="stat-card">
                    <h3>📡 网络速度</h3>
                    <div class="stat-value" id="networkSpeed">-</div>
                    <div class="stat-label">实时上传/下载</div>
                </div>
            </div>

            <div class="current-song">
                <h2>🎶 当前播放</h2>
                <div id="currentSong" class="loading">加载中...</div>
            </div>

            <div class="panel">
                <h2>🖥️ 系统详情</h2>
                <div id="systemDetails" class="loading">加载中...</div>
                <div class="api-links" style="margin-top: 20px;">
                    <a href="/system" target="_blank">📊 详细监控</a>
                </div>
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
                    
                    // 更新系统监控信息
                    const system = data.system;
                    if (system && !system.error) {
                        document.getElementById('cpuUsage').textContent = system.cpu_usage + '%';
                        document.getElementById('memoryUsage').textContent = system.memory_usage + '%';
                        document.getElementById('networkSpeed').textContent = `↑${system.network_speed_up} ↓${system.network_speed_down}`;
                    } else {
                        document.getElementById('cpuUsage').textContent = '-';
                        document.getElementById('memoryUsage').textContent = '-';
                        document.getElementById('networkSpeed').textContent = '-';
                    }
                    
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

            async function loadSystemDetails() {
                try {
                    const res = await fetch('/api/statistics/summary');
                    const data = await res.json();
                    
                    const system = data.system;
                    const systemDiv = document.getElementById('systemDetails');
                    
                    if (system && !system.error) {
                        systemDiv.innerHTML = `
                            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px;">
                                <div style="background: #f8f9fa; padding: 15px; border-radius: 10px; text-align: center;">
                                    <div style="font-size: 1.2em; font-weight: bold; color: #667eea;">🖥️ CPU</div>
                                    <div style="font-size: 1.8em; font-weight: bold; margin: 10px 0; color: ${system.cpu_usage > 80 ? '#dc3545' : system.cpu_usage > 50 ? '#ffc107' : '#28a745'}">${system.cpu_usage}%</div>
                                    <div style="font-size: 0.9em; color: #666;">${system.cpu_count} 核心</div>
                                </div>
                                <div style="background: #f8f9fa; padding: 15px; border-radius: 10px; text-align: center;">
                                    <div style="font-size: 1.2em; font-weight: bold; color: #667eea;">🧠 内存</div>
                                    <div style="font-size: 1.8em; font-weight: bold; margin: 10px 0; color: ${system.memory_usage > 80 ? '#dc3545' : system.memory_usage > 70 ? '#ffc107' : '#28a745'}">${system.memory_usage}%</div>
                                    <div style="font-size: 0.9em; color: #666;">${system.memory_used_formatted} / ${system.memory_total_formatted}</div>
                                </div>
                                <div style="background: #f8f9fa; padding: 15px; border-radius: 10px; text-align: center;">
                                    <div style="font-size: 1.2em; font-weight: bold; color: #667eea;">🌐 网络</div>
                                    <div style="font-size: 1.3em; font-weight: bold; margin: 10px 0; color: #667eea;">
                                        ↑${system.network_speed_up}<br>
                                        ↓${system.network_speed_down}
                                    </div>
                                    <div style="font-size: 0.9em; color: #666;">实时速度</div>
                                </div>
                                <div style="background: #f8f9fa; padding: 15px; border-radius: 10px; text-align: center;">
                                    <div style="font-size: 1.2em; font-weight: bold; color: #667eea;">⚙️ Bot进程</div>
                                    <div style="font-size: 1.5em; font-weight: bold; margin: 10px 0; color: #667eea;">${system.process_cpu}%</div>
                                    <div style="font-size: 0.9em; color: #666;">${system.process_memory_formatted}</div>
                                </div>
                                <div style="background: #f8f9fa; padding: 15px; border-radius: 10px; text-align: center;">
                                    <div style="font-size: 1.2em; font-weight: bold; color: #667eea;">⏱️ 运行时长</div>
                                    <div style="font-size: 1.5em; font-weight: bold; margin: 10px 0; color: #667eea;">${system.uptime_formatted}</div>
                                    <div style="font-size: 0.9em; color: #666;">持续在线</div>
                                </div>
                                <div style="background: #f8f9fa; padding: 15px; border-radius: 10px; text-align: center;">
                                    <div style="font-size: 1.2em; font-weight: bold; color: #667eea;">🕐 更新时间</div>
                                    <div style="font-size: 1.2em; font-weight: bold; margin: 10px 0; color: #667eea;">${system.timestamp}</div>
                                    <div style="font-size: 0.9em; color: #666;">实时数据</div>
                                </div>
                            </div>
                        `;
                    } else {
                        systemDiv.innerHTML = `
                            <div class="error">
                                ❌ 获取系统信息失败: ${system ? system.error : '未知错误'}
                            </div>
                        `;
                    }
                } catch (e) {
                    console.error('加载系统详情失败:', e);
                    document.getElementById('systemDetails').innerHTML = `
                        <div class="error">❌ 连接失败: ${e.message}</div>
                    `;
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
            loadSystemDetails(); // 加载系统详情
            startLogStream(); // 启动日志流

            // 自动刷新统计和队列
            setInterval(() => {
                loadSummary();
                loadQueue();
                loadSystemDetails(); // 刷新系统详情
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
