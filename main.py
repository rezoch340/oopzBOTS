import requests
import websocket
import json
import time
import threading
import traceback

import bilibili
from config import OOPZ_CONFIG, DEFAULT_HEADERS, AudioService
import oopz_sender
import netease
import qqmusic
from database import init_database, ImageCache, SongCache, Statistics
from queue_manager import QueueManager
from logger_config import setup_logger

# 初始化日志
logger = setup_logger("OopzBot")

# 初始化数据库
init_database()

# 初始化队列管理器
queue_manager = QueueManager()

sender = oopz_sender.SimpleOopzSender()
# --- 配置区域 ---
PERSON_ID = OOPZ_CONFIG["person_uid"]
DEVICE_ID = OOPZ_CONFIG["device_id"]
AUDIOSERVICE = AudioService["base_url"]
# 这是一个 JWT (JSON Web Token)，它有严格的过期时间。必须使用最新的。
SIGNATURE_JWT = OOPZ_CONFIG["jwt_token"]
# --- 配置区域结束 ---
neteaseAPI = netease.NeteaseCloud()
bilibiliAPI = bilibili.Bilibili()
OOPZ_URL = "wss://ws.oopz.cn"
qqmusicAPI = qqmusic.QQmusic()
HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/140.0.0.0 Safari/537.36",
    "Origin": "https://web.oopz.cn",
    "Cache-Control": "no-cache",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Accept-Encoding": "gzip, deflate, br, zstd"
}


def send_heartbeat(ws):
    """定时主动发心跳"""
    while True:
        time.sleep(10)  # 建议 20~30 秒
        if ws.sock and ws.sock.connected:
            heartbeat_body = {"person": PERSON_ID}
            heartbeat_payload = {
                "time": str(int(time.time() * 1000)),
                "body": json.dumps(heartbeat_body),
                "event": 254
            }
            ws.send(json.dumps(heartbeat_payload))
        else:
            break


def on_message(ws, message):
    """处理服务器消息"""
    try:
        data = json.loads(message)
        event = data.get("event")

        # 1. 忽略心跳返回
        if event == 254:
            body = json.loads(data["body"])
            if body.get("r") == 1:
                # 收到 ping → 回 pong
                heartbeat_payload = {
                    "time": str(int(time.time() * 1000)),
                    "body": json.dumps({"person": PERSON_ID}),
                    "event": 254
                }
                ws.send(json.dumps(heartbeat_payload))
            return

        # 2. 收到 serverId (event=1) → 模拟浏览器，直接发心跳
        if event == 1:
            heartbeat_payload = {
                "time": str(int(time.time() * 1000)),
                "body": json.dumps({"person": PERSON_ID}),
                "event": 254
            }
            ws.send(json.dumps(heartbeat_payload))
            logger.info("收到 serverId，已发首个心跳")
            return

        # 3. 聊天消息 (event=9)
        if event == 9:
            try:
                body = json.loads(data["body"])
                msg_data = json.loads(body["data"])
                if msg_data.get("person") == PERSON_ID:
                    return
                logger.info(f"💬 [聊天消息] 频道: {msg_data.get('channel')} | 用户: {msg_data.get('person')} | 内容: {msg_data.get('content')}")
                handle_command(msg_data, sender)
                return
            except Exception as e:
                logger.error(f"解析聊天消息失败: {e}")
                return

        # 4. 其他事件
        logger.debug(f"收到事件: {json.dumps(data, ensure_ascii=False)}")

    except Exception as e:
        logger.error(f"消息解析错误: {e} | 原始: {message}")


def on_error(ws, error):
    logger.error(f"WebSocket 错误: {error}")


def on_close(ws, close_status_code, close_msg):
    logger.warning(f"连接关闭 (code={close_status_code}, reason={close_msg})")


def on_open(ws):
    logger.info("WebSocket 连接已建立")

    # 登录包 (253)
    auth_body = {
        "person": PERSON_ID,
        "deviceId": DEVICE_ID,
        "signature": SIGNATURE_JWT,
        "deviceName": DEVICE_ID,
        "platformName": "web",
        "reconnect": 0
    }
    auth_payload = {
        "time": str(int(time.time() * 1000)),
        "body": json.dumps(auth_body),
        "event": 253
    }
    ws.send(json.dumps(auth_payload))
    logger.info("已发送认证信息")

    # 开启主动心跳线程
    threading.Thread(target=send_heartbeat, args=(ws,), daemon=True).start()


