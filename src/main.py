import os
import sys
import time
import json
import sqlite3
import csv
from datetime import datetime
from threading import Thread

from PyQt6.QtCore import (
    Qt, QTimer, QDateTime, QSettings, QObject, QEvent, QPoint, 
    pyqtSignal, QSize, QPropertyAnimation, QMargins, QEasingCurve
)
from PyQt6.QtWidgets import (
    QApplication, QWidget, QLabel, QVBoxLayout, QHBoxLayout, QPushButton,
    QDialog, QCheckBox, QSlider, QTabWidget, QTableView, QAbstractItemView,
    QMessageBox, QInputDialog, QFrame, QGroupBox, QMenu, QFileDialog,
    QTableWidget, QSpinBox, QDialogButtonBox, QHeaderView
)
from PyQt6.QtGui import (
    QFont, QColor, QPainter, QPen, QIcon, QAction, QMouseEvent, 
    QFontMetrics, QScreen, QLinearGradient, QPixmap, QPalette, QStandardItemModel, QStandardItem
)
from PyQt6.QtCharts import QChart, QChartView, QLineSeries, QValueAxis
from database import DatabaseManager
from event_listener import EventListener
from core.services import EventService, TimerService
from core.utils import TimeUtils, ScoreCalculator

class KeyEventFilter(QObject):
    """自定义按键事件过滤器，用于处理确认对话框中的按键事件"""
    
    def __init__(self, parent, yes_button, no_button):
        super().__init__(parent)
        self.yes_button = yes_button
        self.no_button = no_button
        
    def eventFilter(self, obj, event):
        # 处理按键事件
        if event.type() == event.Type.KeyPress:
            # 右箭头键 - 移动到"取消"按钮
            if event.key() == Qt.Key.Key_Right:
                self.no_button.setFocus()
                return True
            # 左箭头键 - 移动到"确定"按钮
            elif event.key() == Qt.Key.Key_Left:
                self.yes_button.setFocus()
                return True
                
        # 其他事件交给父类处理
        return super().eventFilter(obj, event)

class DraggableChartView(QChartView):
    """自定义可拖动的图表视图，支持平滑显示和数据点突出显示"""
    
    def __init__(self, chart, parent=None):
        super().__init__(chart, parent)
        self.parent_window = parent
        self.dragging = False
        
        # 启用抗锯齿渲染
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        # 启用更高质量的平滑曲线
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        
        # 启用平滑渐进动画
        self.chart().setAnimationOptions(QChart.AnimationOption.SeriesAnimations)
        self.chart().setAnimationDuration(150)  # 动画持续150毫秒
        
        # 图表主题设置 - 移除可能导致崩溃的主题设置
        # self.chart().setTheme(QChart.ChartTheme.ChartThemeDark)
        
    def mousePressEvent(self, event):
        # 只有左键点击才触发拖动
        if event.button() == Qt.MouseButton.LeftButton and self.parent_window:
            self.dragging = True
            self.parent_window.mousePressEvent(event)
        super().mousePressEvent(event)
        
    def mouseMoveEvent(self, event):
        # 只有在拖动状态下才传递移动事件
        if self.dragging and self.parent_window:
            self.parent_window.mouseMoveEvent(event)
        super().mouseMoveEvent(event)
        
    def mouseReleaseEvent(self, event):
        # 释放左键，结束拖动
        if event.button() == Qt.MouseButton.LeftButton:
            self.dragging = False
            if self.parent_window:
                self.parent_window.mouseReleaseEvent(event)
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        """重写绘制事件，添加自定义绘制功能"""
        super().paintEvent(event)
        
        try:
            # 获取最新数据点（右侧最后一个点）并突出显示
            series = self.chart().series()
            if series and len(series) > 0:
                main_series = series[0]
                if main_series.count() > 0:
                    # 获取最新数据点（最右侧）
                    last_point = main_series.at(main_series.count() - 1)
                    
                    # 只有当y值大于0时才绘制高亮点
                    if last_point.y() > 0.1:
                        # 绘制最新数据点的突出显示标记
                        painter = QPainter(self.viewport())
                        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                        
                        # 转换数据点坐标为视图坐标
                        chart_point = self.chart().mapToPosition(last_point)
                        
                        # 确保点在有效范围内
                        if not chart_point.isNull() and chart_point.x() > 0 and chart_point.y() > 0:
                            # 设置标记样式 - 荧光效果
                            for i in range(3):
                                alpha = 120 - i * 30  # 增加基础透明度，使点更明显
                                size = 6 + i * 2      # 从内到外渐变大小
                                painter.setPen(Qt.PenStyle.NoPen)
                                painter.setBrush(QColor(0, 220, 255, alpha))
                                painter.drawEllipse(chart_point, size, size)
                            
                            # 绘制中心点
                            painter.setPen(Qt.PenStyle.NoPen)
                            painter.setBrush(QColor(255, 255, 255, 220))
                            painter.drawEllipse(chart_point, 3, 3)
                        
                        painter.end()
                    
                    # 查找并标记所有非零点（显示活动点）
                    painter = QPainter(self.viewport())
                    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                    
                    for i in range(main_series.count()):
                        point = main_series.at(i)
                        if point.y() > 0.1:  # 只处理有意义的数据点
                            chart_point = self.chart().mapToPosition(point)
                            if not chart_point.isNull() and chart_point.x() > 0 and chart_point.y() > 0:
                                # 绘制简单的点标记
                                painter.setPen(Qt.PenStyle.NoPen)
                                painter.setBrush(QColor(0, 220, 255, 150))
                                painter.drawEllipse(chart_point, 2, 2)
                    
                    painter.end()
        except Exception as e:
            # 捕获绘制过程中可能的异常，避免程序崩溃
            print(f"图表绘制错误: {e}")

