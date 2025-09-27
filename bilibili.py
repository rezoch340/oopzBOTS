import requests
from config import BILIBILI





class Bilibili:
    def __init__(self):
        self.config = BILIBILI
        print("✅ BILIBILI API已初始化")


    def detail(self, keyword: str):
        url = f"{self.config['base_url']}/b2mp3/detail/{keyword}"
        response = requests.get(url)
        print(response.json())
        if response.status_code != 200:
            print(f"❌ API访问失败: {response.status_code}")
            return {'code': "error", 'message': "❌ API访问失败", 'data': ''}
        if response.json()['status'] != 'success':
            print(f"❌ 无法获取到信息: {response.json().get('message', '未知错误')}")
            return {'code': "error", 'message': f"❌ 无法获取到信息: {response.json().get('message', '未知错误')}", 'data': ''}
        data = response.json()['data']
        name = data.get('text', '未知标题')
        cover = data.get('preview_url', '')
        data = {
            'name': name,
            'cover': cover,
        }
        return {'code': "success", 'message': "✅ 获取成功", 'data': data}


    def summarize(self, keyword: str):

        url = f"{self.config['base_url']}/b2mp3/{keyword}"
        data = {
            'url': url
        }
        detail = self.detail(keyword)
        if detail['code'] != "success":
            return detail
        data['name'] = detail['data']['name']
        data['cover'] = detail['data']['cover']
        return {'code': "success", 'message': "✅ 获取成功", 'data': data}