def get_player_status():
    """获取 AudioService 播放器状态（优先从 Redis 缓存读取）"""
    # 先尝试从 Redis 缓存读取
    cached_status = queue_manager.get_player_status()
    if cached_status:
        return cached_status
    
    # 缓存不存在或过期，从 AudioService 获取并更新到 Redis
    return queue_manager.update_player_status_from_service(AUDIOSERVICE)


def stopPlay():
    url = f'{AUDIOSERVICE}/stop'
    response = requests.get(url)


def handle_command(msg_data, sender):
    content = msg_data.get("content", "").strip()
    channel = msg_data.get("channel")
    user = msg_data.get("person")

    if not content.startswith("/"):
        return  # 不是命令

    parts = content.split(" ", 2)  # 最多切 3 部分: /qq play xxx
    command = parts[0]  # 比如 /play 或 /qq
    subcommand = parts[1] if len(parts) > 1 else None
    arg = parts[2] if len(parts) > 2 else None

    if command == "/test":
        response = testIMG(channel)
        return

    # /next - 播放下一首
    if command == "/next":
        next_song = queue_manager.play_next()
        if next_song:
            # 如果当前频道与歌曲频道不同，更新歌曲的频道为当前频道
            if next_song.get('channel') != channel:
                next_song['channel'] = channel
                queue_manager.set_current(next_song)  # 更新 Redis 中的当前歌曲
            
            # 根据平台决定播放参数
            model = 'qq' if next_song.get('platform') == 'qq' else None
            t = threading.Thread(target=play, args=(next_song['url'], model))
            t.start()
            
            # 构建完整的消息
            platform = next_song.get('platform')
            platform_name = {
                'netease': '网易云',
                'qq': 'QQ音乐',
                'bilibili': 'B站'
            }.get(platform, '未知')
            
            text = f"⏭️ 切换到下一首:\n来自于{platform_name}:\n"
            
            # B站特殊处理
            if platform == 'bilibili':
                text += f"🎵 标题: {next_song['name']}\n"
                text += f"📺 视频链接: https://www.bilibili.com/video/{next_song.get('song_id')}\n"
                text += f"🎧 音质: 标准"
            else:
                # 网易云和QQ音乐
                text += f"🎵 歌曲: {next_song['name']}\n"
                text += f"🎤 歌手: {next_song.get('artists', '未知')}\n"
                
                # 添加专辑信息（如果有）
                if next_song.get('album'):
                    text += f"💽 专辑: {next_song['album']}\n"
                
                # 添加时长（如果有）
                if next_song.get('duration'):
                    text += f"⏱ 时长: {next_song['duration']}"
            
            # 获取附件数据
            attachments = next_song.get('attachments', [])
            
            # 如果有封面，添加到文本最前面
            if attachments and len(attachments) > 0:
                att = attachments[0]
                text = f"![IMAGEw{att['width']}h{att['height']}]({att['fileKey']})\n" + text
            
            sender.send_message(text=text.rstrip(), attachments=attachments, channel=channel)
        else:
            sender.send_message("📭 队列为空，没有下一首了", channel=channel)
        return

    # /queue - 查看队列
    if command == "/queue":
        queue_list = queue_manager.get_queue(0, 10)
        if queue_list:
            msg = "📋 当前队列（前10首）:\n"
            for idx, song in enumerate(queue_list, 1):
                msg += f"{idx}. {song['name']} - {song.get('artists', '未知')}\n"
            msg += f"\n总计: {queue_manager.get_queue_length()} 首"
            sender.send_message(msg, channel=channel)
        else:
            sender.send_message("📭 队列为空", channel=channel)
        return

    # /stop (全局)
    if command == "/stop":
        t = threading.Thread(target=stopPlay)
        t.start()
        sender.send_message("⏹ 已停止播放", channel=channel)
        return

    # /play xxx (网易云)
    elif command == "/yun" and subcommand == "play":
        if arg:
            result = netPlay(arg, channel, user)
            if result['code'] == "success":
                message = result['message']
                attachments = result.get('attachments', [])
                sender.send_message(text=message, attachments=attachments, channel=channel)
            else:
                sender.send_message(f"❌ 错误: {result['message']}", channel=channel)
        else:
            sender.send_message("⚠️ 用法: /yun play 歌曲名", channel=channel)

    # /qq play xxx (QQ 音乐)
    elif command == "/qq" and subcommand == "play":
        if arg:
            result = qqPlay(arg, channel, user)
            if result['code'] == "success":
                message = result['message']
                attachments = result.get('attachments', [])
                sender.send_message(text=message, attachments=attachments, channel=channel)
            else:
                sender.send_message(f"❌ 错误: {result['message']}", channel=channel)
        else:
            sender.send_message("⚠️ 用法: /qq play 歌曲名", channel=channel)

    # /bili play xxx (Bilibili 音乐/视频)
    elif command == "/bili" and subcommand == "play":
        if arg:
            result = bilibiliMp3(arg, channel, user)
            if result["code"] == "success":
                sender.send_message(
                    result["message"],
                    channel=channel,
                    attachments=result.get("attachments", [])
                )
            else:
                sender.send_message(f"⚠️ {result['message']}", channel=channel)
        else:
            sender.send_message("⚠️ 用法: /bili play 视频链接或关键词", channel=channel)

    else:
        sender.send_message(f"❓ 未知命令: {content}", channel=channel)


