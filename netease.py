import requests
from config import NETEASE_CLOUD


class NeteaseCloud:
    def __init__(self):
        self.config = NETEASE_CLOUD
        print("✅ 网易云音乐API已初始化")

    def search(self, keyword: str, limit: int = 10):
        """搜索音乐"""
        url = f"{self.config['base_url']}/search"
        params = {
            "keywords": keyword,
            "limit": limit,
            "cookie": self.config['cookie']
        }
        response = requests.get(url, params=params)
        if response.status_code != 200:
            print(f"❌ 搜索失败: {response.status_code}")
            return {'code': "error", 'message': "❌ 搜索失败", 'data': ''}
        if len(response.json()['result']['songs']) == 0:
            print(f"❌ 未找到相关歌曲")
            return {'code': "error", 'message': "❌ 未找到相关歌曲", 'data': ''}

        data = {
            "id": response.json()['result']['songs'][0]['id'],
        }

        return {'code': "success", 'message': "✅ 搜索成功", 'data': data}

    def song(self, music_id: str):
        url = f"{self.config['base_url']}/song/url"
        params = {
            "id": music_id,
            "cookie": self.config['cookie']
        }
        response = requests.get(url, params=params)
        if response.status_code != 200:
            print(f"❌ API访问失败: {response.status_code}")
            return {'code': "error", 'message': "❌ API访问失败", 'data': ''}
        if len(response.json()['data']) == 0:
            print(f"❌ 无法获取到信息")
            return {'code': "error", 'message': "❌ 无法获取到信息", 'data': ''}

        time_ms = response.json()["data"][0]["time"]
        seconds = time_ms // 1000
        minutes = seconds // 60
        secs = seconds % 60
        durationText = f"{minutes} 分 {secs} 秒"
        data = {
            'url': response.json()['data'][0],
            'durationText': durationText,
        }
        return {'code': "success", 'message': "✅ 获取成功", 'data': data}

    def detail(self, music_id: str):
        url = f"{self.config['base_url']}/song/detail"
        params = {
            "ids": music_id,
            "cookie": self.config['cookie']
        }
        response = requests.get(url, params=params)
        if response.status_code != 200:
            print(f"❌ API访问失败: {response.status_code}")
            return {'code': "error", 'message': "❌ API访问失败", 'data': ''}
        if len(response.json()['songs']) == 0:
            print(f"❌ 无法获取到信息")
            return {'code': "error", 'message': "❌ 无法获取到信息", 'data': ''}

        song_info = response.json()['songs'][0]
        data = {
            'name': song_info['name'],
            'artists': ', '.join(artist['name'] for artist in song_info['ar']),
            'album': song_info['al']['name'],
            'cover': song_info['al']['picUrl'],
        }
        return {'code': "success", 'message': "✅ 获取成功", 'data': data}

    def summarize(self, keyword: str):
        search_result = self.search(keyword)
        if search_result['code'] != 'success':
            return search_result

        music_id = search_result['data']['id']
        detail_result = self.detail(music_id)
        if detail_result['code'] != 'success':
            return detail_result

        song_result = self.song(music_id)
        if song_result['code'] != 'success':
            return song_result

        summary = {
            'name': detail_result['data']['name'],
            'artists': detail_result['data']['artists'],
            'album': detail_result['data']['album'],
            'cover': detail_result['data']['cover'],
            'url': song_result['data']['url']['url'],
            'durationText': song_result['data']['durationText'],
        }
        return {'code': "success", 'message': "✅ 获取成功", 'data': summary}


def demo():
    client = NeteaseCloud()
    result = client.summarize("兰亭序")
    print(result)


if __name__ == '__main__':
    demo()
