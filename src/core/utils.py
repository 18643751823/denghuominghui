from typing import Dict, Any, Optional, Tuple
from datetime import datetime
import time
import functools
from PyQt6.QtCore import QObject, pyqtSignal

class TimeUtils:
    """时间处理工具类"""
    
    # 添加时间格式化缓存，减少重复转换
    _format_cache = {}
    _cache_size_limit = 100
    
    @staticmethod
    def timestamp_to_str(timestamp: int, fmt: str = "%Y-%m-%d %H:%M") -> str:
        """将时间戳转换为格式化字符串
        使用缓存提高性能，减少重复转换
        """
        cache_key = (timestamp, fmt)
        if cache_key in TimeUtils._format_cache:
            return TimeUtils._format_cache[cache_key]
            
        # 缓存达到上限时清理
        if len(TimeUtils._format_cache) >= TimeUtils._cache_size_limit:
            TimeUtils._format_cache.clear()
            
        result = datetime.fromtimestamp(timestamp).strftime(fmt)
        TimeUtils._format_cache[cache_key] = result
        return result
        
    @staticmethod
    def get_current_timestamp() -> int:
        """获取当前时间戳"""
        return int(time.time())

class ScoreCalculator(QObject):
    """分数计算工具类"""
    
    score_updated = pyqtSignal(int)
    
    def __init__(self):
        super().__init__()
        self._keyboard_weight = 1
        self._mouse_weight = 5
        self._last_calculation = (0, 0, 0)  # (键盘计数, 鼠标计数, 分数)
        
    def calculate_score(self, counts: Dict[str, int]) -> int:
        """
        计算工作效率分数，包含缓存优化
        :param counts: 包含键盘和鼠标计数的字典
        :return: 计算后的分数
        """
        keyboard = counts.get('keyboard', 0)
        mouse = counts.get('mouse', 0)
        
        # 如果输入和上次相同，直接返回缓存结果
        if keyboard == self._last_calculation[0] and mouse == self._last_calculation[1]:
            return self._last_calculation[2]
            
        score = keyboard * self._keyboard_weight + mouse * self._mouse_weight
        
        # 更新缓存和发送信号
        self._last_calculation = (keyboard, mouse, score)
        self.score_updated.emit(score)
        return score
        
    def update_weights(self, keyboard: int, mouse: int) -> None:
        """更新键盘和鼠标的权重"""
        if self._keyboard_weight != keyboard or self._mouse_weight != mouse:
            self._keyboard_weight = keyboard
            self._mouse_weight = mouse
            # 权重变化时清除缓存
            self._last_calculation = (0, 0, 0)

class DataValidator:
    """数据验证工具类"""
    
    @staticmethod
    def validate_event(event: Dict[str, Any]) -> bool:
        """验证事件数据格式"""
        required = ['timestamp', 'event_type']
        return all(key in event for key in required) and \
               event['event_type'] in ['keyboard', 'mouse']
               
    @staticmethod
    def validate_timer(timer: Dict[str, Any]) -> bool:
        """验证计时器数据格式"""
        required = ['name', 'duration']
        return all(key in timer for key in required) and \
               isinstance(timer['duration'], int) and \
               timer['duration'] > 0