def netEaseSearch(keyword):
    searchResult = neteaseAPI.summarize(keyword)
    if searchResult['code'] == "success":
        return {"code": "success", "message": searchResult['message'], "data": searchResult['data']}
    else:
        return {"code": "error", "message": searchResult['message'], "data": ''}


def netPlay(keyword, channel=None, user=None):
    searchResult = netEaseSearch(keyword)
    if searchResult['code'] != "success":
        return {"code": "error", "message": searchResult['message']}

    data = searchResult["data"]
    song_id = data.get('id', keyword)
    
    # 检查图片缓存
    cache_hit = False
    attachments = []
    image_cache_id = None
    
    if data.get('cover'):
        cached = ImageCache.get_by_source(song_id, 'netease')
        if cached:
            # 使用缓存
            attachments = [cached['attachment_data']]
            image_cache_id = cached['id']
            cache_hit = True
        else:
            # 上传新图片
            up = sender.upload_file_from_url(data['cover'])
            if up.get("code") == "success":
                att = up["data"]
                attachments = [att]
                # 保存到缓存
                image_cache_id = ImageCache.save(song_id, 'netease', data['cover'], att)
    
    # 保存歌曲缓存
    song_cache_id = SongCache.get_or_create(song_id, 'netease', data, image_cache_id)
    SongCache.add_play_history(song_cache_id, 'netease', channel, user)
    
    # 更新统计
    Statistics.update_today('netease', cache_hit)
    
    # 构建消息
    text = (
        "来自于网易云:\n"
        f"🎵 歌曲: {data['name']}\n"
        f"🎤 歌手: {data['artists']}\n"
        f"💽 专辑: {data['album']}\n"
        f"⏱ 时长: {data['durationText']}"
    )
    
    if attachments:
        att = attachments[0]
        text = f"![IMAGEw{att['width']}h{att['height']}]({att['fileKey']})\n" + text
        if cache_hit:
            text += "\n💾 (封面来自缓存)"
    
    # 添加到队列
    queue_position = queue_manager.add_to_queue({
        'platform': 'netease',
        'song_id': song_id,
        'name': data['name'],
        'artists': data['artists'],
        'album': data['album'],
        'url': data['url'],
        'cover': data.get('cover'),
        'duration': data['durationText'],
        'attachments': attachments,
        'channel': channel,
        'user': user
    })
    
    # 检查播放器实际状态
    player_status = get_player_status()
    is_playing = player_status.get('playing', False)
    current_song = queue_manager.get_current()
    
    # 只有在播放器空闲且队列为空时才立即播放
    if not is_playing and current_song is None and queue_position == 0:
        next_song = queue_manager.play_next()
        if next_song:
            t = threading.Thread(target=play, args=(next_song['url'],))
            t.start()
            text += "\n▶️ 立即播放"
    else:
        # 计算实际位置：当前播放的算第1位，队列从第2位开始
        actual_position = queue_position + 1 + (1 if current_song or is_playing else 0)
        text += f"\n📋 已加入队列 (位置: {actual_position})"
    
    return {"code": "success", "message": text, "attachments": attachments}


