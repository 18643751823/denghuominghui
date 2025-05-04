from pynput import keyboard, mouse
from datetime import datetime
import time
import threading
from PyQt6.QtCore import QTimer, QObject, pyqtSignal

class EventListener(QObject):
    """键盘鼠标事件监听器"""
    
    event_recorded = pyqtSignal(str, int)  # 事件类型，时间戳
    
    def __init__(self, db_manager):
        super().__init__()
        self.db = db_manager
        self.last_key_time = 0
        self.last_click_time = 0
        self.keyboard_listener = None
        self.mouse_listener = None
        self.running = False
        
        # 连接信号
        self.event_recorded.connect(self.db.record_event)
        
        # 限流相关
        self.keyboard_throttle = 0.05  # 键盘事件间隔从0.1秒减少到0.05秒
        self.mouse_throttle = 0.05     # 鼠标事件间隔从0.2秒减少到0.05秒
        
        # 事件处理锁
        self.key_lock = threading.Lock()
        self.mouse_lock = threading.Lock()
    
    def on_press(self, key):
        """按键事件处理，使用锁保证线程安全"""
        with self.key_lock:
            current_time = time.time()
            # 防抖动过滤，避免短时间内重复记录
            if current_time - self.last_key_time > self.keyboard_throttle:
                self.event_recorded.emit('keyboard', int(current_time))
                self.last_key_time = current_time
            
    def on_click(self, x, y, button, pressed):
        """鼠标点击事件处理，使用锁保证线程安全"""
        if pressed:
            with self.mouse_lock:
                current_time = time.time()
                # 防抖动过滤，避免短时间内重复记录
                if current_time - self.last_click_time > self.mouse_throttle:
                    self.event_recorded.emit('mouse', int(current_time))
                    self.last_click_time = current_time
                
    def start(self):
        """启动监听器"""
        if self.running:
            return self.keyboard_listener, self.mouse_listener
            
        try:
            # 使用守护线程并忽略错误，提高稳定性
            self.keyboard_listener = keyboard.Listener(
                on_press=self.on_press,
                suppress=False
            )
            self.keyboard_listener.daemon = True
            
            self.mouse_listener = mouse.Listener(
                on_click=self.on_click,
                suppress=False
            )
            self.mouse_listener.daemon = True
            
            # 启动监听线程
            self.keyboard_listener.start()
            self.mouse_listener.start()
            
            self.running = True
            print("事件监听器成功启动")
            
            return self.keyboard_listener, self.mouse_listener
        except Exception as e:
            print(f"启动事件监听器失败: {str(e)}")
            return None, None
    
    def stop(self):
        """停止监听器"""
        if self.keyboard_listener:
            try:
                self.keyboard_listener.stop()
                self.keyboard_listener = None
            except:
                pass
                
        if self.mouse_listener:
            try:
                self.mouse_listener.stop()
                self.mouse_listener = None
            except:
                pass
                
        self.running = False
        print("事件监听器已停止")