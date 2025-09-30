#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Redis 队列管理器
管理音乐播放队列、当前播放状态等
"""

import json
import time
from typing import Optional, List, Dict
from redis import Redis


class QueueManager:
    """音乐队列管理器"""
    
    def __init__(self, redis_config: dict = None):
        """初始化 Redis 连接"""
        if redis_config is None:
            from config import REDIS_CONFIG
            redis_config = REDIS_CONFIG
            
        self.redis = Redis(
            host=redis_config.get('host', 'localhost'),
            port=redis_config.get('port', 6379),
            password=redis_config.get('password'),
            db=redis_config.get('db', 0),
            decode_responses=redis_config.get('decode_responses', True)
        )
        self.queue_key = "music:queue"
        self.current_key = "music:current"
        self.history_key = "music:history"
        self.player_status_key = "music:player_status"  # 新增：播放器状态缓存
        self.default_channel_key = "music:default_channel"  # 新增：默认频道
        self.max_history = 50  # 保留最近 50 条历史
    
    def add_to_queue(self, song_data: Dict) -> int:
        """添加歌曲到队列
        
        Args:
            song_data: 歌曲数据字典，包含:
                - platform: 平台 (netease/qq/bilibili)
                - song_id: 歌曲 ID
                - name: 歌曲名
                - artists: 艺术家
                - album: 专辑
                - url: 播放链接
                - cover: 封面链接
                - duration: 时长
                - attachments: Oopz 附件数据
                - channel: 请求频道
                - user: 请求用户
        
        Returns:
            队列中的位置（从 0 开始）
        """
        # 如果有频道信息，缓存为默认频道（24小时过期）
        if song_data.get('channel'):
            self.redis.set(self.default_channel_key, song_data['channel'], ex=86400)
        
        # 将数据序列化为 JSON
        song_json = json.dumps(song_data, ensure_ascii=False)
        
        # 添加到队列末尾
        position = self.redis.rpush(self.queue_key, song_json)
        
        return position - 1  # 返回索引位置
    
    def get_current(self) -> Optional[Dict]:
        """获取当前播放的歌曲"""
        current_json = self.redis.get(self.current_key)
        if current_json:
            return json.loads(current_json)
        return None
    
    def set_current(self, song_data: Optional[Dict]):
        """设置当前播放的歌曲"""
        if song_data:
            # 如果有频道信息，缓存为默认频道（24小时过期）
            if song_data.get('channel'):
                self.redis.set(self.default_channel_key, song_data['channel'], ex=86400)
            
            self.redis.set(self.current_key, json.dumps(song_data, ensure_ascii=False))
            print(f"[QueueManager] 设置当前播放: {song_data.get('name')}, 频道: {song_data.get('channel')}")
        else:
            self.redis.delete(self.current_key)
            print(f"[QueueManager] 清空当前播放")
    
    def get_next(self) -> Optional[Dict]:
        """获取并移除队列中的下一首歌"""
        # 从队列左侧弹出
        song_json = self.redis.lpop(self.queue_key)
        if song_json:
            return json.loads(song_json)
        return None
    
    def peek_next(self) -> Optional[Dict]:
        """查看下一首歌（不移除）"""
        song_json = self.redis.lindex(self.queue_key, 0)
        if song_json:
            return json.loads(song_json)
        return None
    
    def get_queue(self, start: int = 0, end: int = -1) -> List[Dict]:
        """获取队列列表
        
        Args:
            start: 起始位置
            end: 结束位置，-1 表示到末尾
        
        Returns:
            歌曲列表
        """
        songs_json = self.redis.lrange(self.queue_key, start, end)
        return [json.loads(s) for s in songs_json]
    
    def get_queue_length(self) -> int:
        """获取队列长度"""
        return self.redis.llen(self.queue_key)
    
    def clear_queue(self):
        """清空队列"""
        self.redis.delete(self.queue_key)
    
    def remove_from_queue(self, index: int) -> bool:
        """从队列中移除指定位置的歌曲
        
        Args:
            index: 歌曲在队列中的索引
        
        Returns:
            是否成功移除
        """
        # Redis 没有直接按索引删除的命令，需要使用临时标记
        temp_marker = "__TO_DELETE__"
        
        # 设置临时标记
        result = self.redis.lset(self.queue_key, index, temp_marker)
        if not result:
            return False
        
        # 移除标记
        self.redis.lrem(self.queue_key, 1, temp_marker)
        return True
    
    def add_to_history(self, song_data: Dict):
        """添加到播放历史"""
        song_json = json.dumps(song_data, ensure_ascii=False)
        
        # 添加到历史列表头部
        self.redis.lpush(self.history_key, song_json)
        
        # 修剪历史列表，只保留最近的记录
        self.redis.ltrim(self.history_key, 0, self.max_history - 1)
    
    def get_history(self, limit: int = 20) -> List[Dict]:
        """获取播放历史
        
        Args:
            limit: 返回的历史记录数量
        
        Returns:
            历史记录列表
        """
        songs_json = self.redis.lrange(self.history_key, 0, limit - 1)
        return [json.loads(s) for s in songs_json]
    
    def get_status(self) -> Dict:
        """获取播放器状态"""
        return {
            "current": self.get_current(),
            "queue_length": self.get_queue_length(),
            "next": self.peek_next()
        }
    
    def play_next(self, clear_on_empty: bool = False) -> Optional[Dict]:
        """播放下一首
        
        将当前歌曲加入历史，从队列取出下一首设为当前
        
        Args:
            clear_on_empty: 如果队列为空时是否清空当前播放（默认 False，保留最后的歌曲信息）
        
        Returns:
            下一首歌的数据，如果队列为空则返回 None
        """
        # 保存当前歌曲到历史
        current = self.get_current()
        if current:
            self.add_to_history(current)
        
        # 获取下一首
        next_song = self.get_next()
        if next_song:
            self.set_current(next_song)
            return next_song
        else:
            # 队列为空
            if clear_on_empty:
                self.set_current(None)
                print("[QueueManager] 队列为空，已清空当前播放")
            else:
                print(f"[QueueManager] 队列为空，保留当前播放显示: {current.get('name') if current else 'None'}")
            return None
    
    def skip_current(self) -> Optional[Dict]:
        """跳过当前歌曲，播放下一首"""
        return self.play_next()
    
    def get_default_channel(self) -> Optional[str]:
        """获取默认频道"""
        return self.redis.get(self.default_channel_key)
    
    def set_player_status(self, status: Dict):
        """缓存播放器状态到 Redis
        
        Args:
            status: 播放器状态字典，包含 playing、currentFile、playbackState 等
        """
        self.redis.set(
            self.player_status_key,
            json.dumps(status, ensure_ascii=False),
            ex=10  # 10 秒过期，确保状态及时更新
        )
    
    def get_player_status(self) -> Optional[Dict]:
        """从 Redis 获取缓存的播放器状态
        
        Returns:
            播放器状态字典，如果缓存不存在返回 None
        """
        status_json = self.redis.get(self.player_status_key)
        if status_json:
            return json.loads(status_json)
        return None
    
    def update_player_status_from_service(self, audioservice_url: str) -> Dict:
        """从 AudioService 更新播放器状态到 Redis
        
        Args:
            audioservice_url: AudioService 的基础 URL
            
        Returns:
            更新后的状态字典
        """
        try:
            import requests
            response = requests.get(f"{audioservice_url}/status", timeout=2)
            if response.status_code == 200:
                status = response.json()
                # 缓存到 Redis
                self.set_player_status({
                    "playing": status.get("playing", False),
                    "currentFile": status.get("currentFile"),
                    "playbackState": status.get("playbackState", "Unknown"),
                    "timestamp": int(time.time())
                })
                return status
            return {"playing": False, "error": f"状态码: {response.status_code}"}
        except Exception as e:
            return {"playing": False, "error": str(e)}


class CacheManager:
    """缓存管理器（用于其他缓存需求）"""
    
    def __init__(self, redis_client: Redis):
        """使用已有的 Redis 连接"""
        self.redis = redis_client
    
    def set(self, key: str, value: str, ttl: int = 600):
        """设置缓存"""
        self.redis.set(key, value, ex=ttl)
    
    def get(self, key: str) -> Optional[str]:
        """获取缓存"""
        return self.redis.get(key)
    
    def delete(self, key: str):
        """删除缓存"""
        self.redis.delete(key)
    
    def exists(self, key: str) -> bool:
        """检查缓存是否存在"""
        return self.redis.exists(key) > 0


# 测试代码
if __name__ == "__main__":
    qm = QueueManager()
    
    # 测试添加歌曲
    test_song = {
        "platform": "netease",
        "song_id": "123456",
        "name": "测试歌曲",
        "artists": "测试歌手",
        "url": "http://example.com/song.mp3"
    }
    
    pos = qm.add_to_queue(test_song)
    print(f"添加歌曲到队列，位置: {pos}")
    
    # 查看队列
    queue = qm.get_queue()
    print(f"当前队列: {queue}")
    
    # 播放下一首
    next_song = qm.play_next()
    print(f"播放: {next_song}")
    
    # 查看状态
    status = qm.get_status()
    print(f"播放器状态: {status}")