def qqSearch(keyword):
    searchResult = qqmusicAPI.summarize(keyword)  # 👈 调用你写的 QQ 音乐 API
    if searchResult['code'] == "success":
        return {
            "code": "success",
            "message": searchResult['message'],
            "data": searchResult['data']
        }
    else:
        return {
            "code": "error",
            "message": searchResult['message'],
            "data": ''
        }


def bilibiliMp3(keyword, channel=None, user=None):
    searchResult = bilibiliAPI.summarize(keyword)
    if searchResult['code'] != "success":
        return {"code": "error", "message": searchResult['message']}
    
    data = searchResult["data"]
    song_id = keyword  # 使用 BV 号作为 ID
    
    # 检查图片缓存
    cache_hit = False
    attachments = []
    image_cache_id = None
    
    if data.get('cover'):
        cached = ImageCache.get_by_source(song_id, 'bilibili')
        if cached:
            attachments = [cached['attachment_data']]
            image_cache_id = cached['id']
            cache_hit = True
        else:
            result = sender.upload_file_from_url(data['cover'])
            if result['code'] == "success":
                att = result['data']
                attachments = [att]
                image_cache_id = ImageCache.save(song_id, 'bilibili', data['cover'], att)
    
    # 保存歌曲缓存
    song_cache_id = SongCache.get_or_create(song_id, 'bilibili', data, image_cache_id)
    SongCache.add_play_history(song_cache_id, 'bilibili', channel, user)
    
    # 更新统计
    Statistics.update_today('bilibili', cache_hit)
    
    # 构造消息文本
    text = (
        "来自于B站:\n"
        f"🎵 标题: {data.get('name', '未知')}\n"
        f"📺 视频链接: https://www.bilibili.com/video/{keyword}\n"
        f"🎧 音质: 标准"
    )
    
    if attachments:
        att = attachments[0]
        text = f"![IMAGEw{att['width']}h{att['height']}]({att['fileKey']})\n" + text
        if cache_hit:
            text += "\n💾 (封面来自缓存)"
    
    # 添加到队列
    queue_position = queue_manager.add_to_queue({
        'platform': 'bilibili',
        'song_id': song_id,
        'name': data.get('name', '未知'),
        'artists': data.get('artists', 'B站'),
        'album': 'Bilibili',
        'url': data['url'],
        'cover': data.get('cover'),
        'duration': data.get('durationText', '未知'),
        'attachments': attachments,
        'channel': channel,
        'user': user
    })
    
    # 检查播放器实际状态
    player_status = get_player_status()
    is_playing = player_status.get('playing', False)
    current_song = queue_manager.get_current()
    
    # 只有在播放器空闲且队列为空时才立即播放
    if not is_playing and current_song is None and queue_position == 0:
        next_song = queue_manager.play_next()
        if next_song:
            t = threading.Thread(target=play, args=(next_song['url'],))
            t.start()
            text += "\n▶️ 立即播放"
    else:
        # 计算实际位置：当前播放的算第1位，队列从第2位开始
        actual_position = queue_position + 1 + (1 if current_song or is_playing else 0)
        text += f"\n📋 已加入队列 (位置: {actual_position})"
    
    return {"code": "success", "message": text, "attachments": attachments}


