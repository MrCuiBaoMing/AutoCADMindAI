#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI CAD Plugin for AutoCAD
集成AI大模型控制AutoCAD的插件
"""

import sys
import os
import json
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QTextEdit, QLineEdit, QPushButton,
    QVBoxLayout, QHBoxLayout, QWidget, QSplitter, QTreeWidget,
    QTreeWidgetItem, QLabel, QStatusBar, QComboBox, QMessageBox, QDialog
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QByteArray, QUrl
from PyQt6.QtGui import QTextCursor, QColor
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply

from autocad_controller import AutoCADController
from config_manager import ConfigManager
from ai_model import get_ai_model
from ui.settings_window import SettingsWindow

class StatusIndicator(QWidget):
    """状态指示器控件"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(16, 16)
        self.status = "disconnected"  # connected, disconnected, processing
        self.animation_angle = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.animate)
        
    def set_status(self, status):
        """设置状态"""
        self.status = status
        if status == "processing":
            self.timer.start(50)
        else:
            self.timer.stop()
            self.animation_angle = 0
        self.update()
        
    def animate(self):
        """动画效果"""
        self.animation_angle = (self.animation_angle + 10) % 360
        self.update()
        
    def paintEvent(self, event):
        """绘制状态指示器"""
        from PyQt6.QtGui import QPainter, QPen, QBrush, QRadialGradient
        
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        if self.status == "connected":
            # 绿色 - 已连接
            gradient = QRadialGradient(8, 8, 8)
            gradient.setColorAt(0, QColor(100, 255, 100))
            gradient.setColorAt(1, QColor(50, 200, 50))
            painter.setBrush(QBrush(gradient))
            painter.setPen(QPen(QColor(30, 150, 30), 1))
            painter.drawEllipse(2, 2, 12, 12)
            
        elif self.status == "processing":
            # 蓝色旋转 - 处理中
            painter.setPen(QPen(QColor(30, 144, 255), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.translate(8, 8)
            painter.rotate(self.animation_angle)
            painter.drawArc(-6, -6, 12, 12, 0, 270 * 16)
            
        else:
            # 红色 - 未连接
            gradient = QRadialGradient(8, 8, 8)
            gradient.setColorAt(0, QColor(255, 100, 100))
            gradient.setColorAt(1, QColor(200, 50, 50))
            painter.setBrush(QBrush(gradient))
            painter.setPen(QPen(QColor(150, 30, 30), 1))
            painter.drawEllipse(2, 2, 12, 12)

class AICADPlugin(QMainWindow):
    """AI CAD插件主窗口"""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AI CAD - AutoCAD智能助手")
        self.setGeometry(100, 100, 1000, 700)
        
        # 设置窗口属性：置顶 + 无边框 + 透明
        self.set_window_properties()
        
        # 初始化控制器
        self.acad = AutoCADController()
        self.config = ConfigManager()
        
        self.is_processing = False
        self.ai_thread = None
        self._user_requested_stop = False  # 用户点击停止后忽略后续AI结果
        self._ignore_ai_result = False  # 停止后丢弃本轮（延迟返回）的AI结果，直到下一次发送
        self._current_reply = None  # 当前异步 HTTP 请求，用于中止
        self._network_manager = QNetworkAccessManager(self)
        # CAD 命令队列：用 QTimer 间隔执行，避免主线程长时间阻塞，便于点击停止
        self._cad_command_queue = []
        self._cad_timer = QTimer(self)
        self._cad_timer.setSingleShot(True)
        self._cad_timer.timeout.connect(self._execute_next_cad_command)
        self._cad_worker = None  # 当前执行 CAD 命令的工作线程，点停止时对其 stop()
        self._cad_executor = None  # 记录最近一次发送CAD命令的控制器（主控制器或worker控制器）
        self._cad_execution_active = False  # 当前是否确实处于CAD命令执行阶段
        # 对话历史，用于多轮上下文（仅保留最近 N 条，避免 token 过多）
        self._chat_history = []
        self._chat_history_max = 20
        self._last_user_input = ""  # 最近一次用户输入，用于判定是否应执行CAD命令
        self._ignore_ai_result = False  # 停止后忽略迟到结果
        self._request_seq = 0  # 递增请求序号
        self._active_request_id = 0  # 当前有效请求ID（仅此ID可触发执行）

        # 初始化UI
        self.init_ui()
        
        # 连接AutoCAD
        self.connect_to_acad()
        
        # 初始化AI模型
        self.ai_model = None
        self.init_ai_model()
        
        # 更新状态栏
        self.update_status_bar("就绪 - 输入指令控制AutoCAD")
    
    def set_window_properties(self):
        """设置窗口属性：置顶、无边框、透明"""
        # 设置窗口置顶
        self.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint |  # 始终置顶
            Qt.WindowType.FramelessWindowHint     # 无边框
        )
        
        # 设置窗口透明
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        # 设置窗口透明度（0.0-1.0，1.0为不透明）
        self.setWindowOpacity(0.98)
        
        # 允许鼠标穿透（当窗口透明时）
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        
        # 保存正常大小和位置
        self.normal_geometry = self.geometry()
        self.is_maximized = False
    
    def mousePressEvent(self, event):
        """鼠标按下事件 - 用于拖动窗口"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
    
    def mouseMoveEvent(self, event):
        """鼠标移动事件 - 用于拖动窗口"""
        if event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()
    
    def toggle_maximize(self):
        """切换最大化/还原"""
        if self.is_maximized:
            # 还原窗口
            self.setGeometry(self.normal_geometry)
            self.max_button.setText("□")
            self.is_maximized = False
        else:
            # 保存当前大小和位置
            self.normal_geometry = self.geometry()
            # 最大化窗口
            screen = QApplication.primaryScreen().availableGeometry()
            self.setGeometry(screen)
            self.max_button.setText("❐")
            self.is_maximized = True
    
    def mouseDoubleClickEvent(self, event):
        """双击标题栏最大化/还原"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.toggle_maximize()
    
    def connect_to_acad(self):
        """连接到AutoCAD"""
        try:
            self.status_indicator.set_status("processing")
            self.status_label.setText("连接中...")
            self.update_status_bar("正在连接AutoCAD...")
            QApplication.processEvents()
            
            success = self.acad.connect()
            if success and self.acad.is_connected:
                try:
                    version = self.acad.acad_app.Version if self.acad.acad_app else "未知版本"
                    self.status_indicator.set_status("connected")
                    self.status_label.setText(f"已连接 {version}")
                    self.update_status_bar(f"✓ 已连接到AutoCAD {version}")
                except:
                    self.status_indicator.set_status("connected")
                    self.status_label.setText("已连接")
                    self.update_status_bar("✓ 已连接到AutoCAD")
            else:
                self.status_indicator.set_status("disconnected")
                self.status_label.setText("未连接")
                self.update_status_bar("✗ 未连接到AutoCAD，请先启动AutoCAD")
        except Exception as e:
            self.status_indicator.set_status("disconnected")
            self.status_label.setText("连接失败")
            self.update_status_bar(f"✗ 连接失败: {str(e)}")
    
    def init_ai_model(self):
        """初始化AI模型"""
        try:
            # 加载配置的模型
            self.load_models()
            
            # 初始化当前选中的模型
            if self.models and len(self.models) > 0:
                self.current_model_config = self.models[0]
                self.ai_model = get_ai_model(
                    self.current_model_config.model_type,
                    api_key=self.current_model_config.api_key,
                    endpoint=self.current_model_config.endpoint,
                    deployment=self.current_model_config.model_name
                )
                self.update_status_bar(f"AI模型初始化完成: {self.current_model_config.name}")
            else:
                self.ai_model = get_ai_model("local")
                self.update_status_bar("使用本地模型（未配置其他模型）")
        except Exception as e:
            self.ai_model = get_ai_model("local")
            self.update_status_bar(f"AI模型初始化失败，使用本地模型: {str(e)}")
    
    def load_models(self):
        """加载配置的模型"""
        try:
            # 直接从配置文件加载
            import json
            import os
            
            config_file = os.path.join(os.path.dirname(__file__), "ai_config.json")
            if os.path.exists(config_file):
                with open(config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                
                # 创建模型配置对象
                from ui.settings_window import ModelConfig
                self.models = [ModelConfig.from_dict(m) for m in config.get("models", [])]
                
                # 更新模型选择下拉框
                self.model_combo.clear()
                for model in self.models:
                    self.model_combo.addItem(model.name)
                
                if len(self.models) > 0:
                    self.model_combo.setCurrentIndex(0)
            else:
                self.models = []
        except Exception as e:
            print(f"加载模型配置失败: {e}")
            self.models = []
    
    def open_settings(self):
        """打开设置窗口"""
        try:
            settings = SettingsWindow(self)
            if settings.exec() == QDialog.DialogCode.Accepted:
                # 重新加载模型配置
                self.load_models()
                # 重新初始化AI模型
                self.init_ai_model()
        except Exception as e:
            QMessageBox.critical(self, "错误", f"打开设置窗口失败: {str(e)}")
    
    def on_model_changed(self, index):
        """模型切换事件"""
        if index >= 0 and index < len(self.models):
            self.current_model_config = self.models[index]
            
            try:
                self.ai_model = get_ai_model(
                    self.current_model_config.model_type,
                    api_key=self.current_model_config.api_key,
                    endpoint=self.current_model_config.endpoint,
                    deployment=self.current_model_config.model_name
                )
                self.update_status_bar(f"已切换到模型: {self.current_model_config.name}")
                self.add_chat_message("系统", f"已切换到模型: {self.current_model_config.name}")
            except Exception as e:
                self.update_status_bar(f"模型切换失败: {str(e)}")
                self.add_chat_message("系统", f"模型切换失败: {str(e)}")
    
    def init_ui(self):
        """初始化UI"""
        # 主布局
        central_widget = QWidget()
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(10)
        
        # 标题栏（用于拖动窗口）
        title_layout = QHBoxLayout()
        title_label = QLabel("🤖 AI CAD 助手")
        title_label.setStyleSheet("font-weight: bold; font-size: 16px; color: #2c3e50;")
        
        # 状态指示器
        self.status_indicator = StatusIndicator()
        self.status_label = QLabel("未连接")
        self.status_label.setStyleSheet("font-size: 12px; color: #7f8c8d;")
        
        # 最小化按钮
        min_button = QPushButton("—")
        min_button.setFixedSize(35, 28)
        min_button.setStyleSheet("""
            QPushButton {
                background-color: #3498db;
                color: white;
                border: none;
                border-radius: 4px;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #2980b9;
            }
        """)
        min_button.clicked.connect(self.showMinimized)
        
        # 最大化按钮
        self.max_button = QPushButton("□")
        self.max_button.setFixedSize(35, 28)
        self.max_button.setStyleSheet("""
            QPushButton {
                background-color: #9b59b6;
                color: white;
                border: none;
                border-radius: 4px;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #8e44ad;
            }
        """)
        self.max_button.clicked.connect(self.toggle_maximize)
        
        # 关闭按钮
        close_button = QPushButton("×")
        close_button.setFixedSize(35, 28)
        close_button.setStyleSheet("""
            QPushButton {
                background-color: #e74c3c;
                color: white;
                border: none;
                border-radius: 4px;
                font-size: 16px;
            }
            QPushButton:hover {
                background-color: #c0392b;
            }
        """)
        close_button.clicked.connect(self.close)
        
        title_layout.addWidget(title_label)
        title_layout.addSpacing(10)
        title_layout.addWidget(self.status_indicator)
        title_layout.addWidget(self.status_label)
        title_layout.addStretch()
        title_layout.addWidget(min_button)
        title_layout.addWidget(self.max_button)
        title_layout.addWidget(close_button)
        
        # 顶部控制栏
        control_layout = QHBoxLayout()
        
        # 模型选择
        model_label = QLabel("🧠 AI模型:")
        model_label.setStyleSheet("font-size: 13px; color: #34495e;")
        self.model_combo = QComboBox()
        self.model_combo.currentIndexChanged.connect(self.on_model_changed)
        self.model_combo.setMinimumWidth(180)
        
        # 设置按钮
        settings_button = QPushButton("⚙ 设置")
        settings_button.clicked.connect(self.open_settings)
        
        # 连接按钮
        self.connect_button = QPushButton("🔗 连接AutoCAD")
        self.connect_button.clicked.connect(self.connect_to_acad)
        
        control_layout.addWidget(model_label)
        control_layout.addWidget(self.model_combo)
        control_layout.addWidget(settings_button)
        control_layout.addStretch()
        control_layout.addWidget(self.connect_button)
        
        # 添加标题栏和控制栏到主布局
        main_layout.addLayout(title_layout)
        main_layout.addLayout(control_layout)
        
        # 中间分割器
        splitter = QSplitter(Qt.Orientation.Vertical)
        
        # 聊天区域
        chat_widget = QWidget()
        chat_layout = QVBoxLayout(chat_widget)
        chat_layout.setContentsMargins(0, 0, 0, 0)
        
        self.chat_display = QTextEdit()
        self.chat_display.setReadOnly(True)
        self.chat_display.setPlaceholderText("💬 开始与AI助手对话...")
        
        input_layout = QHBoxLayout()
        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("输入指令，例如：绘制一个圆形，半径10")
        self.input_field.returnPressed.connect(self.send_command)
        
        self.send_button = QPushButton("发送 ➤")
        self.send_button.clicked.connect(self.on_send_button_clicked)
        self.send_button.setFixedWidth(80)
        
        input_layout.addWidget(self.input_field)
        input_layout.addWidget(self.send_button)
        
        chat_layout.addWidget(self.chat_display)
        chat_layout.addLayout(input_layout)
        
        # 命令历史和功能树
        bottom_widget = QWidget()
        bottom_layout = QHBoxLayout(bottom_widget)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        
        # 命令历史
        history_widget = QWidget()
        history_layout = QVBoxLayout(history_widget)
        history_layout.setContentsMargins(0, 0, 0, 0)
        history_label = QLabel("📋 命令历史")
        history_label.setStyleSheet("font-weight: bold; font-size: 13px; color: #34495e;")
        self.history_display = QTextEdit()
        self.history_display.setReadOnly(True)
        history_layout.addWidget(history_label)
        history_layout.addWidget(self.history_display)
        
        # 功能树
        function_widget = QWidget()
        function_layout = QVBoxLayout(function_widget)
        function_layout.setContentsMargins(0, 0, 0, 0)
        function_label = QLabel("⚡ 快捷功能")
        function_label.setStyleSheet("font-weight: bold; font-size: 13px; color: #34495e;")
        self.function_tree = QTreeWidget()
        self.function_tree.setHeaderLabels(["功能", "描述"])
        self.add_function_nodes()
        self.function_tree.itemDoubleClicked.connect(self.execute_function)
        
        function_layout.addWidget(function_label)
        function_layout.addWidget(self.function_tree)
        
        bottom_layout.addWidget(history_widget, 1)
        bottom_layout.addWidget(function_widget, 1)
        
        splitter.addWidget(chat_widget)
        splitter.addWidget(bottom_widget)
        splitter.setSizes([400, 300])
        
        # 状态栏
        self.statusBarWidget = QStatusBar()
        self.setStatusBar(self.statusBarWidget)
        
        main_layout.addWidget(splitter)
        
        self.setCentralWidget(central_widget)
        
        # 设置现代化窗口样式
        self.setStyleSheet("""
            QMainWindow {
                background-color: #f5f6fa;
                border: 2px solid #dcdde1;
                border-radius: 15px;
            }
            QWidget {
                background-color: #ffffff;
                border-radius: 8px;
            }
            QTextEdit {
                background-color: #ffffff;
                border: 2px solid #dcdde1;
                border-radius: 8px;
                padding: 8px;
                font-size: 13px;
                color: #2c3e50;
            }
            QTextEdit:focus {
                border: 2px solid #3498db;
            }
            QLineEdit {
                background-color: #ffffff;
                border: 2px solid #dcdde1;
                border-radius: 8px;
                padding: 10px;
                font-size: 13px;
                color: #2c3e50;
            }
            QLineEdit:focus {
                border: 2px solid #3498db;
            }
            QPushButton {
                background-color: #3498db;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 8px 16px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2980b9;
            }
            QPushButton:pressed {
                background-color: #1f6dad;
            }
            QComboBox {
                background-color: #ffffff;
                border: 2px solid #dcdde1;
                border-radius: 8px;
                padding: 8px;
                font-size: 13px;
                color: #2c3e50;
            }
            QComboBox:focus {
                border: 2px solid #3498db;
            }
            QComboBox::drop-down {
                border: none;
                width: 30px;
            }
            QComboBox::down-arrow {
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 8px solid #3498db;
                margin-right: 10px;
            }
            QTreeWidget {
                background-color: #ffffff;
                border: 2px solid #dcdde1;
                border-radius: 8px;
                font-size: 12px;
                color: #2c3e50;
            }
            QTreeWidget::item {
                padding: 5px;
                border-radius: 4px;
            }
            QTreeWidget::item:selected {
                background-color: #3498db;
                color: white;
            }
            QTreeWidget::item:hover {
                background-color: #ecf0f1;
            }
            QStatusBar {
                background-color: #2c3e50;
                color: #ecf0f1;
                border-radius: 0px;
                font-size: 12px;
                padding: 5px;
            }
            QSplitter::handle {
                background-color: #dcdde1;
                height: 3px;
            }
        """)
    
    def add_function_nodes(self):
        """添加功能节点到树"""
        # 常用命令
        common_item = QTreeWidgetItem(["常用命令", "AutoCAD基本操作"])
        common_functions = [
            ("绘制直线", "LINE"),
            ("绘制圆形", "CIRCLE"),
            ("绘制矩形", "RECTANG"),
            ("移动对象", "MOVE"),
            ("复制对象", "COPY"),
            ("删除对象", "ERASE")
        ]
        for name, cmd in common_functions:
            item = QTreeWidgetItem([name, cmd])
            common_item.addChild(item)
        self.function_tree.addTopLevelItem(common_item)
        
        # 中线CAD功能
        zxcad_item = QTreeWidgetItem(["中线CAD", "线束设计功能"])
        zxcad_functions = [
            ("调取连接器", "ZXCAD-TK"),
            ("填写回路号", "ZXCAD-HTHZ"),
            ("节点标注", "ZXCAD-JDCD"),
            ("导出BOM", "ZXCAD-XBOM")
        ]
        for name, cmd in zxcad_functions:
            item = QTreeWidgetItem([name, cmd])
            zxcad_item.addChild(item)
        self.function_tree.addTopLevelItem(zxcad_item)
        
        # 展开所有节点
        self.function_tree.expandAll()
    
    def on_send_button_clicked(self):
        """发送/停止按钮点击"""
        if self.is_processing:
            self.stop_processing()
        else:
            self.send_command()
    
    def send_command(self):
        """发送命令到AI和AutoCAD"""
        command = self.input_field.text().strip()
        if not command:
            return

        self._last_user_input = command
        self._ignore_ai_result = False  # 新请求开始，允许接收本轮AI结果
        self._request_seq += 1
        self._active_request_id = self._request_seq
        self.add_chat_message("用户", command)
        self.input_field.clear()

        if command.startswith("/"):
            self.execute_direct_command(command[1:])
        else:
            self.process_with_ai(command, request_id=self._active_request_id)
    
    def stop_processing(self):
        """停止当前处理：1) 终止AI对话或中止网络请求 2) 取消CAD当前命令"""
        import time

        self._user_requested_stop = True
        self._ignore_ai_result = True  # 停止后彻底丢弃本轮任何迟到结果
        self._active_request_id = self._request_seq + 1  # 失效当前及更早请求结果，防串台
        self.add_chat_message("系统", "⏹ 正在停止...")

        # 1a. 若有正在进行的异步 HTTP 请求，直接中止（不阻塞界面）
        if self._current_reply is not None:
            try:
                self._current_reply.abort()
            except Exception:
                pass
            self._current_reply = None

        # 1b. 若有正在执行的 CAD 工作线程，先请求停止
        self._cad_command_queue.clear()
        self._cad_timer.stop()
        if self._cad_worker is not None and self._cad_worker.isRunning():
            self._cad_worker.stop()

        # 1c. 若为线程方式（本地模型），请求工作线程停止
        if self.ai_thread and self.ai_thread.isRunning():
            self.ai_thread.stop()
            self.ai_thread.wait(1000)

        # 2. 仅当“当前确有CAD命令执行”时才发送取消，避免对纯对话误发控制指令
        cancelled = True
        should_cancel_cad = self._cad_execution_active or (self._cad_worker is not None and self._cad_worker.isRunning())
        if should_cancel_cad:
            target_acad = self._cad_executor if self._cad_executor is not None else self.acad
            cancelled = target_acad.force_cancel_command(rounds=10, interval=0.08)
            # 同时对主控制器再补一次取消，覆盖跨线程/句柄切换场景
            if target_acad is not self.acad:
                cancelled = self.acad.force_cancel_command(rounds=4, interval=0.06) or cancelled

            if not cancelled:
                self.add_chat_message("系统", "⚠ 未确认CAD已响应取消，建议手动按一次 ESC")
        # 3. 统一收尾
        self._cad_finish(was_stopped=True)
        self.is_processing = False
        self.set_send_button_state(False)
        self.add_chat_message("系统", "✓ 已停止（已请求取消CAD当前命令）")
        self.reset_status()
    
    def set_send_button_state(self, is_processing: bool):
        """设置发送按钮状态：处理中显示红色方形停止按钮"""
        if is_processing:
            self.send_button.setText("■ 停止")
            self.send_button.setFixedSize(80, 36)
            self.send_button.setStyleSheet("""
                QPushButton {
                    background-color: #e74c3c;
                    color: white;
                    border: none;
                    border-radius: 8px;
                    font-size: 13px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #c0392b;
                }
            """)
        else:
            self.send_button.setText("发送 ➤")
            self.send_button.setFixedWidth(80)
            self.send_button.setStyleSheet("")
        self.input_field.setEnabled(not is_processing)
    
    def add_chat_message(self, sender, message):
        """添加聊天消息"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.chat_display.append(f"[{timestamp}] {sender}: {message}")
        self.chat_display.moveCursor(QTextCursor.MoveOperation.End)
    
    def process_with_ai(self, command, request_id=None):
        """使用AI处理命令（异步网络请求，不阻塞界面）"""
        try:
            # 每次新请求前重置“用户已停止”标记，避免上次点停止导致本次响应被丢弃
            self._user_requested_stop = False

            self.is_processing = True
            self.set_send_button_state(True)

            self.status_indicator.set_status("processing")
            self.status_label.setText("AI处理中...")
            self.update_status_bar("⏳ AI正在思考，请稍候...")
            self.add_chat_message("系统", "⏳ 正在处理您的请求...")

            self._pending_user_message = command  # 用于收到回复后只追加 assistant 到历史
            # 发送时就把用户消息写入历史，这样即使用户点停止，下一轮“请继续”仍有上下文
            self._chat_history.append({"role": "user", "content": command})
            if len(self._chat_history) > self._chat_history_max:
                self._chat_history = self._chat_history[-self._chat_history_max:]

            params = getattr(self.ai_model, "get_request_params", None)
            if callable(params):
                req = self.ai_model.get_request_params(command, None, self._chat_history)
                if req is not None:
                    url, headers, body = req
                    request = QNetworkRequest(QUrl(url))
                    for k, v in (headers or {}).items():
                        request.setRawHeader(k.encode("utf-8"), v.encode("utf-8"))
                    self._current_reply = self._network_manager.post(request, QByteArray(body))
                    self._current_reply.setProperty("request_id", int(request_id or self._active_request_id))
                    self._current_reply.finished.connect(self._on_ai_network_finished)
                    return
            # 本地模型等无 get_request_params：仍用线程（本地逻辑很快，几乎不阻塞）
            self.ai_thread = AIProcessingThread(self.ai_model, command, self._chat_history)
            self.ai_thread.request_id = int(request_id or self._active_request_id)
            self.ai_thread.result_ready.connect(self.on_ai_result)
            self.ai_thread.finished.connect(self.on_ai_finished)
            self.ai_thread.start()

        except Exception as e:
            self.is_processing = False
            self.set_send_button_state(False)
            self.add_chat_message("系统", f"❌ 处理失败: {str(e)}")
            self.update_status_bar("❌ 处理失败")
            self.reset_status()

    def _on_ai_network_finished(self):
        """异步 AI 请求完成（主线程事件循环回调，界面不卡）"""
        reply = self.sender()
        if not isinstance(reply, QNetworkReply):
            return
        try:
            request_id = int(reply.property("request_id") or 0)
            reply.deleteLater()
            self._current_reply = None
            if self._user_requested_stop or self._ignore_ai_result:
                return
            if request_id != self._active_request_id:
                return
            if reply.error() != QNetworkReply.NetworkError.NoError:
                err_msg = reply.errorString() or "网络错误"
                self.on_ai_result({"response": err_msg, "commands": [], "request_id": request_id})
                return
            data = reply.readAll().data()
            result = self.ai_model.parse_response(data)
            if isinstance(result, dict):
                result["request_id"] = request_id
            self.on_ai_result(result)
        except Exception as e:
            if not self._user_requested_stop:
                self.on_ai_result({"response": f"处理响应失败: {str(e)}", "commands": [], "request_id": self._active_request_id})
    
    def on_ai_finished(self):
        """AI 线程结束（此时可能仍在执行 CAD 命令，不在这里恢复按钮）"""
        self.input_field.setFocus()
    
    def reset_status(self):
        """重置状态"""
        if self.acad.is_connected:
            self.status_indicator.set_status("connected")
            self.status_label.setText("已连接")
        else:
            self.status_indicator.set_status("disconnected")
            self.status_label.setText("未连接")

    def _is_operation_intent(self, text: str) -> bool:
        """判断用户输入是否包含“执行CAD操作”意图。"""
        t = (text or "").strip().lower()
        if not t:
            return False

        # 问句/咨询默认走对话模式，不自动执行CAD命令
        chat_markers = ["？", "?", "怎么", "如何", "为什么", "是什么", "教程", "解释", "介绍", "能否", "可以吗", "请问"]
        if any(m in t for m in chat_markers):
            return False

        # 明确操作意图关键词
        op_markers = [
            "画", "绘制", "创建", "新建", "生成", "插入", "删除", "移动", "复制", "旋转", "镜像", "偏移", "修剪", "延伸", "标注", "执行", "运行", "命令"
        ]
        if any(m in t for m in op_markers):
            return True

        # 直接输入CAD命令也算操作意图
        direct_cmds = ["line", "circle", "rectang", "move", "copy", "erase", "trim", "extend", "offset", "rotate", "mirror", "dimlinear"]
        return any(cmd in t for cmd in direct_cmds)
    
    def on_ai_result(self, result):
        """处理AI结果；若用户已点击停止或结果已过期则不再处理"""
        commands = result.get('commands', [])
        try:
            result_request_id = int(result.get('request_id', self._active_request_id)) if isinstance(result, dict) else self._active_request_id
            if self._user_requested_stop or self._ignore_ai_result:
                return
            if result_request_id != self._active_request_id:
                return

            response_text = result.get('response', '')
            intent = result.get('intent', 'chat')
            self.add_chat_message("AI", response_text)

            # 仅追加 AI 回复到对话历史（用户消息已在发送时写入，避免点停止后丢失上下文）
            self._chat_history.append({"role": "assistant", "content": response_text})
            if len(self._chat_history) > self._chat_history_max:
                self._chat_history = self._chat_history[-self._chat_history_max:]
            self._pending_user_message = None

            # 关键：仅当大模型明确返回 intent=command 时才执行
            if intent == 'command' and commands:
                self.add_chat_message("系统", f"🔧 准备执行命令: {', '.join(commands)}")
                self.update_status_bar("🔧 正在执行AutoCAD命令...（可随时点停止）")
                self._cad_execution_active = True
                self._cad_command_queue.clear()
                self._cad_timer.stop()
                if self._cad_worker and self._cad_worker.isRunning():
                    self._cad_worker.stop()
                self._cad_worker = CADWorkerThread(list(commands))
                self._cad_worker.controller_ready.connect(self._on_cad_worker_controller_ready)
                self._cad_worker.done.connect(self._on_cad_worker_done)
                self._cad_worker.start()
                return

            if commands and intent != 'command':
                self.add_chat_message("系统", "💬 大模型判定为对话，已阻止命令执行")

            self.update_status_bar("✓ 处理完成")
        except Exception as e:
            self.add_chat_message("系统", f"❌ 处理AI结果时出错: {str(e)}")
            self.update_status_bar("❌ 处理出错")
        finally:
            intent = result.get('intent', 'chat') if isinstance(result, dict) else 'chat'
            if (not commands) or (intent != 'command'):
                self._cad_execution_active = False
                self._user_requested_stop = False
                self.is_processing = False
                self.set_send_button_state(False)
                self.reset_status()

    def _execute_next_cad_command(self):
        """（已改用 CADWorkerThread，此处仅作兼容保留）"""
        self._cad_finish()

    def _on_cad_worker_controller_ready(self, controller):
        """收到 CAD 工作线程实际使用的控制器，停止时优先对它发送取消。"""
        self._cad_executor = controller

    def _on_cad_worker_done(self, stopped: bool):
        """CAD 工作线程结束（全部执行完或被用户停止）"""
        self._cad_worker = None
        self._cad_executor = None
        self._cad_finish(was_stopped=stopped)

    def _cad_finish(self, was_stopped=None):
        """CAD 命令执行完毕或用户停止后的收尾。was_stopped 为 True 表示用户点击了停止。"""
        if was_stopped is None:
            was_stopped = self._user_requested_stop
        if self.is_processing and not was_stopped:
            self.add_chat_message("系统", "✓ 命令执行完成")
        self._cad_command_queue.clear()
        self._cad_timer.stop()
        self._cad_worker = None
        self._cad_execution_active = False
        self._user_requested_stop = False
        self.is_processing = False
        self.set_send_button_state(False)
        self.reset_status()
        if not was_stopped:
            self.update_status_bar("✓ 处理完成")
    
    def execute_direct_command(self, command):
        """执行直接命令"""
        try:
            self.execute_autocad_command(command)
            self.add_chat_message("系统", f"执行命令: {command}")
        except Exception as e:
            self.add_chat_message("系统", f"命令执行失败: {str(e)}")
    
    def execute_function(self, item, column):
        """执行功能节点"""
        command = item.text(1)
        if command:
            self.execute_autocad_command(command)
            self.add_chat_message("系统", f"执行功能: {item.text(0)}")
    
    def execute_autocad_command(self, command, delay=0.5):
        """执行AutoCAD命令；delay 为发送后等待时间（秒），队列执行时用较短 delay 便于响应停止"""
        try:
            if not self.acad.is_connected:
                self.connect_to_acad()

            if self.acad.is_connected:
                # 显示执行中状态
                self.update_status_bar(f"正在执行命令: {command}")

                # 执行命令
                result = self.acad.send_command(command, delay=delay)
                
                # 记录命令历史
                self.add_history_command(command, result)

                # 仅在有实质内容时显示（不刷“命令执行结果: True”）
                if result is not None and result is not True and result is not False:
                    self.add_chat_message("系统", f"命令执行结果: {result}")

                self.update_status_bar(f"命令执行成功: {command}")
            else:
                error_msg = "未连接到AutoCAD，请先连接"
                self.add_chat_message("系统", error_msg)
                self.update_status_bar(error_msg)
        except Exception as e:
            import traceback
            error_msg = f"命令执行失败: {str(e)}"
            self.add_chat_message("系统", error_msg)
            self.update_status_bar(error_msg)
            # 打印详细的错误信息用于调试
            print(f"执行命令错误详情: {traceback.format_exc()}")
    
    def add_history_command(self, command, result):
        """添加命令到历史"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.history_display.append(f"[{timestamp}] {command}")
        if result:
            self.history_display.append(f"结果: {result}")
        self.history_display.append("-")
        self.history_display.moveCursor(QTextCursor.MoveOperation.End)
    
    def update_status_bar(self, message):
        """更新状态栏"""
        self.statusBarWidget.showMessage(message)
    
    def closeEvent(self, event):
        """关闭事件"""
        if self.acad.is_connected:
            reply = QMessageBox.question(
                self, "确认退出",
                "AutoCAD仍然连接，确定要退出吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.acad.disconnect()
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()



class CADWorkerThread(QThread):
    """在独立线程中执行 CAD 命令队列，主线程不阻塞，停止按钮随时可点。"""
    done = pyqtSignal(bool)  # True=用户停止, False=全部执行完
    controller_ready = pyqtSignal(object)  # 把线程内实际控制器暴露给主线程用于取消

    def __init__(self, commands):
        super().__init__()
        self._commands = list(commands)
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        import pythoncom
        pythoncom.CoInitialize()
        acad = AutoCADController()
        try:
            if not acad.connect():
                self.done.emit(True)
                return
            self.controller_ready.emit(acad)
            for cmd in self._commands:
                if self._stop:
                    acad.cancel_command()
                    break
                acad.send_command(cmd, delay=0.25)
            self.done.emit(self._stop)
        except Exception as e:
            print(f"CADWorkerThread 异常: {e}")
            self.done.emit(True)
        finally:
            try:
                acad.disconnect()
            except Exception:
                pass
            pythoncom.CoUninitialize()


class AIProcessingThread(QThread):
    """AI处理线程（用于本地模型等无 get_request_params 的情况）"""
    result_ready = pyqtSignal(dict)

    def __init__(self, ai_model, command, history=None):
        super().__init__()
        self.ai_model = ai_model
        self.command = command
        self.history = history or []
        self._stopped = False
        self.request_id = 0
    
    def stop(self):
        """停止线程"""
        self._stopped = True
    
    def run(self):
        """运行线程"""
        try:
            result = self.ai_model.process_command(self.command)
            if not isinstance(result, dict):
                result = {"response": str(result), "commands": []}
            result["request_id"] = int(self.request_id or 0)
            if not self._stopped:
                self.result_ready.emit(result)
            else:
                self.result_ready.emit({"response": "已取消", "commands": [], "request_id": int(self.request_id or 0)})
        except Exception as e:
            if not self._stopped:
                self.result_ready.emit({
                    "response": f"处理失败: {str(e)}",
                    "commands": [],
                    "request_id": int(self.request_id or 0)
                })

def main():
    """主函数"""
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    
    # 设置图标
    # app.setWindowIcon(QIcon("icon.png"))
    
    window = AICADPlugin()
    window.show()
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
