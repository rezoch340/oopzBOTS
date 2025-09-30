#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库模型和管理
使用 SQLite 存储图片缓存和统计数据
"""

import sqlite3
import json
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict
import threading

# 数据库连接（线程安全）
_local = threading.local()

def get_china_time() -> str:
    """获取中国时区的当前时间字符串 (UTC+8)"""
    china_tz = timezone(timedelta(hours=8))
    return datetime.now(china_tz).strftime('%Y-%m-%d %H:%M:%S')


def get_db():
    """获取线程安全的数据库连接"""
    if not hasattr(_local, 'connection'):
        _local.connection = sqlite3.connect('oopz_cache.db', check_same_thread=False)
        _local.connection.row_factory = sqlite3.Row
    return _local.connection


def init_database():
    """初始化数据库表"""
    current_china_time = get_china_time()
    
    conn = get_db()
    cursor = conn.cursor()
    
    # 图片缓存表
    cursor.execute(f'''
        CREATE TABLE IF NOT EXISTS image_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id TEXT NOT NULL UNIQUE,
            source_type TEXT NOT NULL,
            source_url TEXT NOT NULL,
            file_key TEXT NOT NULL,
            oopz_url TEXT NOT NULL,
            width INTEGER,
            height INTEGER,
            file_size INTEGER,
            hash TEXT,
            attachment_data TEXT NOT NULL,
            created_at TEXT DEFAULT '{current_china_time}',
            last_used_at TEXT DEFAULT '{current_china_time}',
            use_count INTEGER DEFAULT 1
        )
    ''')
    
    # 歌曲缓存表（统计用）
    cursor.execute(f'''
        CREATE TABLE IF NOT EXISTS song_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            song_id TEXT NOT NULL,
            platform TEXT NOT NULL,
            song_name TEXT,
            artist TEXT,
            album TEXT,
            duration TEXT,
            cover_url TEXT,
            play_url TEXT,
            image_cache_id INTEGER,
            created_at TEXT DEFAULT '{current_china_time}',
            last_played_at TEXT DEFAULT '{current_china_time}',
            play_count INTEGER DEFAULT 1,
            UNIQUE(song_id, platform),
            FOREIGN KEY (image_cache_id) REFERENCES image_cache(id)
        )
    ''')
    
    # 播放历史表
    cursor.execute(f'''
        CREATE TABLE IF NOT EXISTS play_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            song_cache_id INTEGER NOT NULL,
            platform TEXT NOT NULL,
            channel_id TEXT,
            user_id TEXT,
            played_at TEXT DEFAULT '{current_china_time}',
            FOREIGN KEY (song_cache_id) REFERENCES song_cache(id)
        )
    ''')
    
    # 统计表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS statistics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL UNIQUE,
            total_plays INTEGER DEFAULT 0,
            netease_plays INTEGER DEFAULT 0,
            qq_plays INTEGER DEFAULT 0,
            bilibili_plays INTEGER DEFAULT 0,
            unique_songs INTEGER DEFAULT 0,
            cache_hits INTEGER DEFAULT 0,
            cache_misses INTEGER DEFAULT 0
        )
    ''')
    
    conn.commit()
    print("数据库初始化完成")


class ImageCache:
    """图片缓存管理器"""
    
    @staticmethod
    def get_by_source(source_id: str, source_type: str) -> Optional[Dict]:
        """根据源 ID 和类型获取缓存"""
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM image_cache 
            WHERE source_id = ? AND source_type = ?
        ''', (source_id, source_type))
        row = cursor.fetchone()
        
        if row:
            # 更新使用时间和次数
            cursor.execute('''
                UPDATE image_cache 
                SET last_used_at = CURRENT_TIMESTAMP, use_count = use_count + 1
                WHERE id = ?
            ''', (row['id'],))
            conn.commit()
            
            return {
                'id': row['id'],
                'attachment_data': json.loads(row['attachment_data']),
                'use_count': row['use_count'] + 1
            }
        return None
    
    @staticmethod
    def save(source_id: str, source_type: str, source_url: str, attachment_data: Dict) -> int:
        """保存图片缓存"""
        conn = get_db()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT INTO image_cache (
                    source_id, source_type, source_url, file_key, oopz_url,
                    width, height, file_size, hash, attachment_data
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                source_id,
                source_type,
                source_url,
                attachment_data.get('fileKey'),
                attachment_data.get('url'),
                attachment_data.get('width'),
                attachment_data.get('height'),
                attachment_data.get('fileSize'),
                attachment_data.get('hash'),
                json.dumps(attachment_data)
            ))
            conn.commit()
            return cursor.lastrowid
        except sqlite3.IntegrityError:
            # 已存在，返回现有 ID
            cursor.execute('''
                SELECT id FROM image_cache WHERE source_id = ? AND source_type = ?
            ''', (source_id, source_type))
            return cursor.fetchone()[0]
    
    @staticmethod
    def get_all(limit: int = 100, offset: int = 0) -> List[Dict]:
        """获取所有缓存图片"""
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM image_cache 
            ORDER BY last_used_at DESC 
            LIMIT ? OFFSET ?
        ''', (limit, offset))
        
        return [dict(row) for row in cursor.fetchall()]
    
    @staticmethod
    def get_stats() -> Dict:
        """获取缓存统计"""
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT 
                COUNT(*) as total,
                SUM(use_count) as total_uses,
                SUM(file_size) as total_size
            FROM image_cache
        ''')
        row = cursor.fetchone()
        return dict(row)


class SongCache:
    """歌曲缓存管理器"""
    
    @staticmethod
    def update_play_stats(song_id: str, platform: str, channel_id: str = None, user_id: str = None) -> bool:
        """更新歌曲播放统计（实际播放时调用）"""
        conn = get_db()
        cursor = conn.cursor()
        
        # 查找歌曲
        cursor.execute('''
            SELECT id FROM song_cache WHERE song_id = ? AND platform = ?
        ''', (song_id, platform))
        row = cursor.fetchone()
        
        if row:
            song_cache_id = row[0]
            current_time = get_china_time()
            
            # 更新播放时间和次数 - 使用中国时区时间戳
            cursor.execute('''
                UPDATE song_cache 
                SET last_played_at = ?, 
                    play_count = play_count + 1
                WHERE id = ?
            ''', (current_time, song_cache_id))
            
            # 添加播放历史
            cursor.execute('''
                INSERT INTO play_history (song_cache_id, platform, channel_id, user_id)
                VALUES (?, ?, ?, ?)
            ''', (song_cache_id, platform, channel_id, user_id))
            
            conn.commit()
            print(f"[SongCache] 更新播放统计: {song_id} ({platform}) - 播放次数 +1, 中国时间: {current_time}")
            return True
        else:
            print(f"[SongCache] 警告: 找不到歌曲统计记录: {song_id} ({platform})")
            return False
    
    @staticmethod
    def get_or_create(song_id: str, platform: str, song_data: Dict, image_cache_id: Optional[int] = None) -> int:
        """获取或创建歌曲缓存"""
        conn = get_db()
        cursor = conn.cursor()
        
        # 尝试获取现有记录
        cursor.execute('''
            SELECT id FROM song_cache WHERE song_id = ? AND platform = ?
        ''', (song_id, platform))
        row = cursor.fetchone()
        
        if row:
            # 更新播放时间和次数 - 使用中国时区
            current_time = get_china_time()
            
            cursor.execute('''
                UPDATE song_cache 
                SET last_played_at = ?, 
                    play_count = play_count + 1,
                    image_cache_id = COALESCE(?, image_cache_id)
                WHERE id = ?
            ''', (current_time, image_cache_id, row[0]))
            conn.commit()
            return row[0]
        else:
            # 创建新记录 - 使用中国时区时间
            current_time = get_china_time()
            
            cursor.execute('''
                INSERT INTO song_cache (
                    song_id, platform, song_name, artist, album, 
                    duration, cover_url, play_url, image_cache_id,
                    created_at, last_played_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                song_id,
                platform,
                song_data.get('name'),
                song_data.get('artists'),
                song_data.get('album'),
                song_data.get('durationText'),
                song_data.get('cover'),
                song_data.get('url'),
                image_cache_id,
                current_time,
                current_time
            ))
            conn.commit()
            return cursor.lastrowid
    
    @staticmethod
    def add_play_history(song_cache_id: int, platform: str, channel_id: str = None, user_id: str = None):
        """添加播放历史"""
        current_time = get_china_time()
        
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO play_history (song_cache_id, platform, channel_id, user_id, played_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (song_cache_id, platform, channel_id, user_id, current_time))
        conn.commit()
    
    @staticmethod
    def get_top_songs(platform: Optional[str] = None, limit: int = 20) -> List[Dict]:
        """获取热门歌曲"""
        conn = get_db()
        cursor = conn.cursor()
        
        if platform:
            cursor.execute('''
                SELECT * FROM song_cache 
                WHERE platform = ?
                ORDER BY play_count DESC, last_played_at DESC
                LIMIT ?
            ''', (platform, limit))
        else:
            cursor.execute('''
                SELECT * FROM song_cache 
                ORDER BY play_count DESC, last_played_at DESC
                LIMIT ?
            ''', (limit,))
        
        return [dict(row) for row in cursor.fetchall()]
    
    @staticmethod
    def get_recent_songs(limit: int = 20) -> List[Dict]:
        """获取最近播放的歌曲"""
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM song_cache 
            ORDER BY last_played_at DESC
            LIMIT ?
        ''', (limit,))
        
        return [dict(row) for row in cursor.fetchall()]


class Statistics:
    """统计管理器"""
    
    @staticmethod
    def update_today(platform: str, cache_hit: bool = False):
        """更新今日统计"""
        conn = get_db()
        cursor = conn.cursor()
        # 使用中国时区的日期
        china_tz = timezone(timedelta(hours=8))
        today = datetime.now(china_tz).strftime('%Y-%m-%d')
        
        # 获取或创建今日统计
        cursor.execute('''
            INSERT OR IGNORE INTO statistics (date) VALUES (?)
        ''', (today,))
        
        # 更新计数
        platform_field = f"{platform}_plays"
        cache_field = "cache_hits" if cache_hit else "cache_misses"
        
        cursor.execute(f'''
            UPDATE statistics 
            SET total_plays = total_plays + 1,
                {platform_field} = {platform_field} + 1,
                {cache_field} = {cache_field} + 1
            WHERE date = ?
        ''', (today,))
        
        conn.commit()
    
    @staticmethod
    def get_today() -> Dict:
        """获取今日统计"""
        conn = get_db()
        cursor = conn.cursor()
        # 使用中国时区的日期
        china_tz = timezone(timedelta(hours=8))
        today = datetime.now(china_tz).strftime('%Y-%m-%d')
        
        cursor.execute('SELECT * FROM statistics WHERE date = ?', (today,))
        row = cursor.fetchone()
        
        if row:
            return dict(row)
        return {
            'date': today,
            'total_plays': 0,
            'netease_plays': 0,
            'qq_plays': 0,
            'bilibili_plays': 0,
            'cache_hits': 0,
            'cache_misses': 0
        }
    
    @staticmethod
    def get_recent_days(days: int = 7) -> List[Dict]:
        """获取最近几天的统计"""
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM statistics 
            ORDER BY date DESC 
            LIMIT ?
        ''', (days,))
        
        return [dict(row) for row in cursor.fetchall()]


# 初始化数据库
if __name__ == "__main__":
    init_database()
    print("数据库初始化完成")