def qqPlay(keyword, channel=None, user=None):
    searchResult = qqSearch(keyword)
    if searchResult['code'] != "success":
        return {"code": "error", "message": searchResult['message']}
    
    data = searchResult["data"]
    song_id = data.get('id', keyword)
    
    # 检查图片缓存
    cache_hit = False
    attachments = []
    image_cache_id = None
    
    if data.get('cover'):
        cached = ImageCache.get_by_source(song_id, 'qq')
        if cached:
            attachments = [cached['attachment_data']]
            image_cache_id = cached['id']
            cache_hit = True
        else:
            result = sender.upload_file_from_url(data['cover'])
            if result['code'] == "success":
                att = result['data']
                attachments = [att]
                image_cache_id = ImageCache.save(song_id, 'qq', data['cover'], att)
    
    # 保存歌曲缓存
    song_cache_id = SongCache.get_or_create(song_id, 'qq', data, image_cache_id)
    SongCache.add_play_history(song_cache_id, 'qq', channel, user)
    
    # 更新统计
    Statistics.update_today('qq', cache_hit)
    
    # 构造消息文本
    text = (
        "来自于QQ音乐:\n"
        f"🎵 歌曲: {data['name']}\n"
        f"🎤 歌手: {data['artists']}\n"
        f"💽 专辑: {data['album']}\n"
        f"⏱ 时长: {data['durationText']}\n"
        f"🎧 音质: {data.get('song_quality', '标准')}"
    )
    
    if attachments:
        att = attachments[0]
        text = f"![IMAGEw{att['width']}h{att['height']}]({att['fileKey']})\n" + text
        if cache_hit:
            text += "\n💾 (封面来自缓存)"
    
    # 添加到队列
    queue_position = queue_manager.add_to_queue({
        'platform': 'qq',
        'song_id': song_id,
        'name': data['name'],
        'artists': data['artists'],
        'album': data['album'],
        'url': data['url'],
        'cover': data.get('cover'),
        'duration': data['durationText'],
        'attachments': attachments,
        'channel': channel,
        'user': user
    })
    
    # 检查播放器实际状态
    player_status = get_player_status()
    is_playing = player_status.get('playing', False)
    current_song = queue_manager.get_current()
    
    # 只有在播放器空闲且队列为空时才立即播放
    if not is_playing and current_song is None and queue_position == 0:
        next_song = queue_manager.play_next()
        if next_song:
            t = threading.Thread(target=play, args=(next_song['url'], 'qq'))
            t.start()
            text += "\n▶️ 立即播放"
    else:
        # 计算实际位置：当前播放的算第1位，队列从第2位开始
        actual_position = queue_position + 1 + (1 if current_song or is_playing else 0)
        text += f"\n📋 已加入队列 (位置: {actual_position})"
    
    return {"code": "success", "message": text, "attachments": attachments}


def play(url, model=None):
    """播放音乐"""
    params = {"url": url}
    if model:
        params["model"] = model

    resp = requests.get(f"{AUDIOSERVICE}/play", params=params)

    try:
        data = resp.json()
    except Exception:
        data = {"status": False, "code": resp.status_code, "message": resp.text}

    logger.debug(f"播放响应: {data}")
    return data


def send_now_playing_message(song_data, sender, prefix="🎵 正在播放"):
    """发送正在播放的消息通知
    
    Args:
        song_data: 歌曲数据
        sender: 消息发送器
        prefix: 消息前缀
    """
    channel = song_data.get('channel')
    if not channel:
        logger.warning("消息通知: 没有频道信息，跳过发送消息")
        return
    
    try:
        platform = song_data.get('platform')
        platform_name = {
            'netease': '网易云',
            'qq': 'QQ音乐',
            'bilibili': 'B站'
        }.get(platform, '未知')
        
        text = f"{prefix}:\n来自于{platform_name}:\n"
        
        # B站特殊处理
        if platform == 'bilibili':
            text += f"🎵 标题: {song_data['name']}\n"
            text += f"📺 视频链接: https://www.bilibili.com/video/{song_data.get('song_id')}\n"
            text += f"🎧 音质: 标准"
        else:
            # 网易云和QQ音乐
            text += f"🎵 歌曲: {song_data['name']}\n"
            text += f"🎤 歌手: {song_data.get('artists', '未知')}\n"
            
            # 添加专辑信息（如果有）
            if song_data.get('album'):
                text += f"💽 专辑: {song_data['album']}\n"
            
            # 添加时长（如果有）
            if song_data.get('duration'):
                text += f"⏱ 时长: {song_data['duration']}"
        
        # 获取附件数据
        attachments = song_data.get('attachments', [])
        
        # 如果有封面，添加到文本最前面
        if attachments and len(attachments) > 0:
            att = attachments[0]
            text = f"![IMAGEw{att['width']}h{att['height']}]({att['fileKey']})\n" + text
        
        sender.send_message(text=text.rstrip(), attachments=attachments, channel=channel)
        logger.info(f"消息通知: 已发送播放通知到频道 {channel}")
    except Exception as e:
        logger.error(f"消息通知: 发送消息失败 - {e}")


