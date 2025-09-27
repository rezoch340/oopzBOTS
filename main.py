import requests
import websocket
import json
import time
import threading

import bilibili
from config import OOPZ_CONFIG, DEFAULT_HEADERS, AudioService
import oopz_sender
import netease
import qqmusic

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
            print(">>> 收到 serverId，已发首个心跳 >>>")
            return

        # 3. 聊天消息 (event=9)
        if event == 9:
            try:
                body = json.loads(data["body"])
                msg_data = json.loads(body["data"])
                if msg_data.get("person") == PERSON_ID:
                    return
                print("💬 [聊天消息]")
                print(f"  频道: {msg_data.get('channel')}")
                print(f"  用户: {msg_data.get('person')}")
                print(f"  内容: {msg_data.get('content')}\n")
                handle_command(msg_data, sender)
                return
            except Exception as e:
                print("解析聊天消息失败:", e)
                return

        # 4. 其他事件
        print("<<< 收到事件 >>>")
        print(json.dumps(data, indent=2, ensure_ascii=False))

    except Exception as e:
        print("消息解析错误:", e, "| 原始:", message)


def on_error(ws, error):
    print(f"--- 出错: {error} ---")


def on_close(ws, close_status_code, close_msg):
    print(f"--- 连接关闭 (code={close_status_code}, reason={close_msg}) ---")


def on_open(ws):
    print("--- 连接已建立 ---")

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
    print(">>> 已发送认证 <<<")

    # 开启主动心跳线程
    threading.Thread(target=send_heartbeat, args=(ws,), daemon=True).start()


def stopPlay():
    url = f'{AUDIOSERVICE}/stop'
    response = requests.get(url)


def handle_command(msg_data, sender):
    content = msg_data.get("content", "").strip()
    channel = msg_data.get("channel")

    if not content.startswith("/"):
        return  # 不是命令

    parts = content.split(" ", 2)  # 最多切 3 部分: /qq play xxx
    command = parts[0]  # 比如 /play 或 /qq
    subcommand = parts[1] if len(parts) > 1 else None
    arg = parts[2] if len(parts) > 2 else None

    if command == "/sb":
        response = testIMG(channel)
        # 结束
        return

    # /stop (全局)
    if command == "/stop":
        t = threading.Thread(target=stopPlay)
        t.start()
        sender.send_message("⏹ 已停止播放", channel=channel)

    # /play xxx (网易云)
    elif command == "/yun" and subcommand == "play":
        if arg:
            result = netPlay(arg)
            if result['code'] == "success":
                message = result['message']
                attachments = result.get('attachments', [])
                sender.send_message(text=message, attachments=attachments, channel=channel)
            else:
                sender.send_message(f"❌ 错误: {result['message']}", channel=channel)

    # /qq play xxx (QQ 音乐)
    elif command == "/qq" and subcommand == "play":
        if arg:
            result = qqPlay(arg)
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
            result = bilibiliMp3(arg)
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


def netPlay(keyword):
    searchResult = netEaseSearch(keyword)
    if searchResult['code'] != "success":
        return {"code": "error", "message": searchResult['message']}

    data = searchResult["data"]
    t = threading.Thread(target=play, args=(data['url'],))
    t.start()

    # 基础文本
    text = (
        "来自于网易云:\n"
        f"🎵 歌曲: {data['name']}\n"
        f"🎤 歌手: {data['artists']}\n"
        f"💽 专辑: {data['album']}\n"
        f"⏱ 时长: {data['durationText']}"
    )

    attachments = []
    # 如果有封面 → 上传并在 text 最前面加图片占位
    if sender and data.get('cover'):
        up = sender.upload_file_from_url(data['cover'])
        if up.get("code") == "success":
            att = up["data"]
            attachments = [att]
            text = f"![IMAGEw{att['width']}h{att['height']}]({att['fileKey']})\n" + text

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


def bilibiliMp3(keyword):
    searchResult = bilibiliAPI.summarize(keyword)
    if searchResult['code'] == "success":
        data = searchResult["data"]

        # 启动播放线程
        t = threading.Thread(target=play, args=(data['url'],))
        t.start()

        # 构造消息文本
        text = (
            "来自于B站:\n"
            f"🎵 标题: {data.get('name', '未知')}\n"
            f"📺 视频链接: https://www.bilibili.com/video/{keyword}\n"
            f"🎧 音质: 标准"
        )

        # 上传封面图
        attachments = []
        if sender and data.get('cover'):
            result = sender.upload_file_from_url(data['cover'])
            if result['code'] == "success":
                att = result['data']
                attachments = [att]
                # ✅ 在文本最前面插入封面图占位
                text = f"![IMAGEw{att['width']}h{att['height']}]({att['fileKey']})\n" + text

        return {"code": "success", "message": text, "attachments": attachments}

    else:
        return {"code": "error", "message": searchResult['message']}


def qqPlay(keyword):
    searchResult = qqSearch(keyword)
    if searchResult['code'] == "success":
        data = searchResult["data"]
        t = threading.Thread(target=play, args=(data['url'], 'qq',))
        t.start()

        # 上传封面图

        # 构造消息文本
        text = (
            "来自于QQ音乐:\n"
            f"🎵 歌曲: {data['name']}\n"
            f"🎤 歌手: {data['artists']}\n"
            f"💽 专辑: {data['album']}\n"
            f"⏱ 时长: {data['durationText']}\n"
            f"🎧 音质: {data['song_quality']}"
        )

        attachments = []
        if sender and data.get('cover'):
            result = sender.upload_file_from_url(data['cover'])
            if result['code'] == "success":
                att = result['data']
                attachments = [att]
                # ✅ 在文本最前面插入封面图占位
                text = f"![IMAGEw{att['width']}h{att['height']}]({att['fileKey']})\n" + text

        return {"code": "success", "message": text, "attachments": attachments}
    else:
        return {"code": "error", "message": searchResult['message']}


def play(url, model=None):
    params = {"url": url}
    if model:
        params["model"] = model

    resp = requests.get(f"{AUDIOSERVICE}/play", params=params)

    try:
        data = resp.json()
    except Exception:
        data = {"status": False, "code": resp.status_code, "message": resp.text}

    print(data)
    return data


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
