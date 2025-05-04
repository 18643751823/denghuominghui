from typing import Any, Dict, List, Optional
from datetime import datetime
import time
from .models import DatabaseManager, EventRecord, AggregatedStats, TimerRecord
import threading

class EventService:
    """事件记录服务"""
    
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager
        # 添加缓存
        self._counts_cache = {}  # 格式: {timestamp: {'keyboard': count, 'mouse': count}}
        self._cache_lifetime = 1  # 将缓存有效期从5秒降低到1秒
        self._cache_timestamps = {}  # 记录缓存创建时间
        self._last_aggregate_time = 0  # 上次聚合时间
        
    def record_event(self, event_type: str, timestamp: int) -> None:
        """记录键盘或鼠标事件"""
        self.db.record_event_signal.emit(event_type, timestamp)
        # 清除可能失效的缓存
        self._clear_outdated_cache()
        
    def get_counts_since(self, timestamp: int) -> Dict[str, int]:
        """获取指定时间戳之后的键盘和鼠标点击次数，带缓存"""
        current_time = time.time()
        
        # 对于很短时间窗口的请求优先使用内存缓存
        very_recent = current_time - timestamp < 2  # 2秒内的数据请求
        
        # 检查缓存是否存在且未过期
        if timestamp in self._counts_cache:
            cache_time = self._cache_timestamps.get(timestamp, 0)
            if current_time - cache_time < (0.2 if very_recent else self._cache_lifetime):
                return self._counts_cache[timestamp]
        
        # 对于特别近的时间，使用优化的查询
        if very_recent:
            cursor = self.db.conn.cursor()
            cursor.execute("""
                SELECT event_type, COUNT(*) as count
                FROM raw_events
                WHERE timestamp >= ?
                GROUP BY event_type
            """, (timestamp,))
            
            result = {'keyboard': 0, 'mouse': 0}
            for row in cursor.fetchall():
                if row[0] == 'keyboard':
                    result['keyboard'] = row[1]
                elif row[0] == 'mouse':
                    result['mouse'] = row[1]
        else:
            # 原始查询方式
            cursor = self.db.conn.cursor()
            cursor.execute("""
                SELECT
                    SUM(CASE WHEN event_type = 'keyboard' THEN 1 ELSE 0 END) as keyboard,
                    SUM(CASE WHEN event_type = 'mouse' THEN 1 ELSE 0 END) as mouse
                FROM raw_events
                WHERE timestamp >= ?
            """, (timestamp,))
            row = cursor.fetchone()
            
            # 提前准备好结果，避免None值导致的问题
            result = {
                'keyboard': row[0] or 0,
                'mouse': row[1] or 0
            }
        
        # 更新缓存
        self._counts_cache[timestamp] = result
        self._cache_timestamps[timestamp] = current_time
        
        # 清理缓存，避免内存泄漏
        if len(self._counts_cache) > 20:  # 最多保留20个时间段的缓存
            self._clear_outdated_cache(force=True)
            
        return result
        
    def _clear_outdated_cache(self, force=False):
        """清理过期的缓存"""
        current_time = time.time()
        outdated_keys = []
        
        for timestamp, cache_time in self._cache_timestamps.items():
            if force or current_time - cache_time >= self._cache_lifetime:
                outdated_keys.append(timestamp)
                
        for key in outdated_keys:
            if key in self._counts_cache:
                del self._counts_cache[key]
            if key in self._cache_timestamps:
                del self._cache_timestamps[key]
        
    def get_total_counts(self) -> Dict[str, int]:
        """获取键盘和鼠标的总点击次数（所有历史数据）"""
        cursor = self.db.conn.cursor()
        cursor.execute("""
            SELECT
                SUM(CASE WHEN event_type = 'keyboard' THEN 1 ELSE 0 END) as keyboard,
                SUM(CASE WHEN event_type = 'mouse' THEN 1 ELSE 0 END) as mouse
            FROM raw_events
        """)
        row = cursor.fetchone()
        return {
            'keyboard': row[0] or 0 if row else 0,
            'mouse': row[1] or 0 if row else 0
        }
        
        cursor.execute(
            "SELECT COUNT(*) FROM raw_events WHERE event_type = 'keyboard'"
        )
        keyboard = cursor.fetchone()[0]
        
        cursor.execute(
            "SELECT COUNT(*) FROM raw_events WHERE event_type = 'mouse'"
        )
        mouse = cursor.fetchone()[0]
        
        return {'keyboard': keyboard, 'mouse': mouse}
        
    def get_aggregated_data(self, time_range: str = 'day', limit: int = 30) -> List[AggregatedStats]:
        """
        获取聚合数据
        :param time_range: 时间粒度 ('15min', '30min', 'day', 'week', 'month')
        :param limit: 返回的数据点数量
        :return: 包含时间戳和计数的字典列表
        """
        try:
            cursor = self.db.conn.cursor()
            
            # 获取当前日期，用于调试
            today = datetime.now().strftime("%Y-%m-%d")
            print(f"查询聚合数据: 时间范围={time_range}, 今日={today}")
            
            if time_range == '15min':
                cursor.execute("""
                    SELECT time_period, keyboard_count, mouse_count, score
                    FROM aggregated_stats
                    WHERE time_period LIKE '%-%-% %:%' 
                    AND (time_period LIKE '%:00' OR time_period LIKE '%:15' OR time_period LIKE '%:30' OR time_period LIKE '%:45')
                    ORDER BY time_period DESC
                    LIMIT ?
                """, (limit,))
            elif time_range == '30min':
                cursor.execute("""
                    SELECT time_period, keyboard_count, mouse_count, score
                    FROM aggregated_stats
                    WHERE time_period LIKE '%-%-% %:%' AND (time_period LIKE '%:00' OR time_period LIKE '%:30')
                    ORDER BY time_period DESC
                    LIMIT ?
                """, (limit,))
            elif time_range == 'day':
                cursor.execute("""
                    SELECT time_period, keyboard_count, mouse_count, score
                    FROM aggregated_stats
                    WHERE time_period LIKE '%-%-%' AND LENGTH(time_period) = 10
                    ORDER BY time_period DESC
                    LIMIT ?
                """, (limit,))
            elif time_range == 'week':
                cursor.execute("""
                    SELECT time_period, keyboard_count, mouse_count, score
                    FROM aggregated_stats
                    WHERE time_period LIKE '%-W%'
                    ORDER BY time_period DESC
                    LIMIT ?
                """, (limit,))
            elif time_range == 'month':
                cursor.execute("""
                    SELECT time_period, keyboard_count, mouse_count, score
                    FROM aggregated_stats
                    WHERE time_period LIKE '%-%'
                    AND LENGTH(time_period) = 7
                    ORDER BY time_period DESC
                    LIMIT ?
                """, (limit,))
            
            results = cursor.fetchall()
            print(f"查询到 {len(results)} 条记录")
            
            return [{
                'period': row[0],
                'keyboard': row[1],
                'mouse': row[2],
                'score': row[3]
            } for row in results]
            
        except Exception as e:
            print(f"获取聚合数据时出错: {e}")
            return []  # 发生错误时返回空列表
    
    def get_today_aggregated_data(self, time_range: str = '15min', limit: int = 96) -> List[AggregatedStats]:
        """
        获取今日聚合数据，确保只返回今天的数据
        :param time_range: 时间粒度 ('15min', '30min')
        :param limit: 返回的数据点数量
        :return: 包含时间戳和计数的字典列表
        """
        try:
            cursor = self.db.conn.cursor()
            today = datetime.now().strftime("%Y-%m-%d")
            
            print(f"查询今日({today})聚合数据: 时间范围={time_range}")
            
            if time_range == '15min':
                cursor.execute("""
                    SELECT time_period, keyboard_count, mouse_count, score
                    FROM aggregated_stats
                    WHERE time_period LIKE ? || ' %:%' 
                    AND (time_period LIKE '%:00' OR time_period LIKE '%:15' OR time_period LIKE '%:30' OR time_period LIKE '%:45')
                    ORDER BY time_period ASC
                    LIMIT ?
                """, (today, limit))
            elif time_range == '30min':
                cursor.execute("""
                    SELECT time_period, keyboard_count, mouse_count, score
                    FROM aggregated_stats
                    WHERE time_period LIKE ? || ' %:%' 
                    AND (time_period LIKE '%:00' OR time_period LIKE '%:30')
                    ORDER BY time_period ASC
                    LIMIT ?
                """, (today, limit))
            else:
                # 返回空列表，因为只支持分钟级别的今日数据
                print(f"不支持的时间范围: {time_range}")
                return []
                
            results = cursor.fetchall()
            print(f"查询到今日数据 {len(results)} 条记录")
            
            # 打印部分数据用于调试
            if results:
                print(f"示例数据: {results[0]}")
            
            return [{
                'period': row[0],
                'keyboard': row[1],
                'mouse': row[2],
                'score': row[3]
            } for row in results]
            
        except Exception as e:
            print(f"获取今日聚合数据时出错: {e}")
            return []  # 发生错误时返回空列表

    def calculate_aggregates(self) -> None:
        """计算并存储聚合统计数据"""
        # 检查是否需要执行聚合，避免频繁更新
        current_time = time.time()
        if current_time - self._last_aggregate_time < 60:  # 至少间隔1分钟
            return
            
        self._last_aggregate_time = current_time
            
        # 所有的聚合操作放入工作线程执行，避免阻塞主线程
        if hasattr(self.db, 'worker') and self.db.worker:
            self.db.worker.queue.put((self._do_calculate_aggregates, (), None))
        else:
            # 兼容旧版本，但会在主线程中执行可能导致阻塞
            try:
                self._do_calculate_aggregates()
            except Exception as e:
                print(f"执行聚合计算时出错: {e}")
    
    def _do_calculate_aggregates(self):
        """实际执行聚合计算的方法"""
        try:
            # 确保在正确的线程中使用数据库连接
            if hasattr(self.db, 'worker') and self.db.worker:
                try:
                    # 判断是否在工作线程中
                    is_worker_thread = threading.current_thread().ident == self.db.worker.thread_id()
                except:
                    # 如果获取thread_id失败，可能是因为QThread没有该方法
                    # 退回到使用主线程连接
                    is_worker_thread = False
                    
                if is_worker_thread:
                    # 在工作线程中，使用工作线程的连接
                    cursor = self.db.worker.conn.cursor()
                    conn = self.db.worker.conn
                else:
                    # 在主线程中，使用主线程的连接
                    cursor = self.db.conn.cursor()
                    conn = self.db.conn
            else:
                # 没有工作线程，使用主线程的连接
                cursor = self.db.conn.cursor()
                conn = self.db.conn
                
            # 确保清除可能的重复记录
            cursor.execute("DELETE FROM aggregated_stats WHERE time_period LIKE '%-%-% %:%'")
            
            # 15分钟聚合
            cursor.execute("""
            INSERT OR REPLACE INTO aggregated_stats (time_period, keyboard_count, mouse_count, score)
            SELECT
                strftime('%Y-%m-%d %H:', datetime(timestamp, 'unixepoch', 'localtime')) || 
                CASE 
                    WHEN cast(strftime('%M', datetime(timestamp, 'unixepoch', 'localtime')) as integer) < 15 THEN '00'
                    WHEN cast(strftime('%M', datetime(timestamp, 'unixepoch', 'localtime')) as integer) < 30 THEN '15'
                    WHEN cast(strftime('%M', datetime(timestamp, 'unixepoch', 'localtime')) as integer) < 45 THEN '30'
                    ELSE '45'
                END as period,
                SUM(CASE WHEN event_type = 'keyboard' THEN 1 ELSE 0 END) as keyboard,
                SUM(CASE WHEN event_type = 'mouse' THEN 1 ELSE 0 END) as mouse,
                SUM(CASE WHEN event_type = 'keyboard' THEN 1 ELSE 5 END) as score
            FROM raw_events
            WHERE timestamp >= strftime('%s', datetime('now', '-2 day'))
            GROUP BY period
            """)
            
            # 30分钟聚合
            cursor.execute("""
            INSERT OR REPLACE INTO aggregated_stats (time_period, keyboard_count, mouse_count, score)
            SELECT
                strftime('%Y-%m-%d %H:', datetime(timestamp, 'unixepoch', 'localtime')) || 
                CASE 
                    WHEN cast(strftime('%M', datetime(timestamp, 'unixepoch', 'localtime')) as integer) < 30 THEN '00'
                    ELSE '30'
                END as period,
                SUM(CASE WHEN event_type = 'keyboard' THEN 1 ELSE 0 END) as keyboard,
                SUM(CASE WHEN event_type = 'mouse' THEN 1 ELSE 0 END) as mouse,
                SUM(CASE WHEN event_type = 'keyboard' THEN 1 ELSE 5 END) as score
            FROM raw_events
            WHERE timestamp >= strftime('%s', datetime('now', '-7 day'))
            GROUP BY period
            """)
            
            # 日聚合
            cursor.execute("""
            INSERT OR REPLACE INTO aggregated_stats (time_period, keyboard_count, mouse_count, score)
            SELECT
                strftime('%Y-%m-%d', timestamp, 'unixepoch', 'localtime') as period,
                SUM(CASE WHEN event_type = 'keyboard' THEN 1 ELSE 0 END) as keyboard,
                SUM(CASE WHEN event_type = 'mouse' THEN 1 ELSE 0 END) as mouse,
                SUM(CASE WHEN event_type = 'keyboard' THEN 1 ELSE 5 END) as score
            FROM raw_events
            WHERE timestamp >= strftime('%s', datetime('now', '-30 day'))
            GROUP BY period
            """)
            
            # 周聚合(ISO周)
            cursor.execute("""
            INSERT OR REPLACE INTO aggregated_stats (time_period, keyboard_count, mouse_count, score)
            SELECT
                strftime('%Y-W%W', timestamp, 'unixepoch', 'localtime') as period,
                SUM(CASE WHEN event_type = 'keyboard' THEN 1 ELSE 0 END) as keyboard,
                SUM(CASE WHEN event_type = 'mouse' THEN 1 ELSE 0 END) as mouse,
                SUM(CASE WHEN event_type = 'keyboard' THEN 1 ELSE 5 END) as score
            FROM raw_events
            WHERE timestamp >= strftime('%s', datetime('now', '-365 day'))
            GROUP BY period
            """)
            
            # 月聚合
            cursor.execute("""
            INSERT OR REPLACE INTO aggregated_stats (time_period, keyboard_count, mouse_count, score)
            SELECT
                strftime('%Y-%m', timestamp, 'unixepoch', 'localtime') as period,
                SUM(CASE WHEN event_type = 'keyboard' THEN 1 ELSE 0 END) as keyboard,
                SUM(CASE WHEN event_type = 'mouse' THEN 1 ELSE 0 END) as mouse,
                SUM(CASE WHEN event_type = 'keyboard' THEN 1 ELSE 5 END) as score
            FROM raw_events
            WHERE timestamp >= strftime('%s', datetime('now', '-365 day'))
            GROUP BY period
            """)
            
            conn.commit()
            print("聚合计算完成")
        except Exception as e:
            print(f"聚合计算发生错误: {e}")

class TimerService:
    """计时器服务"""
    
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager
        
    def get_timers(self) -> List[Dict[str, Any]]:
        """获取所有计时器"""
        cursor = self.db.conn.cursor()
        cursor.execute("SELECT id, duration AS minutes, created_at FROM timers ORDER BY created_at DESC")
        return [
            {
                'id': row[0], 
                'minutes': row[1], 
                'created_at': datetime.fromtimestamp(row[2]).strftime("%Y-%m-%d %H:%M") if row[2] else "-"
            }
            for row in cursor.fetchall()
        ]
        
    def add_timer(self, minutes: int) -> int:
        """添加新计时器
        Args:
            minutes: 计时时长(分钟)
        """
        cursor = self.db.conn.cursor()
        cursor.execute(
            "INSERT INTO timers (duration) VALUES (?)",
            (minutes,)
        )
        self.db.conn.commit()
        return cursor.lastrowid
        
    def remove_timer(self, timer_id: int) -> None:
        """删除计时器"""
        cursor = self.db.conn.cursor()
        cursor.execute(
            "DELETE FROM timers WHERE id = ?",
            (timer_id,)
        )
        self.db.conn.commit()