def auto_play_next_monitor():
    """监控播放状态，自动播放下一首"""
    last_play_time = 0  # 记录上次播放时间，避免重复触发
    
    while True:
        try:
            # 强制从 AudioService 获取最新状态，避免缓存问题
            status = queue_manager.update_player_status_from_service(AUDIOSERVICE)
            current_time = time.time()
            
            # 如果没有在播放，检查队列是否有歌曲
            if not status.get("playing", False):
                current = queue_manager.get_current()
                queue_length = queue_manager.get_queue_length()
                
                # 检查是否刚刚播放过（10秒内），避免重复触发
                if current_time - last_play_time < 10:
                    time.sleep(3)
                    continue
                
                # 如果有当前歌曲但没在播放，说明播放完成了
                if current:
                    # logger.info(f"自动播放: 检测到播放完成 - {current.get('name')}")
                    
                    # 检查队列是否有下一首
                    if queue_length > 0:
                        # 播放下一首
                        next_song = queue_manager.play_next()
                        if next_song:
                            logger.info(f"自动播放: 开始播放 - {next_song.get('name')}")
                            model = 'qq' if next_song.get('platform') == 'qq' else None
                            play(next_song['url'], model)
                            last_play_time = current_time
                            
                            # 发送播放通知
                            send_now_playing_message(next_song, sender, prefix="🎵 自动播放")
                            
                            # 播放后等待5秒，让播放器完全启动
                            time.sleep(5)
                        else:
                            logger.warning("自动播放: 获取下一首失败")
                    # else:
                    #     # 队列为空，保留当前歌曲信息（不清空）
                    #     logger.info(f"自动播放: 队列已空，保持当前歌曲显示 - {current.get('name')}")
                # 如果没有当前歌曲但队列有歌，自动播放
                elif queue_length > 0:
                    logger.info(f"自动播放: 检测到队列有 {queue_length} 首歌，但没有当前播放，开始播放")
                    next_song = queue_manager.play_next()
                    if next_song:
                        print(f"[自动播放] 开始播放: {next_song.get('name')}")
                        model = 'qq' if next_song.get('platform') == 'qq' else None
                        play(next_song['url'], model)
                        last_play_time = current_time
                        
                        # 发送播放通知
                        send_now_playing_message(next_song, sender, prefix="🎵 自动播放")
                        
                        # 播放后等待5秒，让播放器完全启动
                        time.sleep(5)
            
            # 每 5 秒检查一次（增加间隔，减少频繁检查）
            time.sleep(5)
            
        except Exception as e:
            logger.error(f"自动播放: 监控出错 - {e}")
            logger.error(traceback.format_exc())
            time.sleep(5)


def testIMG(channel):
    text = "![IMAGEw375h162](/im/20250927/32bce37716d14833af8f389ba9b21cb4.webp)\n禁止狗叫"
    attachments = [
        {
            "fileKey": "/im/20250927/32bce37716d14833af8f389ba9b21cb4.webp",
            "url": "https://imimagecdn.oopz.cn/im/20250927/32bce37716d14833af8f389ba9b21cb4.webp?sign=1758913436-lDuoV8-0-5f0ff68605a5210bcb74e0ccc28177a8",
            "width": 375,
            "height": 162,
            "fileSize": 517,
            "hash": "e3e72b7e25f112c696e52529b91d8250",
            "animated": False,
            "displayName": "",
            "attachmentType": "IMAGE",
        }
    ]
    return sender.send_message(text=text, attachments=attachments, channel=channel)


if __name__ == "__main__":
    # 启动自动播放监控线程
    threading.Thread(target=auto_play_next_monitor, daemon=True).start()
    logger.info("✅ 自动播放监控已启动")
    
    # netPlay("不说")
    websocket.enableTrace(False)  # 关闭底层帧日志
    ws_app = websocket.WebSocketApp(
        OOPZ_URL,
        header=HTTP_HEADERS,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close
    )
    ws_app.run_forever()
