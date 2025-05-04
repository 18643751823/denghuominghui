from typing import TypedDict, Optional
from datetime import datetime
from PyQt6.QtCore import QObject, pyqtSignal
import sqlite3
from pathlib import Path

class EventRecord(TypedDict):
    """事件记录数据模型"""
    timestamp: int
    event_type: str  # 'keyboard' or 'mouse'
    details: Optional[str]

class AggregatedStats(TypedDict):
    """聚合统计数据模型"""
    time_period: str
    keyboard_count: int
    mouse_count: int
    score: int

class TimerRecord(TypedDict):
    """计时器记录数据模型"""
    id: int
    name: str
    duration: int  # in minutes
    created_at: int  # timestamp

class DatabaseManager(QObject):
    """数据库管理类"""
    record_event_signal = pyqtSignal(str, int)
    
    def __init__(self):
        """初始化数据库连接"""
        super().__init__()
        db_path = Path(__file__).parent.parent / "data" / "usage_stats.db"
        db_path.parent.mkdir(exist_ok=True)
        
        self.conn = sqlite3.connect(str(db_path))
        self._init_tables()
        self.record_event_signal.connect(self._record_event)