import sqlite3
import time
import threading
from pathlib import Path
from PyQt6.QtCore import QObject, pyqtSignal, QThread, QTimer
from queue import Queue

class DatabaseWorker(QThread):
    """数据库工作线程，处理耗时的数据库操作"""
    
    def __init__(self, db_path):
        super().__init__()
        self.db_path = db_path
        self.queue = Queue()
        self.running = True
        self.conn = None
        self._thread_id = None
    
    def run(self):
        """线程主函数，处理数据库操作队列"""
        # 在线程中创建连接
        self.conn = sqlite3.connect(str(self.db_path))
        # 记录当前线程ID
        self._thread_id = threading.current_thread().ident
        
        while self.running:
            try:
                # 从队列获取任务，最多等待1秒
                task, args, callback = self.queue.get(timeout=1)
                
                # 执行任务
                try:
                    result = task(*args)
                    # 如果有回调函数，将结果传递给它
                    if callback:
                        callback(result)
                except Exception as e:
                    print(f"数据库操作错误: {e}")
                
                # 标记任务完成
                self.queue.task_done()
            except:
                # 队列为空或超时，继续循环
                pass
                
        # 关闭数据库连接
        if self.conn:
            self.conn.close()
    
    def thread_id(self):
        """获取工作线程的ID"""
        return self._thread_id
    
    def stop(self):
        """停止工作线程"""
        self.running = False
        self.wait()  # 等待线程结束