class MainWindow(QWidget):
    update_requested = pyqtSignal()
    
    def __init__(self):
        super().__init__()
        print("MainWindow constructor called")
        self.drag_pos = None
        self._ui_initialized = False
        self._layout_set = False
        
        # 记录启动时间
        self.session_start_time = int(time.time())
        
        # 初始化设置
        self.settings = QSettings("KeyMouseCounter", "Settings")
        
        # 基础窗口设置 - 在UI初始化前优先设置窗口属性
        self.setWindowTitle("键盘鼠标计数器")
        self.setFixedSize(320, 400)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.WindowContextHelpButtonHint
        )
        
        # 加载窗口位置等基本设置
        self.load_window_position()
        
        # 设置窗口透明度
        opacity = self.settings.value("opacity", 0.9, type=float)
        self.setWindowOpacity(opacity)
        
        # 初始化UI组件 - 先创建界面，提高用户体验
        self._init_ui()
        
        # 延迟初始化其他组件，使界面快速显示
        QTimer.singleShot(100, self._delayed_init)
        
    def _delayed_init(self):
        """延迟初始化耗时组件"""
        # 初始化数据库和事件监听
        self.db = DatabaseManager()
        self.listener = EventListener(self.db)
        
        # 初始化服务类
        self.event_service = EventService(self.db)
        self.timer_service = TimerService(self.db)
        self.score_calculator = ScoreCalculator()
        
        # 使用事件监听器的信号机制，避免直接回调
        self.update_requested.connect(self.update_stats)
        
        # 连接事件监听器的信号到更新请求
        self.listener.event_recorded.connect(lambda _, __: self.update_requested.emit())
        
        # 窗口样式设置
        self.setStyleSheet(
            """
            QWidget {
                background: rgba(40, 40, 40, 0.9);
                border: 1px solid #555;
                border-radius: 5px;
                color: #ffffff;
            }
            QLabel {
                background: transparent;
                border: none;
                color: #ffffff;
            }
            QPushButton {
                background: #444;
                color: white;
                border: 1px solid #555;
                border-radius: 3px;
                padding: 5px;
            }
            QPushButton:hover {
                background: #666;
            }
            QPushButton:pressed {
                background: #888;
            }
            """
        )
        
        # 添加上下文菜单
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.ActionsContextMenu)
        exit_action = QAction("退出", self)
        exit_action.triggered.connect(self.close)
        settings_action = QAction("设置", self)
        settings_action.triggered.connect(self.show_settings)
        minimize_action = QAction("最小化", self)
        minimize_action.triggered.connect(self.showMinimized)
        self.addAction(exit_action)
        self.addAction(settings_action)
        self.addAction(minimize_action)
        
        # 启动事件监听
        self.keyboard_listener, self.mouse_listener = self.listener.start()
        
        # 设置定时器 - 加快更新频率
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_stats)
        self.timer.start(500)  # 每秒更新一次UI改为每500毫秒更新一次
        
        # 立即执行一次聚合计算，确保数据可用
        self.event_service.calculate_aggregates()
        
        # 聚合数据定时任务 - 推迟启动，减少启动时的负担
        self.aggregate_timer = QTimer()
        self.aggregate_timer.timeout.connect(self.event_service.calculate_aggregates)
        self.aggregate_timer.start(1800000)  # 30分钟执行一次聚合
        
        # 初始化统计数据
        self.key_count = 0
        self.mouse_count = 0
        self.last_rate = 0
        self.last_update_time = time.time()
        
        # 加载默认计时器设置
        settings = QSettings("MyApp", "KeyMouseTracker")
        default_timer = settings.value("default_timer", 25, type=int)
        self.default_timer_minutes = default_timer
        
        # 初始化完成后执行首次数据更新
        self.update_stats()
        
    def update_stats(self):
        """更新统计数据显示"""
        # 从服务获取本次会话的计数（从启动时间开始）
        counts = self.event_service.get_counts_since(self.session_start_time)
        self.key_count = counts.get('keyboard', 0)
        self.mouse_count = counts.get('mouse', 0)
        
        # 计算过去3秒的速率 - 增加时间窗口，使得数据更有持续性
        current_time = time.time()
        start_time = current_time - 3
        counts = self.event_service.get_counts_since(start_time)
        key_count = counts.get('keyboard', 0)
        mouse_count = counts.get('mouse', 0)
        # 调整计算公式，使速率更加平滑
        rate = (key_count * 1 + mouse_count * 5) * 8  # 调整系数，避免数值过大或过小
        
        # 计算分数 (仍然计算但不显示)
        score = self.score_calculator.calculate_score({
            'keyboard': key_count,
            'mouse': mouse_count
        })
        
        # 更新UI - 使用更明亮的颜色，但不显示分数部分
        trend = "↑" if rate > self.last_rate else "↓"
        color = "#4caf50" if rate > self.last_rate else "#f44336"  # 绿色或红色
        key_color = "#3498db"  # 蓝色
        mouse_color = "#e67e22"  # 橙色
        
        self.status_bar.setText(
            f"键盘: <font color='{key_color}'><b>{self.key_count}</b></font> | "
            f"鼠标: <font color='{mouse_color}'><b>{self.mouse_count}</b></font> | "
            f"速率: <font color='{color}'><b>{rate:.1f}/s {trend}</b></font>"
        )
        
        # 更新折线图 - 改进图表更新逻辑，使其随时间向左推移
        if hasattr(self, 'series'):
            try:
                # 计算当前秒在60秒环形缓冲区中的位置
                seconds_index = int(current_time) % 60
                
                # 计算当前秒的速率值
                # 获取过去1秒内的事件计数 - 延长时间窗口以捕获更多活动
                last_second_start = current_time - 1.0  # 从0.5秒改为1.0秒
                last_second_counts = self.event_service.get_counts_since(last_second_start)
                last_second_key_count = last_second_counts.get('keyboard', 0)
                last_second_mouse_count = last_second_counts.get('mouse', 0)
                
                # 计算当前秒的速率值
                current_second_rate = last_second_key_count * 1 + last_second_mouse_count * 5
                
                # 重要：只有在当前速率为0且上一个点不为0时才执行衰减
                # 这样确保数据点有更长的持续时间，而不是立即归零
                if current_second_rate == 0 and hasattr(self, 'last_point_value') and self.last_point_value > 0:
                    # 使用更缓慢的衰减，延长数据点的可见时间
                    current_second_rate = self.last_point_value * 0.9  # 每次只衰减10%
                    
                    # 如果值太小，则设为0以避免无限衰减
                    if current_second_rate < 0.1:
                        current_second_rate = 0
                        
                # 数据平滑 - 对非零数据使用不同的平滑策略
                elif current_second_rate > 0 and hasattr(self, 'last_point_value'):
                    if self.last_point_value > 0:
                        # 对于连续的活动进行60/40平滑
                        smoothed_rate = current_second_rate * 0.6 + self.last_point_value * 0.4
                    else:
                        # 对于新开始的活动，保留80%原值以保证波动明显
                        smoothed_rate = current_second_rate * 0.8
                    current_second_rate = smoothed_rate
                
                # 保存当前值用于下次平滑计算
                self.last_point_value = current_second_rate
                
                # 记录当前秒对应的数据点
                self.rate_buffer[seconds_index] = current_second_rate
                
                # 清空现有数据点
                self.series.clear()
                
                # 以最新数据保持在右侧的方式重新填充点，确保图表随时间向左滚动
                for i in range(60):
                    # 计算环形缓冲区索引
                    buffer_index = (seconds_index - i + 60) % 60  # 确保索引为正数
                    
                    # X坐标：最新的数据在最右边（59），然后向左递减
                    x_coord = 59 - i
                    
                    # 获取Y值并确保非负
                    y_value = max(0, self.rate_buffer[buffer_index])
                    
                    # 添加点到系列
                    self.series.append(x_coord, y_value)
                
                # 自动调整Y轴范围 - 增加最小值确保小的波动也能看到
                max_value_in_buffer = max(self.rate_buffer)
                
                # 计算合适的Y轴最大值 - 确保有足够空间显示波动
                if max_value_in_buffer < 0.5:  # 几乎没有活动
                    target_max = 5.0  # 使用默认最小值
                elif max_value_in_buffer < 3.0:  # 低活动水平
                    target_max = max_value_in_buffer * 2 + 1  # 提供更多空间
                else:  # 正常或高活动水平
                    target_max = max_value_in_buffer * 1.2 + 1  # 提供20%额外空间
                
                # 平滑Y轴最大值变化 - 避免频繁跳动
                current_max = self.axisY.max()
                    
                # 逐步调整Y轴 - 上升快，下降慢
                if target_max > current_max:  # 需要增加范围
                    # 快速增加以适应新的最大值
                    new_max = min(current_max * 1.3, target_max)
                    if abs(new_max - current_max) / current_max > 0.1:  # 只有变化大于10%才更新
                        self.axisY.setRange(0, new_max)
                elif current_max > target_max * 1.5:  # 当前范围远大于需要
                    # 缓慢减小以平滑过渡
                    new_max = current_max * 0.95  # 每次只减少5%
                    if new_max > 5.0:  # 不要低于最小值
                        self.axisY.setRange(0, new_max)
            except Exception as e:
                print(f"更新图表时出错: {e}")
        
        self.last_rate = rate
        self.last_update_time = current_time
        
    def _init_ui(self):
        """初始化UI组件"""
        if self._ui_initialized:
            return
            
        # 添加自定义关闭按钮
        close_btn = QPushButton("×", self)
        close_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #aaa; font-size: 18px; border: none; padding: 0 8px; }"
            "QPushButton:hover { color: #f55; }"
        )
        close_btn.setFixedSize(30, 30)
        close_btn.move(290, 0)  # 更新X坐标以匹配新的窗口宽度
        close_btn.clicked.connect(self.close)
            
        # 主UI布局
        main_layout = None
        if not self._layout_set:
            main_layout = QVBoxLayout(self)
            main_layout.setContentsMargins(10, 40, 10, 10)
            self._layout_set = True
        else:
            main_layout = self.layout()
            
        # 创建状态显示标签
        self.status_bar = QLabel("正在初始化...", self)
        self.status_bar.setStyleSheet(
            "background: rgba(60, 60, 60, 0.8);"
            "border: 1px solid #555;"
            "border-radius: 4px;"
            "padding: 10px;"
            "font-weight: bold;"
        )
        self.status_bar.setWordWrap(True)
        main_layout.addWidget(self.status_bar)
        
        # 图表区域
        self.chart = QChart()
        self.chart.setTitle("键盘鼠标活动实时趋势图")
        self.chart.setTitleBrush(Qt.GlobalColor.white)
        self.chart.setBackgroundBrush(Qt.GlobalColor.transparent)
        self.chart.legend().setVisible(False)
        
        # 设置图表边距，减少边缘空白区域，让图表内容占更多空间
        self.chart.setMargins(QMargins(5, 5, 5, 5))
        self.chart.layout().setContentsMargins(0, 0, 0, 0)
        
        # 减小标题字体大小，节省空间
        title_font = self.chart.titleFont()
        title_font.setPointSize(9)
        self.chart.setTitleFont(title_font)
        
        # 初始化环形缓冲区数据
        self.rate_buffer = [0] * 60
        self.last_point_value = 0  # 保存最后一个点的值，用于平滑计算
        
        # 配置图表系列
        self.series = QLineSeries()
        pen = QPen(QColor(0, 200, 255, 200), 2)  # 设置更明亮的青色，线宽2，加入透明度
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        pen.setWidth(3)  # 增加线宽使波动更明显
        self.series.setPen(pen)
        self.series.setUseOpenGL(True)  # 使用OpenGL渲染
        
        # 添加区域效果 - 在线下方添加渐变填充
        gradient = QLinearGradient(0, 0, 0, 300)
        gradient.setColorAt(0.0, QColor(0, 200, 255, 100))  # 顶部颜色（半透明）
        gradient.setColorAt(0.5, QColor(0, 200, 255, 30))   # 中间颜色（更透明）
        gradient.setColorAt(1.0, QColor(0, 200, 255, 0))    # 底部颜色（完全透明）
        self.series.setBrush(gradient)
        
        # 初始化图表数据点，最新的数据在右侧
        for i in range(60):
            self.series.append(i, 0)
        
        # 将系列添加到图表
        self.chart.addSeries(self.series)
        
        # 创建并保存轴对象引用
        self.axisX = QValueAxis()
        self.axisX.setRange(0, 59)  # X轴固定范围0-59秒
        self.axisX.setTitleText("时间轴 (60秒)")
        self.axisX.setTitleBrush(Qt.GlobalColor.white)
        self.axisX.setLabelsColor(Qt.GlobalColor.white)
        self.axisX.setGridLineColor(QColor(80, 80, 80, 120))  # 半透明的网格线
        self.axisX.setGridLineVisible(True)
        # 减少轴标签大小
        self.axisX.setLabelsFont(QFont("Arial", 7))
        # 设置刻度，每15秒一个刻度
        self.axisX.setTickCount(5)  # 0, 15, 30, 45, 59
        # 设置次要刻度，每5秒一个刻度
        self.axisX.setMinorTickCount(2)
        
        self.axisY = QValueAxis()
        self.axisY.setRange(0, 5)  # 设置更小的初始Y轴范围，使小波动更明显
        self.axisY.setTitleText("活动强度")
        self.axisY.setTitleBrush(Qt.GlobalColor.white)
        self.axisY.setLabelsColor(Qt.GlobalColor.white)
        self.axisY.setGridLineColor(QColor(80, 80, 80, 120))  # 半透明的网格线
        self.axisY.setGridLineVisible(True)
        # 设置刻度
        self.axisY.setTickCount(6)
        # 减少轴标签大小
        self.axisY.setLabelsFont(QFont("Arial", 7))
        
        self.chart.addAxis(self.axisX, Qt.AlignmentFlag.AlignBottom)
        self.chart.addAxis(self.axisY, Qt.AlignmentFlag.AlignLeft)
        self.series.attachAxis(self.axisX)
        self.series.attachAxis(self.axisY)
        
        # 创建图表视图
        self.chart_view = DraggableChartView(self.chart, self)
        self.chart_view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.chart_view.setStyleSheet("background: transparent;")
        # 增加图表视图的stretch比例，使其占据更多空间
        main_layout.addWidget(self.chart_view, stretch=4)
        
        # 倒计时区域 - 使用水平布局
        timer_container = QWidget()
        timer_layout = QHBoxLayout(timer_container)
        timer_layout.setContentsMargins(0, 0, 0, 0)
        timer_layout.setSpacing(4)  # 减小间距
        
        # 倒计时显示
        self.timer_label = QLabel("倒计时: 00:00")
        self.timer_label.setStyleSheet(
            "background: rgba(60, 60, 60, 0.8);"
            "color: white;"
            "border: 1px solid #555;"
            "padding: 5px;"  # 减少内边距
            "font-size: 13px;"  # 稍微减小字体
            "font-weight: bold;"
            "border-radius: 4px;"  # 减小圆角
        )
        self.timer_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        timer_layout.addWidget(self.timer_label, 3)  # 倒计时标签占比例3
        
        # 控制按钮共同样式
        button_style = """
            QPushButton {
                background: rgba(50, 50, 50, 0.8);
                color: white;
                border: 1px solid #555;
                font-size: 12px;
                font-weight: bold;
                border-radius: 4px;
                padding: 4px;
                min-width: 24px;
            }
            QPushButton:hover {
                background: rgba(70, 70, 70, 0.9);
                border: 1px solid #777;
            }
            QPushButton:pressed {
                background: rgba(90, 90, 90, 0.9);
            }
            QPushButton:disabled {
                background: rgba(40, 40, 40, 0.8);
                color: #777;
                border: 1px solid #444;
            }
        """
        
        # 暂停按钮
        self.pause_button = QPushButton("暂停")
        self.pause_button.setToolTip("暂停计时")
        self.pause_button.setStyleSheet(button_style)
        self.pause_button.clicked.connect(self.pause_timer)
        timer_layout.addWidget(self.pause_button, 1)  # 按钮占比例1
        
        # 启动按钮
        self.start_button = QPushButton("启动")
        self.start_button.setToolTip("启动计时")
        self.start_button.setStyleSheet(button_style)
        self.start_button.clicked.connect(self.start_timer)
        timer_layout.addWidget(self.start_button, 1)  # 按钮占比例1
        
        # 恢复按钮
        self.reset_button = QPushButton("归位")
        self.reset_button.setToolTip("恢复默认计时")
        self.reset_button.setStyleSheet(button_style)
        self.reset_button.clicked.connect(self.reset_timer)
        timer_layout.addWidget(self.reset_button, 1)  # 按钮占比例1
        
        # 禁用所有按钮，直到有计时器启动
        self.pause_button.setEnabled(False)
        self.start_button.setEnabled(True)  # 开始按钮始终可用
        self.reset_button.setEnabled(False)
        
        # 添加计时器容器到主布局
        main_layout.addWidget(timer_container, stretch=1)
        
        # 存储计时器状态
        self.timer_paused = False
        
        self._ui_initialized = True

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            # 左键处理拖动
            self.drag_pos = event.globalPosition().toPoint()
            event.accept()
        elif event.button() == Qt.MouseButton.RightButton:
            # 右键直接交给contextMenu处理
            event.ignore()

    def mouseMoveEvent(self, event):
        print(f"鼠标移动位置: {event.pos()}, 按键状态: {event.buttons()}")
        if event.buttons() == Qt.MouseButton.LeftButton and self.drag_pos:
            new_pos = self.pos() + event.globalPosition().toPoint() - self.drag_pos
            print(f"移动窗口到: {new_pos}")
            self.move(new_pos)
            self.drag_pos = event.globalPosition().toPoint()
            event.accept()
        else:
            event.ignore()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.drag_pos:
            self.drag_pos = None
            event.accept()

    def closeEvent(self, event):
        """窗口关闭事件处理"""
        # 保存当前窗口位置
        pos = self.pos()
        self.settings.setValue("window_pos_x", pos.x())
        self.settings.setValue("window_pos_y", pos.y())
        self.settings.sync()  # 立即写入设置
        print(f"退出前保存窗口位置: ({pos.x()}, {pos.y()})")
        
        # 停止所有定时器，防止退出时卡顿
        if hasattr(self, 'timer'):
            self.timer.stop()
        if hasattr(self, 'aggregate_timer'):
            self.aggregate_timer.stop() 
        if hasattr(self, 'timer_countdown') and self.timer_countdown.isActive():
            self.timer_countdown.stop()
            
        # 使用QTimer延迟停止监听器和关闭数据库，让界面先关闭
        QTimer.singleShot(0, self._cleanup_resources)
        
        # 调用父类方法
        super().closeEvent(event)
        
    def _cleanup_resources(self):
        """释放资源的延迟处理函数"""
        # 停止监听器
        if hasattr(self, "listener") and self.listener:
            self.listener.stop()  # 使用优化后的stop方法
        
        # 关闭数据库连接
        if hasattr(self, "db") and self.db:
            self.db.close()
            
        print("资源清理完成")

    def start_timer_countdown(self, minutes):
        """启动计时器倒计时"""
        if hasattr(self, 'timer_countdown'):
            self.timer_countdown.stop()
            
        self.timer_countdown = QTimer()
        self.timer_countdown.timeout.connect(self.update_timer_display)
        
        # 如果是暂停后继续，使用剩余时间
        if hasattr(self, 'remaining_seconds') and self.timer_paused:
            # 继续使用剩余时间
            pass
        else:
            # 初始化新的倒计时
            self.remaining_seconds = minutes * 60
        
        # 更新按钮状态
        self.pause_button.setEnabled(True)
        self.start_button.setEnabled(False)
        self.reset_button.setEnabled(True)
        self.timer_paused = False
        
        # 更新UI显示
        mins, secs = divmod(self.remaining_seconds, 60)
        self.timer_label.setStyleSheet(
            "background: rgba(60, 60, 60, 0.8);"
            "color: #3498db;"
            "border: 1px solid #555;"
            "padding: 5px;"  # 减少内边距
            "font-size: 13px;"  # 稍微减小字体
            "font-weight: bold;"
            "border-radius: 4px;"  # 减小圆角
        )
        self.timer_label.setText(f"计时器: <b>{mins:02d}:{secs:02d}</b>")
        
        self.timer_countdown.start(1000)  # 每秒更新一次

    def update_timer_display(self):
        """更新计时器显示"""
        self.remaining_seconds -= 1
        mins, secs = divmod(self.remaining_seconds, 60)
        
        # 根据剩余时间更改颜色：正常、警告、紧急
        if self.remaining_seconds > 60:  # 大于1分钟，蓝色
            color = "#3498db"
        elif self.remaining_seconds > 10:  # 小于1分钟，黄色
            color = "#f39c12"
        else:  # 小于10秒，红色
            color = "#e74c3c"
            
        self.timer_label.setStyleSheet(
            "background: rgba(60, 60, 60, 0.8);"
            f"color: {color};"
            "border: 1px solid #555;"
            "padding: 5px;"  # 减少内边距
            "font-size: 13px;"  # 稍微减小字体
            "font-weight: bold;"
            "border-radius: 4px;"  # 减小圆角
        )
        
        self.timer_label.setText(f"计时器: <b>{mins:02d}:{secs:02d}</b>")
        
        if self.remaining_seconds <= 0:
            self.timer_countdown.stop()
            self.timer_label.setStyleSheet(
                "background: rgba(60, 60, 60, 0.8);"
                "color: white;"
                "border: 1px solid #555;"
                "padding: 5px;"  # 减少内边距
                "font-size: 13px;"  # 稍微减小字体
                "font-weight: bold;"
                "border-radius: 4px;"  # 减小圆角
            )
            self.timer_label.setText("计时器: <b>完成</b>")
            QMessageBox.information(self, "计时器", "时间到！")
            
            # 重置按钮状态
            self.pause_button.setEnabled(False)
            self.start_button.setEnabled(True)
            self.reset_button.setEnabled(False)
            return
            
    def show_settings(self):
        """安全显示设置对话框"""
        try:
            if not hasattr(self, '_settings_dialog') or not self._settings_dialog:
                self._settings_dialog = SettingsDialog(self)
                # 确保对话框关闭时释放资源
                self._settings_dialog.finished.connect(self.on_settings_dialog_closed)
            
            # 仅显示对话框，不再通过QTimer加载计时器
            self._settings_dialog.show()
            
        except Exception as e:
            print(f"打开设置失败: {str(e)}")
            QMessageBox.critical(self, "错误", "无法打开设置界面")
            
    def on_settings_dialog_closed(self, result):
        """处理设置对话框关闭事件"""
        # 释放对话框资源
        if hasattr(self, '_settings_dialog') and self._settings_dialog:
            self._settings_dialog = None

    def load_settings(self):
        """加载设置"""
        # 加载透明度设置
        opacity = self.settings.value("opacity", 0.9, type=float)
        self.setWindowOpacity(opacity)
        
        # 加载默认计时器设置
        settings = QSettings("MyApp", "KeyMouseTracker")
        default_timer = settings.value("default_timer", 25, type=int)
        self.default_timer_minutes = default_timer
        
    def load_window_position(self):
        """单独加载窗口位置设置"""
        print("正在尝试恢复窗口位置...")
        pos_x = self.settings.value("window_pos_x", -1, type=int)
        pos_y = self.settings.value("window_pos_y", -1, type=int)
        
        if pos_x >= 0 and pos_y >= 0:
            # 确保窗口在屏幕范围内
            screen_rect = QApplication.primaryScreen().availableGeometry()
            print(f"上次退出位置: ({pos_x}, {pos_y})")
            print(f"屏幕分辨率: {screen_rect.width()}x{screen_rect.height()}")
            
            if pos_x < screen_rect.width() - 50 and pos_y < screen_rect.height() - 50 and pos_y >= 0:
                self.move(pos_x, pos_y)
                print(f"✓ 成功恢复窗口位置: ({pos_x}, {pos_y})")
            else:
                print("✗ 窗口位置超出屏幕范围，使用默认位置")
        else:
            print("✗ 没有找到保存的窗口位置，使用默认位置")

    def save_settings(self, opacity=None):
        """保存设置
        Args:
            opacity: 窗口透明度，值范围0.3-1.0
        """
        if opacity is not None:
            self.settings.setValue("opacity", opacity)
            self.setWindowOpacity(opacity)
        
        # 将所有设置同步到存储
        self.settings.sync()

    def contextMenuEvent(self, event):
        """右键菜单事件处理"""
        menu = QMenu(self)
        
        # 添加计时器菜单
        timer_menu = QMenu("计时器", menu)
        timer_menu.setStyleSheet("background: rgba(30, 30, 30, 0.9); color: white;")
        
        # 从设置中获取已保存的计时器列表
        settings = QSettings("MyApp", "KeyMouseTracker")
        timers = settings.value("timers", [])
        
        if not timers:
            no_timer_action = QAction("暂无计时器", self)
            no_timer_action.setEnabled(False)
            timer_menu.addAction(no_timer_action)
        else:
            # 排序计时器（按ID）
            timers.sort(key=lambda x: x["id"])
            
            # 添加计时器选项
            for timer in timers:
                timer_action = QAction(f"{timer['id']}. {timer['minutes']}分钟", self)
                timer_action.triggered.connect(
                    lambda checked, m=timer['minutes']: self.start_timer_countdown(m)
                )
                timer_menu.addAction(timer_action)
                
        menu.addMenu(timer_menu)
        
        # 显示设置动作
        settings_action = QAction("设置", self)
        settings_action.triggered.connect(self.show_settings)
        menu.addAction(settings_action)
        
        # 添加退出动作
        exit_action = QAction("退出", self)
        exit_action.triggered.connect(self.close)
        menu.addAction(exit_action)
        
        # 在鼠标位置显示菜单
        menu.exec(event.globalPosition().toPoint())

    def pause_timer(self):
        """暂停计时器"""
        if hasattr(self, 'timer_countdown') and self.timer_countdown.isActive():
            self.timer_countdown.stop()
            self.timer_paused = True
            self.pause_button.setEnabled(False)
            self.start_button.setEnabled(True)
            self.reset_button.setEnabled(True)
            # 更新UI显示暂停状态
            self.timer_label.setText(f"⏸ <b>{self.timer_label.text()[9:]}</b>")
            
    def start_timer(self):
        """启动或继续计时器"""
        if self.timer_paused and hasattr(self, 'remaining_seconds'):
            # 继续已暂停的计时器
            self.timer_countdown = QTimer()
            self.timer_countdown.timeout.connect(self.update_timer_display)
            self.timer_countdown.start(1000)
            
            # 更新按钮状态
            self.pause_button.setEnabled(True)
            self.start_button.setEnabled(False)
            self.reset_button.setEnabled(True)
            self.timer_paused = False
            
            # 更新UI去掉暂停标志
            mins, secs = divmod(self.remaining_seconds, 60)
            self.timer_label.setText(f"计时器: <b>{mins:02d}:{secs:02d}</b>")
        else:
            # 使用默认时间启动新计时器
            self.start_timer_countdown(self.default_timer_minutes)
            
    def reset_timer(self):
        """重置为默认计时器"""
        # 停止当前计时器
        if hasattr(self, 'timer_countdown'):
            self.timer_countdown.stop()
        
        # 重置为默认时间但不启动
        self.remaining_seconds = self.default_timer_minutes * 60
        mins, secs = divmod(self.remaining_seconds, 60)
        
        # 更新UI
        self.timer_label.setStyleSheet(
            "background: rgba(60, 60, 60, 0.8);"
            "color: white;"  # 未启动时使用白色
            "border: 1px solid #555;"
            "padding: 5px;"
            "font-size: 13px;"
            "font-weight: bold;"
            "border-radius: 4px;"
        )
        self.timer_label.setText(f"计时器: <b>{mins:02d}:{secs:02d}</b>")
        
        # 更新按钮状态
        self.pause_button.setEnabled(False)
        self.start_button.setEnabled(True)
        self.reset_button.setEnabled(False)
        self.timer_paused = False

    def export_today_data(self):
        """导出今日数据"""
        try:
            # 检查是否有数据库连接
            if not hasattr(self, 'event_service'):
                QMessageBox.warning(self, "导出失败", "无法访问数据库")
                return
                
            # 获取今日聚合数据，使用新的精确方法
            today_data = self.event_service.get_today_aggregated_data('15min', 96)
            
            if not today_data:
                QMessageBox.information(self, "导出提示", "今日暂无活动记录")
                return
                
            # 提示用户选择导出方式
            options = ["复制到剪贴板", "导出为CSV文件", "导出为Excel文件", "取消"]
            choice, ok = QInputDialog.getItem(
                self,
                "选择导出方式",
                "请选择数据导出方式:",
                options,
                0,  # 默认选择第一项
                False  # 不可编辑
            )
            
            if not ok or choice == "取消":
                return
                
            if choice == "复制到剪贴板":
                self._copy_to_clipboard(today_data)
            elif choice == "导出为CSV文件":
                default_filename = f"键鼠活动统计_{datetime.now().strftime('%Y-%m-%d')}.csv"
                file_path, _ = QFileDialog.getSaveFileName(
                    self, 
                    "保存文件", 
                    os.path.join(os.path.expanduser("~"), "Desktop", default_filename),
                    "CSV文件 (*.csv)"
                )
                
                if not file_path:
                    return  # 用户取消了保存
                    
                if not file_path.endswith('.csv'):
                    file_path += '.csv'  # 确保有正确的扩展名
                
                success = self._export_as_csv(file_path, today_data)
                
                if success:
                    QMessageBox.information(
                        self, 
                        "导出成功", 
                        f"成功导出{len(today_data)}条记录到:\n{file_path}"
                    )
            elif choice == "导出为Excel文件":
                default_filename = f"键鼠活动统计_{datetime.now().strftime('%Y-%m-%d')}.xlsx"
                file_path, _ = QFileDialog.getSaveFileName(
                    self, 
                    "保存文件", 
                    os.path.join(os.path.expanduser("~"), "Desktop", default_filename),
                    "Excel文件 (*.xlsx)"
                )
                
                if not file_path:
                    return  # 用户取消了保存
                    
                success = self._export_as_excel(file_path, today_data)
                
                if success:
                    QMessageBox.information(
                        self, 
                        "导出成功", 
                        f"成功导出{len(today_data)}条记录到:\n{file_path}"
                    )
            
        except Exception as e:
            QMessageBox.critical(self, "导出错误", f"导出过程中发生错误: {str(e)}")
    
    def _copy_to_clipboard(self, data):
        """将数据复制到剪贴板，使用改进的格式"""
        try:
            # 确保只筛选今天的数据
            today = datetime.now().strftime("%Y-%m-%d")
            today_data = [item for item in data if item['period'].startswith(today)]
            
            if not today_data:
                QMessageBox.information(self, "复制提示", "今日暂无活动记录")
                return
                
            # 按时间排序
            sorted_data = sorted(today_data, key=lambda x: x['period'])
            
            # 打印调试信息，确认数据日期正确
            print(f"正在复制今日 ({today}) 数据，共 {len(sorted_data)} 条记录:")
            for item in sorted_data[:3]:  # 只打印前3条作为示例
                print(f"  - {item['period']}, 键盘:{item['keyboard']}, 鼠标:{item['mouse']}, 分数:{item['score']}")
            
            # 合并连续的时间段，如果它们的活跃度相近
            merged_data = []
            if sorted_data:
                current_start = sorted_data[0]['period']
                current_score = sorted_data[0]['score']
                current_data = sorted_data[0]
                
                for i in range(1, len(sorted_data)):
                    # 如果分数相差不大（50%以内），且时间连续，则合并
                    score_diff = abs(sorted_data[i]['score'] - current_score) / max(current_score, 1)
                    time_diff = self._get_time_diff_minutes(sorted_data[i-1]['period'], sorted_data[i]['period'])
                    
                    if score_diff <= 0.5 and time_diff <= 15:
                        # 累加数据
                        current_data['keyboard'] += sorted_data[i]['keyboard']
                        current_data['mouse'] += sorted_data[i]['mouse']
                        current_data['score'] += sorted_data[i]['score']
                    else:
                        # 添加之前的数据并开始新的时间段
                        current_end = sorted_data[i-1]['period']
                        start_time = self._format_time(current_start)
                        end_time = self._format_time(current_end)
                        merged_data.append({
                            'period': f"{start_time}-{end_time}",
                            'score': current_data['score']
                        })
                        
                        current_start = sorted_data[i]['period']
                        current_score = sorted_data[i]['score']
                        current_data = sorted_data[i].copy()
                
                # 添加最后一个时间段
                current_end = sorted_data[-1]['period']
                start_time = self._format_time(current_start)
                end_time = self._format_time(current_end)
                merged_data.append({
                    'period': f"{start_time}-{end_time}",
                    'score': current_data['score']
                })
            
            # 格式化输出
            lines = []
            for i, item in enumerate(merged_data, 1):
                lines.append(f"{i}. {item['period']}，{item['score']}分")
                
            formatted_text = "\n".join(lines)
            
            # 复制到剪贴板
            clipboard = QApplication.clipboard()
            clipboard.setText(formatted_text)
            
            QMessageBox.information(self, "复制成功", f"已复制{len(merged_data)}条今日({today})记录到剪贴板")
            
        except Exception as e:
            print(f"复制到剪贴板时出错: {e}")
            QMessageBox.warning(self, "复制失败", f"复制到剪贴板时出错: {str(e)}")
    
    def _format_time(self, time_string):
        """将时间字符串格式化为更易读的形式"""
        try:
            # 示例输入: '2023-04-10 14:30'
            if ' ' in time_string:
                time_part = time_string.split(' ')[1]
                # 将小时:分钟格式提取出来
                if ':' in time_part:
                    hour, minute = time_part.split(':')
                    return f"{hour}:{minute}"
            return time_string  # 如果不符合预期格式，返回原字符串
        except:
            return time_string
    
    def _get_time_diff_minutes(self, time1, time2):
        """计算两个时间字符串之间的分钟差"""
        try:
            # 示例输入: '2023-04-10 14:30'
            format_str = "%Y-%m-%d %H:%M"
            t1 = datetime.strptime(time1, format_str)
            t2 = datetime.strptime(time2, format_str)
            
            # 返回分钟差
            return abs((t2 - t1).total_seconds() / 60)
        except:
            return 999  # 解析失败，返回一个大值表示不连续

    def _export_as_csv(self, file_path, data):
        """导出为CSV格式"""
        try:
            with open(file_path, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f)
                # 写入表头
                writer.writerow(['时间段', '键盘点击', '鼠标点击', '活动分数'])
                
                # 写入数据行
                for item in data:
                    period = item['period']
                    keyboard = item['keyboard']
                    mouse = item['mouse']
                    score = item['score']
                    writer.writerow([period, keyboard, mouse, score])
            return True
        except Exception as e:
            print(f"CSV导出错误: {e}")
            return False
            
    def _export_as_excel(self, file_path, data):
        """导出为Excel格式"""
        try:
            try:
                import pandas as pd
            except ImportError:
                QMessageBox.warning(
                    self, 
                    "功能受限", 
                    "未安装pandas库，无法导出为Excel格式。\n将以CSV格式导出数据。"
                )
                return self._export_as_csv(file_path.replace('.xlsx', '.csv'), data)
                
            # 将数据转换为DataFrame
            df = pd.DataFrame([
                {
                    '时间段': item['period'],
                    '键盘点击': item['keyboard'],
                    '鼠标点击': item['mouse'],
                    '活动分数': item['score']
                } for item in data
            ])
            
            # 写入Excel文件
            df.to_excel(file_path, index=False, sheet_name='键鼠活动统计')
            return True
        except Exception as e:
            print(f"Excel导出错误: {e}")
            return False

