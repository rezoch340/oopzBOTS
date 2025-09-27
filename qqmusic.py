import requests
from config import QQ_MUSIC


def format_duration(interval: int) -> str:
    minutes = interval // 60
    seconds = interval % 60
    return f"{minutes} 分 {seconds} 秒"


def detect_quality(song: dict) -> dict:
    if song.get("size320", 0) > 0:
        return {"type": "320", "desc": "mp3 320k"}
    elif song.get("size128", 0) > 0:
        return {"type": "128", "desc": "mp3 128k"}
    elif song.get("sizem4a", 0) > 0:
        return {"type": "m4a", "desc": "m4a格式 128k"}
    elif song.get("sizeflac", 0) > 0:
        return {"type": "flac", "desc": "flac格式 无损"}
    elif song.get("sizeape", 0) > 0:
        return {"type": "ape", "desc": "ape格式 无损"}
    else:
        return {"type": "unknown", "desc": "未知"}



class QQmusic:
    def __init__(self):
        self.config = QQ_MUSIC
        print("✅ QQ音乐 API已初始化")

    def search(self, keyword: str, limit: int = 10):
        """搜索音乐"""
        url = f"{self.config['base_url']}/search"
        params = {
            "key": keyword,
            'pageNo': 1,
            'pageSize': limit,
        }
        response = requests.get(url, params=params)
        if response.status_code != 200:
            print(f"❌ API失败: {response.status_code}")
            return {'code': "error", 'message': "❌ API失败", 'data': ''}
        if response.json()['result'] != 100:
            print("搜索失败")
            return {'code': "error", 'message': "❌ 搜索失败", 'data': ''}
        if len(response.json()['data']['list']) == 0:
            print(f"❌ 未找到相关歌曲")
            return {'code': "error", 'message': "❌ 未找到相关歌曲", 'data': ''}

        topElement = response.json()['data']['list'][0]
        artists = topElement['singer'][0]['name']
        album = topElement['albumname']
        albummid = topElement['albummid']
        name = topElement['songname']
        songmid = topElement['songmid']
        strMediaMid = topElement['strMediaMid']
        durationText = format_duration(topElement['interval'])
        song_quality = detect_quality(topElement)
        front_cover = f"https://y.gtimg.cn/music/photo_new/T002R300x300M000{albummid}.jpg?max_age=2592000"
        data = {
            'artists': artists,
            'album': album,
            'name': name,
            'songmid': songmid,
            'strMediaMid': strMediaMid,
            'durationText': durationText,
            'song_quality': song_quality['type'],
            'cover': front_cover,
        }

        return {'code': "success", 'message': "✅ 搜索成功", 'data': data}

    def song(self, songmid: str, strMediaMid: str, quality: str):
        url = f"{self.config['base_url']}/song/url"
        params = {
            "id": songmid,
            "mediaId": strMediaMid,
            "type": quality
        }
        response = requests.get(url, params=params)
        if response.status_code != 200:
            print(f"❌ API访问失败: {response.status_code}")
            return {'code': "error", 'message': "❌ API访问失败", 'data': ''}
        if response.json()['result'] != 100:
            print("获取失败")
            return {'code': "error", 'message': "❌ 获取失败", 'data': ''}

        data = {
            'url': response.json()['data'],
        }
        return {'code': "success", 'message': "✅ 获取成功", 'data': data}

    def summarize(self, keyword: str):
        searchResult = self.search(keyword)
        if searchResult['code'] == "success":
            data = searchResult["data"]
            songResult = self.song(data['songmid'], data['strMediaMid'], data['song_quality'])
            if songResult['code'] == "success":
                data['url'] = songResult['data']['url']
                return {'code': "success", 'message': "✅ 获取成功", 'data': data}
            else:
                return {'code': "error", 'message': songResult['message'], 'data': ''}
        else:
            return {'code': "error", 'message': searchResult['message'], 'data': ''}


def demo():
    QQmusicAPI = QQmusic()
    result = QQmusicAPI.summarize("兰亭序")

    print(result)


if __name__ == '__main__':
    demo()