class DatabaseManager(QObject):
    record_event_signal = pyqtSignal(str, int)
    
    def __init__(self):
        super().__init__()
        self.db_path = Path(__file__).parent / "data" / "usage_stats.db"
        self.db_path.parent.mkdir(exist_ok=True)
        
        # 主线程连接 - 仅用于快速查询
        self.conn = sqlite3.connect(str(self.db_path))
        
        # 表初始化和设置
        self._init_tables()
        
        # 创建工作线程处理耗时操作
        self.worker = DatabaseWorker(self.db_path)
        self.worker.start()
        
        # 连接信号
        self.record_event_signal.connect(self._record_event)
        
        # 创建批量操作队列和定时提交机制
        self.batch_events = []
        self.batch_timer = QTimer()
        self.batch_timer.timeout.connect(self._flush_batch_events)
        self.batch_timer.start(500)  # 将刷新间隔从2000毫秒缩短到500毫秒
        
        # 线程锁保护批量队列
        self.batch_lock = threading.Lock()

    def _init_tables(self):
        """初始化数据库表结构"""
        cursor = self.conn.cursor()
        
        # 为事件表创建索引以提高查询性能
        create_tables_script = """
        CREATE TABLE IF NOT EXISTS raw_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp INTEGER NOT NULL,
            event_type TEXT NOT NULL CHECK(event_type IN ('keyboard', 'mouse')),
            details TEXT
        );
        
        CREATE INDEX IF NOT EXISTS idx_events_timestamp ON raw_events(timestamp);
        CREATE INDEX IF NOT EXISTS idx_events_type ON raw_events(event_type);
        CREATE INDEX IF NOT EXISTS idx_events_composite ON raw_events(event_type, timestamp);
        
        CREATE TABLE IF NOT EXISTS aggregated_stats (
            time_period TEXT PRIMARY KEY,
            keyboard_count INTEGER DEFAULT 0,
            mouse_count INTEGER DEFAULT 0,
            score INTEGER DEFAULT 0
        );
        
        CREATE TABLE IF NOT EXISTS timers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            duration INTEGER NOT NULL,  -- 分钟
            created_at INTEGER DEFAULT (strftime('%s', 'now'))
        );
        
        -- 启用WAL模式提高并发写入性能
        PRAGMA journal_mode = WAL;
        -- 优化SQLite性能
        PRAGMA synchronous = NORMAL;
        -- 启用内存缓存
        PRAGMA cache_size = 5000;
        """
        
        # 执行多条SQL语句
        cursor.executescript(create_tables_script)
        self.conn.commit()
        
        # 检查并清理超过30天的数据，防止数据库过大
        self._cleanup_old_data()

    def _cleanup_old_data(self):
        """清理超过30天的旧数据"""
        try:
            cursor = self.conn.cursor()
            thirty_days_ago = int(time.time()) - (30 * 24 * 60 * 60)
            cursor.execute(
                "DELETE FROM raw_events WHERE timestamp < ?",
                (thirty_days_ago,)
            )
            self.conn.commit()
            
            # 执行vacuum操作以回收空间
            cursor.execute("VACUUM")
            self.conn.commit()
        except Exception as e:
            print(f"清理旧数据时出错: {e}")

    def record_event(self, event_type, timestamp):
        """记录事件 - 使用批处理"""
        with self.batch_lock:
            self.batch_events.append((event_type, timestamp))
            
        # 如果批处理队列太大，立即刷新
        if len(self.batch_events) > 10:  # 将队列阈值从50降低到10
            self._flush_batch_events()
    
    def _flush_batch_events(self):
        """将批处理事件写入数据库"""
        with self.batch_lock:
            if not self.batch_events:
                return
                
            events = self.batch_events.copy()
            self.batch_events.clear()
        
        # 将批量插入任务添加到工作线程
        self.worker.queue.put((self._do_batch_insert, (events,), None))
    
    def _do_batch_insert(self, events):
        """执行批量插入操作"""
        cursor = self.worker.conn.cursor()
        cursor.executemany(
            "INSERT INTO raw_events (event_type, timestamp) VALUES (?, ?)",
            events
        )
        self.worker.conn.commit()
        
    def _record_event(self, event_type, timestamp):
        """记录单个事件 - 兼容性方法"""
        self.record_event(event_type, timestamp)

    def close(self):
        """关闭数据库连接"""
        # 刷新所有待处理的事件
        self._flush_batch_events()
        
        # 停止批处理定时器
        if self.batch_timer.isActive():
            self.batch_timer.stop()
        
        # 停止工作线程
        if hasattr(self, 'worker') and self.worker.isRunning():
            self.worker.stop()
        
        # 关闭主线程连接
        if hasattr(self, 'conn'):
            self.conn.close()
        
    # 计时器相关方法
    def add_timer(self, name, duration):
        """添加新计时器"""
        cursor = self.conn.cursor()
        cursor.execute(
            "INSERT INTO timers (name, duration, created_at) VALUES (?, ?, ?)",
            (name, duration, int(time.time()))
        )
        self.conn.commit()
        return cursor.lastrowid
        
    def get_timers(self):
        """获取所有计时器"""
        cursor = self.conn.cursor()
        cursor.execute("SELECT id, name, duration FROM timers ORDER BY created_at DESC")
        return [
            {'id': row[0], 'name': row[1], 'duration': row[2]}
            for row in cursor.fetchall()
        ]
        
    def delete_timer(self, timer_id):
        """删除计时器"""
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM timers WHERE id = ?", (timer_id,))
        self.conn.commit()

    def get_total_counts(self):
        """获取键盘和鼠标的总点击次数"""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM raw_events WHERE event_type = 'keyboard'"
        )
        keyboard = cursor.fetchone()[0]
        
        cursor.execute(
            "SELECT COUNT(*) FROM raw_events WHERE event_type = 'mouse'"
        )
        mouse = cursor.fetchone()[0]
        
        return {'keyboard': keyboard, 'mouse': mouse}
        
    def get_aggregated_data(self, time_range='day', limit=30):
        """
        获取聚合数据
        :param time_range: 时间粒度 ('30min', 'day', 'week', 'month')
        :param limit: 返回的数据点数量
        :return: 包含时间戳和计数的字典列表
        """
        cursor = self.conn.cursor()
        
        if time_range == '30min':
            cursor.execute("""
                SELECT time_period, keyboard_count, mouse_count, score
                FROM aggregated_stats
                WHERE time_period LIKE '%-%-% %:%'
                ORDER BY time_period DESC
                LIMIT ?
            """, (limit,))
        elif time_range == 'day':
            cursor.execute("""
                SELECT time_period, keyboard_count, mouse_count, score
                FROM aggregated_stats
                WHERE time_period LIKE '%-%-%'
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
            
        results = []
        for row in cursor.fetchall():
            results.append({
                'period': row[0],
                'keyboard': row[1],
                'mouse': row[2],
                'score': row[3]
            })
            
        return results

    def calculate_aggregates(self):
        """计算并存储聚合统计数据"""
        cursor = self.conn.cursor()
        
        # 30分钟聚合
        cursor.execute("""
        INSERT OR REPLACE INTO aggregated_stats (time_period, keyboard_count, mouse_count, score)
        SELECT
            strftime('%Y-%m-%d %H:%M', timestamp, 'unixepoch', 'localtime') as period,
            SUM(CASE WHEN event_type = 'keyboard' THEN 1 ELSE 0 END) as keyboard,
            SUM(CASE WHEN event_type = 'mouse' THEN 1 ELSE 0 END) as mouse,
            SUM(CASE WHEN event_type = 'keyboard' THEN 1 ELSE 5 END) as score
        FROM raw_events
        WHERE timestamp >= strftime('%s', datetime('now', '-1 day'))
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
        
        self.conn.commit()