class SettingsDialog(QDialog):
    """设置对话框"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.setWindowTitle("设置")
        self.setMinimumWidth(400)
        self.setMinimumHeight(500)
        self.resize(450, 600)
        
        # 设置窗口居中于父窗口
        if parent:
            parent_center = parent.geometry().center()
            self.setGeometry(
                parent_center.x() - self.width() // 2,
                parent_center.y() - self.height() // 2,
                self.width(),
                self.height()
            )
        
        self._init_ui()
        
        # 设置对话框关闭时关联
        self.finished.connect(self.on_dialog_closed)
        
        # 应用黑色主题
        self.setStyleSheet("""
            QDialog {
                background-color: #2D2D2D;
                color: white;
            }
            QGroupBox {
                background-color: #333;
                border: 1px solid #444;
                border-radius: 5px;
                margin-top: 15px;
                font-weight: bold;
                color: white;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top center;
                padding: 0 5px;
                color: white;
            }
            QLabel {
                color: white;
            }
            QTableView {
                background-color: #2D2D2D;
                color: white;
            }
        """)

    def _init_ui(self):
        """初始化对话框UI"""
        # 创建主要布局
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(6)
        
        # 添加透明度设置组
        opacity_group = QGroupBox("窗口透明度")
        opacity_layout = QVBoxLayout(opacity_group)
        
        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setRange(30, 100)
        self.opacity_slider.setValue(int(self.parent.windowOpacity() * 100))
        self.opacity_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #444, stop:1 #16A085);
                height: 8px;
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                background: #3498DB;
                width: 16px;
                margin: -4px 0;
                border-radius: 8px;
            }
        """)
        
        opacity_layout.addWidget(self.opacity_slider)
        
        # 添加透明度百分比显示
        self.opacity_label = QLabel(f"{self.opacity_slider.value()}%")
        self.opacity_label.setStyleSheet("color: #3498DB; font-weight: bold;")
        self.opacity_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        opacity_layout.addWidget(self.opacity_label)
        
        # 添加提示标签
        tip_label = QLabel("拖动滑块可实时预览透明度效果")
        tip_label.setStyleSheet("color: #888; font-size: 11px; font-style: italic;")
        opacity_layout.addWidget(tip_label)
        
        # 连接透明度滑块的值变化信号 - 立即应用更改
        self.opacity_slider.valueChanged.connect(self.apply_opacity)
        
        main_layout.addWidget(opacity_group)
        
        # 添加计时器管理组
        timer_group = QGroupBox("计时器管理")
        timer_layout = QVBoxLayout(timer_group)
        
        # 计时器表格
        self.timer_table = QTableView()
        self.timer_table.setStyleSheet("""
            QTableView {
                background-color: #2D2D2D;
                color: white;
                gridline-color: #555;
                selection-background-color: #3498DB;
                selection-color: white;
                border: none;
            }
            QHeaderView::section {
                background-color: #444;
                color: white;
                padding: 5px;
                border: none;
            }
        """)
        self.timer_table.setMaximumHeight(180)  # 限制表格最大高度
        
        # 创建并设置模型
        self.timer_model = QStandardItemModel()
        self.timer_model.setHorizontalHeaderLabels(["ID", "分钟数", "操作"])
        self.timer_table.setModel(self.timer_model)
        
        # 设置表格属性
        self.timer_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.timer_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.timer_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.timer_table.horizontalHeader().setStretchLastSection(True)
        
        # 加载计时器数据
        self.load_timers()
        
        timer_layout.addWidget(self.timer_table)
        
        # 添加计时器按钮
        buttons_layout = QHBoxLayout()
        
        self.add_timer_btn = QPushButton("添加")
        self.add_timer_btn.setStyleSheet("""
            QPushButton {
                background-color: #3498DB;
                color: white;
                padding: 8px 12px;
                border: none;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2980B9;
            }
            QPushButton:pressed {
                background-color: #1F6AA5;
            }
        """)
        self.add_timer_btn.clicked.connect(self.add_timer)
        buttons_layout.addWidget(self.add_timer_btn)
        
        timer_layout.addLayout(buttons_layout)
        
        main_layout.addWidget(timer_group)
        
        # 添加数据管理组
        data_group = QGroupBox("数据管理")
        data_layout = QVBoxLayout(data_group)
        
        # 添加数据统计显示
        self.data_summary = QLabel("今日数据: 正在加载...")
        self.data_summary.setStyleSheet("""
            QLabel {
                background-color: #2c3e50;
                color: white;
                padding: 8px;
                border-radius: 4px;
                font-size: 12px;
            }
        """)
        self.data_summary.setWordWrap(True)
        self.data_summary.setFixedHeight(100)  # 固定高度以美化布局
        data_layout.addWidget(self.data_summary)
        
        # 添加数据操作按钮布局
        data_buttons_layout = QHBoxLayout()
        
        # 导出今日数据按钮
        self.export_today_btn = QPushButton("导出今日数据")
        self.export_today_btn.setStyleSheet("""
            QPushButton {
                background-color: #9b59b6;
                color: white;
                padding: 10px;
                border: none;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #8e44ad;
            }
            QPushButton:pressed {
                background-color: #6c3483;
            }
        """)
        self.export_today_btn.setIcon(self.style().standardIcon(self.style().StandardPixmap.SP_DialogSaveButton))
        self.export_today_btn.clicked.connect(self.export_today_data)
        data_buttons_layout.addWidget(self.export_today_btn)
        
        # 复制到剪贴板按钮
        self.copy_btn = QPushButton("复制到剪贴板")
        self.copy_btn.setStyleSheet("""
            QPushButton {
                background-color: #16a085;
                color: white;
                padding: 10px;
                border: none;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #138d75;
            }
            QPushButton:pressed {
                background-color: #107a65;
            }
        """)
        self.copy_btn.setIcon(self.style().standardIcon(self.style().StandardPixmap.SP_DialogResetButton))
        self.copy_btn.clicked.connect(self.copy_today_data)
        data_buttons_layout.addWidget(self.copy_btn)
        
        data_layout.addLayout(data_buttons_layout)
        
        main_layout.addWidget(data_group)
        
        # 加载今日数据
        QTimer.singleShot(100, self.load_today_summary)

    def apply_opacity(self, value):
        """实时应用透明度变化并保存"""
        opacity = value / 100
        self.parent.setWindowOpacity(opacity)
        self.opacity_label.setText(f"{value}%")
        
        # 立即保存设置
        self.parent.save_settings(opacity=opacity)

    def load_timers(self):
        """加载计时器数据"""
        # 清除旧数据
        self.timer_model.setRowCount(0)
        
        # 从设置中加载计时器项
        settings = QSettings("MyApp", "KeyMouseTracker")
        timers = settings.value("timers", [])
        default_timer_id = settings.value("default_timer_id", -1, type=int)
        
        # 添加到表格
        for timer in timers:
            row = self.timer_model.rowCount()
            self.timer_model.insertRow(row)
            
            # ID 列
            id_item = QStandardItem(str(timer["id"]))
            id_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            
            # 如果是默认计时器，添加标记
            if timer["id"] == default_timer_id:
                id_item.setText(str(timer["id"]) + " ★")
                id_item.setToolTip("默认计时器")
                
            self.timer_model.setItem(row, 0, id_item)
            
            # 分钟数列
            minutes_item = QStandardItem(str(timer["minutes"]))
            minutes_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.timer_model.setItem(row, 1, minutes_item)
            
            # 操作列（包含删除和设为默认按钮）
            actions_widget = QWidget()
            actions_layout = QHBoxLayout(actions_widget)
            actions_layout.setContentsMargins(2, 2, 2, 2)
            actions_layout.setSpacing(4)
            
            # 删除按钮
            delete_btn = QPushButton("删除")
            delete_btn.setProperty("row", row)
            delete_btn.setProperty("timer_id", timer["id"])
            delete_btn.setFixedHeight(24)
            delete_btn.setStyleSheet("""
                QPushButton {
                    background-color: #E74C3C;
                    color: white;
                    border: none;
                    border-radius: 3px;
                    padding: 2px 6px;
                    font-size: 11px;
                }
                QPushButton:hover {
                    background-color: #C0392B;
                }
            """)
            delete_btn.clicked.connect(self.delete_timer_clicked)
            
            # 设为默认按钮
            default_btn = QPushButton("默认")
            default_btn.setProperty("timer_id", timer["id"])
            default_btn.setProperty("minutes", timer["minutes"])
            default_btn.setFixedHeight(24)
            default_btn.setStyleSheet("""
                QPushButton {
                    background-color: #27AE60;
                    color: white;
                    border: none;
                    border-radius: 3px;
                    padding: 2px 6px;
                    font-size: 11px;
                }
                QPushButton:hover {
                    background-color: #2ECC71;
                }
            """)
            
            # 如果已经是默认的，禁用该按钮
            if timer["id"] == default_timer_id:
                default_btn.setEnabled(False)
                default_btn.setStyleSheet("""
                    QPushButton {
                        background-color: #555;
                        color: #AAA;
                        border: none;
                        border-radius: 3px;
                        padding: 2px 6px;
                        font-size: 11px;
                    }
                """)
                
            default_btn.clicked.connect(self.set_default_timer)
            
            actions_layout.addWidget(delete_btn)
            actions_layout.addWidget(default_btn)
            
            # 创建操作列
            action_item = self.timer_model.item(row, 2)
            if not action_item:
                action_item = QStandardItem("")
                self.timer_model.setItem(row, 2, action_item)
            
            # 设置操作列的自定义小部件
            self.timer_table.setIndexWidget(self.timer_model.index(row, 2), actions_widget)
        
        # 设置列宽
        self.timer_table.setColumnWidth(0, 40)
        self.timer_table.setColumnWidth(1, 60)

    def delete_timer_clicked(self):
        """处理删除按钮点击事件"""
        # 获取发送者
        sender = self.sender()
        row = sender.property("row")
        timer_id = sender.property("timer_id")
        
        # 创建确认对话框
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("确认删除")
        msg_box.setText(f"确认要删除ID为 {timer_id} 的计时器吗？")
        msg_box.setIcon(QMessageBox.Icon.Question)
        
        # 自定义按钮
        yes_button = msg_box.addButton("确定", QMessageBox.ButtonRole.YesRole)
        no_button = msg_box.addButton("取消", QMessageBox.ButtonRole.NoRole)
        
        # 设置默认按钮为"确定"
        msg_box.setDefaultButton(yes_button)
        
        # 添加按键事件过滤器
        key_filter = KeyEventFilter(msg_box, yes_button, no_button)
        msg_box.installEventFilter(key_filter)
        
        # 设置样式
        msg_box.setStyleSheet("""
            QMessageBox {
                background-color: #2D2D2D;
                color: white;
            }
            QPushButton {
                background-color: #7F8C8D;
                color: white;
                padding: 6px 12px;
                border-radius: 4px;
                font-weight: bold;
                min-width: 80px;
            }
            QPushButton:default {
                background-color: #3498DB;
            }
            QPushButton:hover {
                background-color: #95A5A6;
            }
            QPushButton:default:hover {
                background-color: #2980B9;
            }
            QPushButton:focus {
                border: 1px solid #E5E5E5;
            }
        """)
        
        # 显示对话框并获取用户选择
        msg_box.exec()
        
        # 判断用户选择
        if msg_box.clickedButton() == yes_button:
            self.delete_timer(timer_id)
    
    def delete_timer(self, timer_id):
        """删除计时器"""
        # 获取所有计时器
        settings = QSettings("MyApp", "KeyMouseTracker")
        timers = settings.value("timers", [])
        default_timer_id = settings.value("default_timer_id", -1, type=int)
        
        # 找到并移除计时器
        for i, timer in enumerate(timers):
            if timer["id"] == timer_id:
                # 如果要删除的是默认计时器，重置默认计时器设置
                if timer_id == default_timer_id:
                    settings.setValue("default_timer_id", -1)
                    settings.setValue("default_timer", 25)  # 恢复为25分钟默认值
                    
                    # 通知主窗口更新默认计时器
                    if self.parent:
                        self.parent.default_timer_minutes = 25
                        
                timers.pop(i)
                break
        
        # 保存更新后的计时器列表
        settings.setValue("timers", timers)
        
        # 更新表格
        self.load_timers()

    def set_default_timer(self):
        """设置默认计时器"""
        # 获取发送者
        sender = self.sender()
        timer_id = sender.property("timer_id")
        minutes = sender.property("minutes")
        
        # 保存默认计时器设置
        settings = QSettings("MyApp", "KeyMouseTracker")
        settings.setValue("default_timer_id", timer_id)
        settings.setValue("default_timer", minutes)
        
        # 通知主窗口更新默认计时器
        if self.parent:
            self.parent.default_timer_minutes = minutes
            
        # 更新表格以反映变化
        self.load_timers()

    def add_timer(self):
        """添加新计时器"""
        minutes, ok = QInputDialog.getInt(
            self, "添加计时器", "请输入分钟数:", 25, 1, 120, 1
        )
        
        if ok:
            # 获取所有计时器
            settings = QSettings("MyApp", "KeyMouseTracker")
            timers = settings.value("timers", [])
            
            # 生成新ID
            new_id = 1
            if timers:
                new_id = max(timer["id"] for timer in timers) + 1
            
            # 添加新计时器
            timers.append({
                "id": new_id,
                "minutes": minutes,
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M")
            })
            
            # 保存更新后的计时器列表
            settings.setValue("timers", timers)
            
            # 如果没有默认计时器，将此设为默认
            if settings.value("default_timer_id", -1) == -1:
                settings.setValue("default_timer_id", new_id)
                settings.setValue("default_timer", minutes)
                
                # 通知主窗口更新默认计时器
                if self.parent:
                    self.parent.default_timer_minutes = minutes
            
            # 更新表格
            self.load_timers()
            
    def on_dialog_closed(self):
        """对话框关闭时的处理"""
        # 确保所有设置已保存
        opacity = self.opacity_slider.value() / 100
        self.parent.save_settings(opacity=opacity)

    def export_today_data(self):
        """转发到主窗口的导出方法"""
        if self.parent and hasattr(self.parent, 'export_today_data'):
            self.parent.export_today_data()
        else:
            QMessageBox.warning(self, "导出失败", "无法访问主窗口导出功能")
    
    def copy_today_data(self):
        """直接复制今日数据到剪贴板"""
        try:
            # 检查是否有父窗口和数据库连接
            if not self.parent or not hasattr(self.parent, 'event_service'):
                QMessageBox.warning(self, "复制失败", "无法访问数据库")
                return
                
            # 使用新方法获取今日聚合数据
            today_data = self.parent.event_service.get_today_aggregated_data('15min', 96)
            
            print(f"找到 {len(today_data)} 条今日记录")
            
            if not today_data:
                QMessageBox.information(self, "复制提示", "今日暂无活动记录")
                return
                
            # 直接调用主窗口的剪贴板复制功能
            if hasattr(self.parent, '_copy_to_clipboard'):
                self.parent._copy_to_clipboard(today_data)  # 传递已筛选的今日数据
            else:
                QMessageBox.warning(self, "复制失败", "剪贴板功能不可用")
                
        except Exception as e:
            print(f"复制到剪贴板时出错: {str(e)}")
            QMessageBox.warning(self, "复制失败", f"复制到剪贴板时出错: {str(e)}")
    
    def load_today_summary(self):
        """加载今日数据摘要"""
        try:
            # 检查是否有父窗口和数据库连接
            if not self.parent or not hasattr(self.parent, 'event_service'):
                self.data_summary.setText("今日数据: 无法加载")
                return
            
            # 获取今天的日期
            today = datetime.now().strftime("%Y-%m-%d")
            
            # 获取今日聚合数据
            data = self.parent.event_service.get_aggregated_data('15min', 96)  # 获取96条记录(最多24小时)
            
            # 筛选今天的数据
            today_data = [item for item in data if item['period'].startswith(today)]
            
            if not today_data:
                # 尝试手动触发一次聚合计算后稍后再尝试
                self.parent.event_service.calculate_aggregates()
                
                # 使用QTimer延迟1秒后再次尝试加载
                QTimer.singleShot(1000, self._retry_load_today_summary)
                return
                
            # 计算总计
            total_keyboard = sum(item['keyboard'] for item in today_data)
            total_mouse = sum(item['mouse'] for item in today_data)
            total_score = sum(item['score'] for item in today_data)
            active_periods = len(today_data)
            
            # 找出最活跃的时段
            most_active = max(today_data, key=lambda x: x['score'])
            most_active_time = most_active['period'].split(' ')[1]  # 只取时间部分
            
            # 更新显示
            self.data_summary.setText(
                f"<b>今日数据统计</b>\n"
                f"• 键盘点击: <span style='color:#3498db;'>{total_keyboard}</span> 次\n"
                f"• 鼠标点击: <span style='color:#e67e22;'>{total_mouse}</span> 次\n"
                f"• 活动总分: <span style='color:#1abc9c;'>{total_score}</span>\n"
                f"• 活动时段: {active_periods} 个 (约 {active_periods*15} 分钟)\n"
                f"• 最活跃时段: <span style='color:#f1c40f;'>{most_active_time}</span> "
                f"(键盘:{most_active['keyboard']}, 鼠标:{most_active['mouse']})"
            )
            
        except Exception as e:
            print(f"加载今日数据摘要时出错: {str(e)}")
            self.data_summary.setText(f"今日数据: 加载错误 ({str(e)})")
    
    def _retry_load_today_summary(self):
        """在聚合操作完成后重试加载今日数据"""
        try:
            # 获取今天的日期
            today = datetime.now().strftime("%Y-%m-%d")
            
            # 获取今日聚合数据
            data = self.parent.event_service.get_aggregated_data('15min', 96)
            
            # 筛选今天的数据
            today_data = [item for item in data if item['period'].startswith(today)]
            
            if not today_data:
                self.data_summary.setText("今日数据: 暂无记录")
                return
                
            # 计算总计
            total_keyboard = sum(item['keyboard'] for item in today_data)
            total_mouse = sum(item['mouse'] for item in today_data)
            total_score = sum(item['score'] for item in today_data)
            active_periods = len(today_data)
            
            # 找出最活跃的时段
            most_active = max(today_data, key=lambda x: x['score'])
            most_active_time = most_active['period'].split(' ')[1]  # 只取时间部分
            
            # 更新显示
            self.data_summary.setText(
                f"<b>今日数据统计</b>\n"
                f"• 键盘点击: <span style='color:#3498db;'>{total_keyboard}</span> 次\n"
                f"• 鼠标点击: <span style='color:#e67e22;'>{total_mouse}</span> 次\n"
                f"• 活动总分: <span style='color:#1abc9c;'>{total_score}</span>\n"
                f"• 活动时段: {active_periods} 个 (约 {active_periods*15} 分钟)\n"
                f"• 最活跃时段: <span style='color:#f1c40f;'>{most_active_time}</span> "
                f"(键盘:{most_active['keyboard']}, 鼠标:{most_active['mouse']})"
            )
        except Exception as e:
            print(f"重试加载今日数据摘要时出错: {str(e)}")
            self.data_summary.setText("今日数据: 重试加载失败")

if __name__ == "__main__":
    try:
        app = QApplication(sys.argv)
        window = MainWindow()
        window.show()
        sys.exit(app.exec())
    except Exception as e:
        print(f"程序出错: {str(e)}")
        import traceback
        traceback.print_exc()