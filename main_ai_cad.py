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
from typing import Dict, Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QTextEdit, QLineEdit, QPushButton,
    QVBoxLayout, QHBoxLayout, QWidget, QSplitter, QTreeWidget,
    QTreeWidgetItem, QLabel, QStatusBar, QComboBox, QMessageBox, QDialog,
    QToolButton, QMenu
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QByteArray, QUrl
from PyQt6.QtGui import QTextCursor, QColor, QAction
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply, QSslConfiguration, QSslSocket

from autocad_controller import AutoCADController
from config_manager import ConfigManager
from ai_model import get_ai_model
from ui.settings_window import SettingsWindow
from ipc_bridge import AICADBridgeServer
from core.config_db_store import ConfigDBStore
from core.orchestrator import Orchestrator
from core.ai_intent_analyzer import AIIntentAnalyzer
from core.answer_cache import AnswerCache
from core.drawing_parser import DrawingCommandParser
from connectors.web_retriever import WebRetriever

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

    bridge_chat_signal = pyqtSignal(str)
    
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
        # 配置 SSL (支持 HTTPS)
        ssl_config = QSslConfiguration.defaultConfiguration()
        ssl_config.setPeerVerifyMode(QSslSocket.PeerVerifyMode.VerifyNone)
        QSslConfiguration.setDefaultConfiguration(ssl_config)
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
        self._bridge_last_ai_seq = 0
        self._bridge_last_ai_message = ""
        self._orchestrator = None

        # 本地 IPC Bridge：供 AutoCAD C# 插件调用
        self.bridge = AICADBridgeServer(
            host="127.0.0.1",
            port=8765,
            on_show=self._bridge_show,
            on_stop=self._bridge_stop,
            on_chat=self._bridge_chat,
            on_get_last_ai=self._bridge_get_last_ai,
        )

        # 初始化UI
        self.init_ui()
        self.bridge_chat_signal.connect(self._bridge_chat_on_ui)

        # 先启动桥接服务（优先保证 AutoCAD AIMIND 可快速探活成功）
        try:
            self.bridge.start()
            self.add_chat_message("系统", "[网络] 本地桥接服务已启动: http://127.0.0.1:8765")
        except Exception as e:
            self.add_chat_message("系统", f"[警告] 桥接服务启动失败: {str(e)}")

        # 延后执行可能较慢的初始化，确保 bridge 可被 AIMIND 快速探活
        self.ai_model = None
        QTimer.singleShot(0, self._deferred_init_after_bridge)

        # 更新状态栏
        self.update_status_bar("启动中 - 正在初始化 AutoCAD 与 AI 模型...")
    
    def set_window_properties(self):
        """设置窗口属性：置顶、无边框、不透明"""
        # 设置窗口置顶
        self.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint |  # 始终置顶
            Qt.WindowType.FramelessWindowHint     # 无边框
        )

        # 关闭半透明背景，改为不透明
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)

        # 设置窗口不透明（1.0为完全不透明）
        self.setWindowOpacity(1.0)

        # 不启用鼠标穿透
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
                    self.update_status_bar(f"[OK] 已连接到AutoCAD {version}")
                except:
                    self.status_indicator.set_status("connected")
                    self.status_label.setText("已连接")
                    self.update_status_bar("[OK] 已连接到AutoCAD")
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
                model_name = self.current_model_config.name
                self.update_status_bar(f"AI模型初始化完成: {model_name}")

                # 如果是 NVIDIA 模型，添加提示
                is_nvidia = self.current_model_config.endpoint and "nvidia.com" in self.current_model_config.endpoint
                if is_nvidia:
                    self.add_chat_message("系统", f"[OK] 已加载 NVIDIA 模型: {model_name}\n[注意] 首次使用可能需要 1-2 分钟加载时间，请耐心等待。")
            else:
                self.ai_model = get_ai_model("local")
                self.update_status_bar("使用本地模型（未配置其他模型）")

            # 初始化 Web 检索器
            self._init_web_retriever()

            # 初始化答案缓存
            self._init_answer_cache()

            # 重建编排器(需要 ai_model 和 web_retriever)
            self._orchestrator = None

        except Exception as e:
            self.ai_model = get_ai_model("local")
            self.update_status_bar(f"AI模型初始化失败，使用本地模型: {str(e)}")

    def _init_web_retriever(self):
        """初始化 Web 检索器"""
        try:
            import json
            import os
            config_file = os.path.join(os.path.dirname(__file__), "ai_config.json")
            web_cfg = {}
            if os.path.exists(config_file):
                with open(config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                web_cfg = config.get("web_search", {}) if isinstance(config, dict) else {}

            if web_cfg.get("enabled", False):
                self.web_retriever = WebRetriever(web_cfg)
                self.add_chat_message("系统", "[网络] 网络检索功能已启用")
            else:
                self.web_retriever = None
                print("[System] Web 检索功能未启用")
        except Exception as e:
            self.web_retriever = None
            print(f"[System] Web 检索器初始化失败: {e}")

    def _init_answer_cache(self):
        """初始化答案缓存"""
        try:
            import json
            import os
            config_file = os.path.join(os.path.dirname(__file__), "ai_config.json")
            web_cfg = {}
            if os.path.exists(config_file):
                with open(config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                web_cfg = config.get("web_search", {}) if isinstance(config, dict) else {}

            cache_cfg = web_cfg.get("cache", {})
            if cache_cfg.get("enabled", True):
                self.answer_cache = AnswerCache(
                    max_size=cache_cfg.get("max_size", 200),
                    ttl_seconds=cache_cfg.get("ttl_seconds", 300)
                )
                print(f"[System] 答案缓存已启用: max={cache_cfg.get('max_size', 200)}, ttl={cache_cfg.get('ttl_seconds', 300)}s")
            else:
                self.answer_cache = None
                print("[System] 答案缓存未启用")
        except Exception as e:
            self.answer_cache = None
            print(f"[System] 答案缓存初始化失败: {e}")
    
    def load_models(self):
        """加载配置的模型（优先数据库，其次本地文件）"""
        try:
            import json
            import os

            config_file = os.path.join(os.path.dirname(__file__), "ai_config.json")
            config = {}
            if os.path.exists(config_file):
                with open(config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)

            # 若启用数据库配置中心，优先读取数据库中的启用配置
            db_cfg = config.get("database", {}) if isinstance(config, dict) else {}
            if db_cfg.get("enabled"):
                try:
                    from core.config_db_store import ConfigDBStore
                    store = ConfigDBStore((db_cfg.get("connection_string") or "").strip())
                    active = store.get_active_config((db_cfg.get("config_key") or "app/global").strip())
                    if active and isinstance(active.get("config_json"), dict):
                        config = active.get("config_json")
                except Exception as db_err:
                    print(f"数据库配置读取失败，回退本地配置: {db_err}")

            from ui.settings_window import ModelConfig
            self.models = [ModelConfig.from_dict(m) for m in config.get("models", [])]

            self.model_combo.clear()
            for model in self.models:
                self.model_combo.addItem(model.name)

            if len(self.models) > 0:
                self.model_combo.setCurrentIndex(0)
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
                # 设置变更后重建编排器
                self._orchestrator = None
                # 应用通用主题配置
                self.apply_theme(self._get_saved_theme())
                # 立即刷新数据库连接状态（无需重启）
                self.check_database_connection_at_startup()
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
                model_name = self.current_model_config.name
                self.update_status_bar(f"已切换到模型: {model_name}")

                # NVIDIA 模型特殊提示
                is_nvidia = self.current_model_config.endpoint and "nvidia.com" in self.current_model_config.endpoint
                hint = ""
                if is_nvidia:
                    hint = "\n⏱️ 注意：首次使用 NVIDIA 模型可能需要 1-2 分钟加载时间，请耐心等待。"

                self.add_chat_message("系统", f"已切换到模型: {model_name}{hint}")
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
        
        # AutoCAD 状态指示器
        self.status_indicator = StatusIndicator()
        self.status_label = QLabel("未连接")
        self.status_label.setStyleSheet("font-size: 12px; color: #7f8c8d;")

        # 数据库状态指示器
        self.db_status_indicator = StatusIndicator()
        self.db_status_label = QLabel("书库未连接")
        self.db_status_label.setStyleSheet("font-size: 12px; color: #7f8c8d;")
        
        # 窗口控制按钮（仅图标，无背景块）
        min_button = QPushButton("−")
        min_button.setFixedSize(34, 26)
        min_button.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #7b7f87;
                border: none;
                padding: 0;
                font-size: 20px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: transparent;
                color: #a4a8b0;
            }
            QPushButton:pressed {
                background-color: transparent;
                color: #5f6470;
            }
        """)
        min_button.clicked.connect(self.showMinimized)

        self.max_button = QPushButton("▢")
        self.max_button.setFixedSize(34, 26)
        self.max_button.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #7b7f87;
                border: none;
                padding: 0;
                font-size: 16px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: transparent;
                color: #a4a8b0;
            }
            QPushButton:pressed {
                background-color: transparent;
                color: #5f6470;
            }
        """)
        self.max_button.clicked.connect(self.toggle_maximize)

        close_button = QPushButton("✕")
        close_button.setFixedSize(30, 24)
        close_button.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #7b7f87;
                border: none;
                padding: 0;
                font-size: 13px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: transparent;
                color: #d96b6b;
            }
            QPushButton:pressed {
                background-color: transparent;
                color: #b44b4b;
            }
        """)
        close_button.clicked.connect(self.close)
        
        # 应用内菜单（与标题同一行，位于左侧）
        self.menu_file_btn = QToolButton()
        self.menu_file_btn.setText("文件")
        self.menu_file_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        file_menu = QMenu(self)
        file_menu.addAction("设置", self.open_settings)
        self.menu_file_btn.setMenu(file_menu)

        self.menu_edit_btn = QToolButton(); self.menu_edit_btn.setText("编辑")
        self.menu_view_btn = QToolButton(); self.menu_view_btn.setText("视图")
        self.menu_draw_btn = QToolButton(); self.menu_draw_btn.setText("绘图")
        self.menu_tools_btn = QToolButton(); self.menu_tools_btn.setText("工具")
        self.menu_help_btn = QToolButton(); self.menu_help_btn.setText("帮助")
        self.menu_help_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        help_menu = QMenu(self)
        help_menu.addAction("关于软件", self.show_about_dialog)
        help_menu.addAction("版权与授权", self.show_copyright_dialog)
        self.menu_help_btn.setMenu(help_menu)

        for btn in [self.menu_file_btn, self.menu_edit_btn, self.menu_view_btn, self.menu_draw_btn, self.menu_tools_btn, self.menu_help_btn]:
            btn.setStyleSheet("""
                QToolButton {
                    background: transparent;
                    color: #2c3e50;
                    border: none;
                    padding: 4px 8px;
                    font-size: 13px;
                }
                QToolButton:hover {
                    background-color: #ecf0f1;
                    border-radius: 4px;
                }
            """)
            title_layout.addWidget(btn)

        title_layout.addSpacing(8)
        title_layout.addWidget(title_label)
        title_layout.addSpacing(10)
        title_layout.addWidget(self.status_indicator)
        title_layout.addWidget(self.status_label)
        title_layout.addSpacing(8)
        title_layout.addWidget(self.db_status_indicator)
        title_layout.addWidget(self.db_status_label)
        title_layout.addStretch()
        title_layout.addWidget(min_button)
        title_layout.addSpacing(6)
        title_layout.addWidget(self.max_button)
        title_layout.addSpacing(6)
        title_layout.addWidget(close_button)

        # 顶部控制栏
        control_layout = QHBoxLayout()

        # 模型选择
        model_label = QLabel("🧠 AI模型:")
        model_label.setStyleSheet("font-size: 13px; color: #34495e;")
        self.model_combo = QComboBox()
        self.model_combo.currentIndexChanged.connect(self.on_model_changed)
        self.model_combo.setMinimumWidth(180)

        # 连接按钮
        self.connect_button = QPushButton("🔗 连接AutoCAD")
        self.connect_button.clicked.connect(self.connect_to_acad)

        control_layout.addWidget(model_label)
        control_layout.addWidget(self.model_combo)
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
        self.apply_theme(self._get_saved_theme())
    
    def _load_file_text(self, filename: str) -> str:
        """读取项目根目录文本文件（SOUL/USER/AGENTS）"""
        try:
            path = os.path.join(os.path.dirname(__file__), filename)
            if os.path.exists(path):
                with open(path, 'r', encoding='utf-8') as f:
                    return f.read().strip()
        except Exception:
            pass
        return ""

    def _load_runtime_config(self):
        """读取运行时配置：优先本地配置；若启用 DB 则尝试合并 DB 配置（DB 配置覆盖本地，但不删除本地特有配置）。"""
        cfg = {}
        try:
            config_file = os.path.join(os.path.dirname(__file__), "ai_config.json")
            if os.path.exists(config_file):
                with open(config_file, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
        except Exception:
            cfg = {}

        if not isinstance(cfg, dict):
            cfg = {}

        try:
            db_cfg_local = cfg.get("database", {}) if isinstance(cfg, dict) else {}
            if db_cfg_local.get("enabled"):
                conn_str = (db_cfg_local.get("connection_string") or "").strip()
                config_key = (db_cfg_local.get("config_key") or "app/global").strip()
                if conn_str:
                    store = ConfigDBStore(conn_str)
                    active = store.get_active_config(config_key)
                    if active and isinstance(active.get("config_json"), dict):
                        db_config = active.get("config_json")
                        # 合并策略：DB 配置覆盖本地，但保留本地特有的配置项（如 web_search）
                        merged = cfg.copy()
                        merged.update(db_config)
                        # 特殊处理嵌套字典：对于 web_search 等嵌套配置，如果 DB 没有则保留本地
                        for key in cfg:
                            if key not in db_config:
                                merged[key] = cfg[key]
                            elif isinstance(cfg[key], dict) and isinstance(db_config.get(key), dict):
                                # 合并嵌套字典
                                merged[key] = {**cfg[key], **db_config[key]}
                        return merged
        except Exception:
            pass

        return cfg if isinstance(cfg, dict) else {}

    def _get_saved_theme(self):
        """读取已保存主题（支持 DB 覆盖）"""
        cfg = self._load_runtime_config()
        return (cfg.get("general", {}) or {}).get("theme", "默认") or "默认"

    def apply_theme(self, theme_name: str):
        """应用主题到主界面（不改变业务逻辑）"""
        theme = theme_name or "默认"

        light_qss = """
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
            QTextEdit:focus { border: 2px solid #3498db; }
            QLineEdit {
                background-color: #ffffff;
                border: 2px solid #dcdde1;
                border-radius: 8px;
                padding: 10px;
                font-size: 13px;
                color: #2c3e50;
            }
            QLineEdit:focus { border: 2px solid #3498db; }
            QPushButton {
                background-color: #3498db;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 8px 16px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #2980b9; }
            QPushButton:pressed { background-color: #1f6dad; }
            QComboBox {
                background-color: #ffffff;
                border: 2px solid #dcdde1;
                border-radius: 8px;
                padding: 8px;
                font-size: 13px;
                color: #2c3e50;
            }
            QComboBox:focus { border: 2px solid #3498db; }
            QComboBox::drop-down { border: none; width: 30px; }
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
            QTreeWidget::item { padding: 5px; border-radius: 4px; }
            QTreeWidget::item:selected { background-color: #3498db; color: white; }
            QTreeWidget::item:hover { background-color: #ecf0f1; }
            QStatusBar {
                background-color: #2c3e50;
                color: #ecf0f1;
                border-radius: 0px;
                font-size: 12px;
                padding: 5px;
            }
            QSplitter::handle { background-color: #dcdde1; height: 3px; }
        """

        dark_qss = """
            QMainWindow {
                background-color: #14171c;
                border: 1px solid #2d333b;
                border-radius: 12px;
            }
            QWidget {
                background-color: #1b2129;
                color: #d6dbe3;
                border-radius: 8px;
            }
            QLabel { color: #d6dbe3; background: transparent; }
            QTextEdit {
                background-color: #11161d;
                border: 1px solid #2f3742;
                border-radius: 8px;
                padding: 8px;
                font-size: 13px;
                color: #d6dbe3;
            }
            QTextEdit:focus { border: 1px solid #4b84ff; }
            QLineEdit {
                background-color: #11161d;
                border: 1px solid #2f3742;
                border-radius: 8px;
                padding: 8px;
                font-size: 13px;
                color: #d6dbe3;
            }
            QLineEdit:focus { border: 1px solid #4b84ff; }
            QPushButton {
                background-color: #2e6be6;
                color: #f5f8ff;
                border: none;
                border-radius: 8px;
                padding: 8px 14px;
                font-size: 13px;
                font-weight: 600;
            }
            QPushButton:hover { background-color: #3b78f0; }
            QPushButton:pressed { background-color: #285fcd; }
            QComboBox {
                background-color: #11161d;
                border: 1px solid #2f3742;
                border-radius: 8px;
                padding: 6px 8px;
                color: #d6dbe3;
            }
            QTreeWidget {
                background-color: #11161d;
                border: 1px solid #2f3742;
                border-radius: 8px;
                color: #d6dbe3;
            }
            QTreeWidget::item:selected { background-color: #2e6be6; color: #ffffff; }
            QTreeWidget::item:hover { background-color: #232b36; }
            QStatusBar {
                background-color: #0f141a;
                color: #d6dbe3;
                border-top: 1px solid #2a313d;
                font-size: 12px;
                padding: 4px;
            }
            QSplitter::handle { background-color: #2a313d; height: 3px; }
            QMenu {
                background-color: #1b2129;
                color: #d6dbe3;
                border: 1px solid #2f3742;
            }
            QMenu::item:selected { background-color: #2e6be6; color: #ffffff; }
        """

        if theme == "深色":
            self.setStyleSheet(dark_qss)
        else:
            self.setStyleSheet(light_qss)

    def show_about_dialog(self):
        """显示软件关于信息"""
        about_text = (
            "<b>AutoCADMindAI - AutoCAD智能助手</b><br><br>"
            "版本：企业版（当前构建）<br>"
            "技术栈：Python + PyQt6 + AutoCAD COM + AI 模型接口<br><br>"
            "用途：用于企业内 AutoCAD 智能问答、命令辅助与流程支持。"
        )
        QMessageBox.about(self, "关于软件", about_text)

    def show_copyright_dialog(self):
        """显示版权与授权信息"""
        copyright_text = (
            "<b>软件版权与授权声明</b><br><br>"
            "软件名称：AutoCADMindAI<br>"
            "作者：崔宝明<br>"
            "著作权人/拥有人：崔宝明<br>"
            "授权使用单位：德州锦城电装股份有限公司<br><br>"
            "说明：本软件及相关文档、界面与功能设计受版权保护。"
            "未经授权，不得擅自复制、分发、修改或用于超出授权范围的用途。"
        )
        QMessageBox.information(self, "版权与授权", copyright_text)

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
            self._cad_worker.wait(1500)

        # 1c. 若为线程方式（本地模型），请求工作线程停止
        if self.ai_thread and self.ai_thread.isRunning():
            self.ai_thread.stop()
            self.ai_thread.wait(1000)

        # 2. 仅当"当前确有CAD命令执行"时才发送取消，避免对纯对话误发控制指令
        cancelled = True
        should_cancel_cad = self._cad_execution_active or (self._cad_worker is not None and self._cad_worker.isRunning())
        if should_cancel_cad:
            target_acad = self._cad_executor if self._cad_executor is not None else self.acad
            cancelled = target_acad.force_cancel_command(rounds=10, interval=0.08)
            # 同时对主控制器再补一次取消，覆盖跨线程/句柄切换场景
            if target_acad is not self.acad:
                cancelled = self.acad.force_cancel_command(rounds=4, interval=0.06) or cancelled

            if not cancelled:
                self.add_chat_message("系统", "[警告] 未确认CAD已响应取消，建议手动按一次 ESC")
        # 3. 统一收尾
        self._cad_finish(was_stopped=True)
        self.is_processing = False
        self.set_send_button_state(False)
        self.add_chat_message("系统", "[OK] 已停止（已请求取消CAD当前命令）")
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
            # 每次新请求前重置"用户已停止"标记，避免上次点停止导致本次响应被丢弃
            self._user_requested_stop = False

            # ===== 答案缓存检查 =====
            # 注意：对于需要实时信息的查询（时间/天气/新闻等），跳过缓存
            realtime_keywords = ["今天", "明天", "昨天", "天气", "气温", "温度", "新闻", "最新", "实时", "当前", "现在", "总统", "股价", "汇率"]
            needs_realtime = any(kw in command for kw in realtime_keywords)
            
            if self.answer_cache and not needs_realtime:
                cached_response = self.answer_cache.get(command, "chat")
                if cached_response:
                    print(f"[System] 缓存命中: {command}")
                    self.on_ai_result({
                        "intent": "chat",
                        "response": cached_response,
                        "commands": [],
                        "request_id": int(request_id or self._active_request_id),
                    })
                    return
            elif needs_realtime:
                print(f"[System] 实时信息查询，跳过缓存: {command}")

            self.is_processing = True
            self.set_send_button_state(True)

            self.status_indicator.set_status("processing")
            self.status_label.setText("AI处理中...")
            self.update_status_bar("AI正在思考，请稍候...")
            self.add_chat_message("系统", "正在处理您的请求...")

            self._pending_user_message = command  # 用于收到回复后只追加 assistant 到历史
            # 发送时就把用户消息写入历史，这样即使用户点停止，下一轮"请继续"仍有上下文
            self._chat_history.append({"role": "user", "content": command})
            if len(self._chat_history) > self._chat_history_max:
                self._chat_history = self._chat_history[-self._chat_history_max:]

            # 主流程编排（Phase 2 起步）：优先处理 KB_QA，CAD 命令继续走既有模型链路
            cfg = self._load_runtime_config()
            db_cfg = cfg.get("database", {}) if isinstance(cfg, dict) else {}
            web_cfg = cfg.get("web_search", {}) if isinstance(cfg, dict) else {}
            if self._orchestrator is None:
                self._orchestrator = Orchestrator(
                    db_enabled=bool(db_cfg.get("enabled", False)),
                    db_connection_string=(db_cfg.get("connection_string") or "").strip(),
                    db_domain_code=(db_cfg.get("domain_code") or "").strip(),
                    web_retriever=self.web_retriever,
                    web_cfg=web_cfg,
                    ai_model=self.ai_model
                )
            analyzer = AIIntentAnalyzer(self.ai_model)
            analysis = analyzer.analyze(command, {
                "last_kb_query": getattr(self._orchestrator, "last_kb_query", ""),
                "last_kb_doc_title": getattr(self._orchestrator, "last_kb_doc_title", ""),
            })
            print(f"[Debug] Analysis: {analysis}")
            orchestration_result = self._orchestrator.handle(command, analysis)
            if isinstance(orchestration_result, dict):
                route = orchestration_result.get("route")
                # ===== Web 检索路由 =====
                if route == "web":
                    web_sources = orchestration_result.get("web_sources", [])
                    response_text = orchestration_result.get("response", "")
                    if web_sources:
                        source_lines = []
                        for ws in web_sources:
                            source_lines.append(f"- [{ws.get('title', '')}]({ws.get('url', '')})")
                        response_text += "\n\n来源：\n" + "\n".join(source_lines)
                    self.on_ai_result(
                        {
                            "intent": "chat",
                            "response": response_text or "已联网获取信息，但未生成可展示回答。",
                            "commands": [],
                            "request_id": int(request_id or self._active_request_id),
                        }
                    )
                    return

                if orchestration_result.get("intent") != "command_proxy" and route == "kb":
                    # 需要用户澄清/补充时，直接使用编排器文本
                    self.on_ai_result(
                        {
                            "intent": orchestration_result.get("intent", "chat"),
                            "response": orchestration_result.get("response", ""),
                            "commands": orchestration_result.get("commands", []),
                            "request_id": int(request_id or self._active_request_id),
                        }
                    )
                    return

                if route == "kb_context":
                    # 命中公司知识库后，直接基于证据输出，避免模型脱离事实胡乱发挥
                    kb_context = orchestration_result.get("kb_context") or {}
                    response_text = kb_context.get("summary", "")
                    citations = kb_context.get("citations", [])
                    if citations:
                        source_lines = []
                        for c in citations[:4]:
                            source_lines.append(
                                f"- {c.get('doc_title')}（{c.get('doc_code')}）{c.get('version_no')} {c.get('section')}"
                            )
                        response_text += "\n\n来源：\n" + "\n".join(source_lines)

                    self.on_ai_result(
                        {
                            "intent": "chat",
                            "response": response_text or "已命中知识库，但未生成可展示摘要。",
                            "commands": [],
                            "request_id": int(request_id or self._active_request_id),
                        }
                    )
                    return

                if route == "cad":
                    # CAD 路由优先直通，避免再次走通用大模型导致复杂图形意图丢失
                    self.on_ai_result(
                        {
                            "intent": "drawing" if orchestration_result.get("drawing_commands") else "command",
                            "response": orchestration_result.get("response", ""),
                            "commands": orchestration_result.get("commands", []),
                            "drawing_commands": orchestration_result.get("drawing_commands", []),
                            "request_id": int(request_id or self._active_request_id),
                        }
                    )
                    return

            composed_context = {
                "soul": self._load_file_text("SOUL.md"),
                "user_profile": self._load_file_text("USER.md"),
                "agent_rules": self._load_file_text("AGENTS.md"),
                "instruction": "优先理解用户需求，给出完整建议；如用户询问公司内部标准，优先引导走公司知识库。"
            }

            params = getattr(self.ai_model, "get_request_params", None)
            if callable(params):
                req = self.ai_model.get_request_params(command, composed_context, self._chat_history)
                if req is not None:
                    url, headers, body = req
                    request = QNetworkRequest(QUrl(url))
                    # 应用 SSL 配置
                    ssl_config = QSslConfiguration.defaultConfiguration()
                    request.setSslConfiguration(ssl_config)
                    for k, v in (headers or {}).items():
                        request.setRawHeader(k.encode("utf-8"), v.encode("utf-8"))
                    # 根据端点类型动态设置超时时间
                    timeout_ms = 120000  # 默认 120 秒
                    if "nvidia.com" in url:
                        timeout_ms = 180000  # NVIDIA API 180 秒
                    elif "localhost" in url or "127.0.0.1" in url:
                        timeout_ms = 60000  # 本地模型 60 秒
                    print(f"[Network] 设置超时: {timeout_ms}ms, URL: {url}")
                    request.setTransferTimeout(timeout_ms)
                    self._current_reply = self._network_manager.post(request, QByteArray(body))
                    self._current_reply.setProperty("request_id", int(request_id or self._active_request_id))
                    self._current_reply.finished.connect(self._on_ai_network_finished)
                    return
            # 本地模型等无 get_request_params：仍用线程（本地逻辑很快，几乎不阻塞）
            self.ai_thread = AIProcessingThread(self.ai_model, command, self._chat_history, composed_context)
            self.ai_thread.request_id = int(request_id or self._active_request_id)
            self.ai_thread.result_ready.connect(self.on_ai_result)
            self.ai_thread.finished.connect(self.on_ai_finished)
            self.ai_thread.start()

        except Exception as e:
            self.is_processing = False
            self.set_send_button_state(False)
            self.add_chat_message("系统", f"[错误] 处理失败: {str(e)}")
            self.update_status_bar("[错误] 处理失败")
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
                http_status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
                print(f"[Network Error] Status: {http_status}, Error: {err_msg}")
                self.on_ai_result({"response": f"网络错误({http_status}): {err_msg}", "commands": [], "request_id": request_id})
                return
            data = reply.readAll().data()
            print(f"[Network Response] Length: {len(data)} bytes")
            result = self.ai_model.parse_response(data)
            if isinstance(result, dict):
                result["request_id"] = request_id
            self.on_ai_result(result)
        except Exception as e:
            print(f"[Network Exception] {str(e)}")
            import traceback
            traceback.print_exc()
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

        # 数据库状态不随CAD重置，启动后保持当前检测结果

    def _is_operation_intent(self, text: str) -> bool:
        """判断用户输入是否包含"执行CAD操作"意图。"""
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
    
    def clean_ai_response(self, response: str) -> str:
        """清理模型泄露的思考过程，仅保留最终回答。"""
        if not isinstance(response, str):
            return str(response or "")
        text = response.strip()
        if not text:
            return ""

        # 优先提取"最终回答"段
        for marker in ["【最终回答】", "最终回答：", "最终回答:"]:
            if marker in text:
                return text.split(marker)[-1].strip()

        # 过滤明显思考链前缀行
        thought_prefixes = [
            "首先", "根据规则", "用户说", "回顾", "分析", "思考", "第一步", "第二步", "规则",
            "you must", "json字段", "统一输出格式", "intent=", "commands"
        ]
        lines = text.splitlines()
        kept = []
        for ln in lines:
            s = ln.strip().lower()
            if not s:
                continue
            if any(s.startswith(p) for p in thought_prefixes):
                continue
            kept.append(ln)

        cleaned = "\n".join(kept).strip()
        return cleaned if cleaned else text

    def _sanitize_history_content(self, text: str, max_len: int = 1200) -> str:
        """清洗写入会话历史的文本，避免把系统提示词/超长脏数据带入下一轮。"""
        t = self.clean_ai_response(text)
        if not t:
            return ""

        # 移除疑似系统提示词片段
        bad_markers = [
            "你是autocad智能绘图助手", "## 重要提醒", "输出：{\"intent\"", "可用工具：", "系统prompt", "json格式："
        ]
        tl = t.lower()
        for m in bad_markers:
            idx = tl.find(m.lower())
            if idx >= 0:
                t = t[:idx].strip()
                tl = t.lower()

        # 兜底：如果仍是超长文本，截断
        if len(t) > max_len:
            t = t[:max_len].rstrip() + "…"

        return t

    def _to_num(self, v, default=0.0):
        """鲁棒数值转换：允许嵌套list/tuple，避免 float(list) 异常。"""
        try:
            cur = v
            depth = 0
            while isinstance(cur, (list, tuple)) and cur and depth < 4:
                cur = cur[0]
                depth += 1
            return float(cur)
        except Exception:
            return float(default)

    def _to_xy(self, p, default=(0.0, 0.0)):
        if not isinstance(p, (list, tuple)):
            return float(default[0]), float(default[1])
        if len(p) < 2:
            return float(default[0]), float(default[1])
        return self._to_num(p[0], default[0]), self._to_num(p[1], default[1])

    def _normalize_points(self, pts):
        norm = []
        for p in (pts or []):
            x, y = self._to_xy(p, (0.0, 0.0))
            norm.append((x, y))
        return norm

    def _semantic_quality_check(self, user_text: str, drawing_commands) -> tuple[bool, str]:
        """语义质量门：检查图形是否符合用户对象语义（轻量规则，不写死具体图形参数）。"""
        t = (user_text or "").lower()
        cmds = [c for c in (drawing_commands or []) if isinstance(c, dict)]
        if not cmds:
            return False, "未生成有效绘图命令"

        types = [str(c.get("type", "")).lower() for c in cmds]

        # 椅子：至少应具备座面+靠背语义（通常需要纵向构件，不应仅是桌面+四角块）
        if any(k in t for k in ["椅子", "chair"]):
            rects = [c for c in cmds if str(c.get("type", "")).lower() == "rectangle"]
            lines = [c for c in cmds if str(c.get("type", "")).lower() == "line"]
            polys = [c for c in cmds if str(c.get("type", "")).lower() in {"polyline", "polygon"}]

            # 纯5个矩形且无其他构件，极大概率是错误“桌子模板”
            if len(rects) >= 5 and len(lines) == 0 and len(polys) == 0:
                # 检查是否只有1个大矩形+4个角矩形
                def _area(r):
                    c1 = r.get("corner1", (0, 0))
                    c2 = r.get("corner2", (0, 0))
                    x1, y1 = self._to_xy(c1, (0.0, 0.0))
                    x2, y2 = self._to_xy(c2, (0.0, 0.0))
                    return abs((x2 - x1) * (y2 - y1))
                areas = sorted([_area(r) for r in rects], reverse=True)
                if len(areas) >= 5 and areas[0] > (areas[1] * 6):
                    return False, "语义不匹配：当前结果更像桌子，不像椅子（缺少靠背/座面层次）"

        return True, "ok"

    def _normalize_drawing_commands(self, drawing_commands):
        """执行前标准化绘图命令，降低复杂图形失败率。"""
        parser = DrawingCommandParser()
        normalized = []

        for cmd in (drawing_commands or []):
            validated = parser._validate_command(cmd) if isinstance(cmd, dict) else None
            if not validated:
                continue

            t = validated.get("type")
            if t == "rectangle":
                c1 = list(validated.get("corner1", (0, 0)))
                c2 = list(validated.get("corner2", (100, 80)))
                x1, y1 = self._to_xy(c1, (0.0, 0.0))
                x2, y2 = self._to_xy(c2, (100.0, 80.0))
                validated["corner1"] = (min(x1, x2), min(y1, y2))
                validated["corner2"] = (max(x1, x2), max(y1, y2))

            elif t == "line":
                s = validated.get("start", (0, 0))
                e = validated.get("end", (100, 0))
                sx, sy = self._to_xy(s, (0.0, 0.0))
                ex, ey = self._to_xy(e, (100.0, 0.0))
                validated["start"] = (sx, sy, 0)
                validated["end"] = (ex, ey, 0)

            elif t == "circle":
                c = validated.get("center", (0, 0))
                cx, cy = self._to_xy(c, (0.0, 0.0))
                validated["center"] = (cx, cy, 0)
                validated["radius"] = max(0.1, self._to_num(validated.get("radius", 10), 10.0))

            elif t == "polyline":
                pts = self._normalize_points(validated.get("points", []))
                if len(pts) >= 2:
                    dedup = [pts[0]]
                    for p in pts[1:]:
                        if tuple(p) != tuple(dedup[-1]):
                            dedup.append(p)
                    if len(dedup) >= 2:
                        validated["points"] = dedup

            normalized.append(validated)

        return normalized

    def _sanitize_drawing_commands(self, drawing_commands, max_commands=80):
        """清洗绘图命令：去重、裁剪异常重复，避免复杂场景爆量命令。"""
        sanitized = []
        seen = set()

        def _key(cmd):
            try:
                t = cmd.get("type", "")
                if t == "line":
                    s = cmd.get("start", (0, 0, 0))
                    e = cmd.get("end", (0, 0, 0))
                    sx, sy = self._to_xy(s, (0.0, 0.0))
                    ex, ey = self._to_xy(e, (0.0, 0.0))
                    return ("line", round(sx, 3), round(sy, 3), round(ex, 3), round(ey, 3))
                if t == "rectangle":
                    c1 = cmd.get("corner1", (0, 0))
                    c2 = cmd.get("corner2", (0, 0))
                    x1, y1 = self._to_xy(c1, (0.0, 0.0))
                    x2, y2 = self._to_xy(c2, (0.0, 0.0))
                    return ("rectangle", round(x1, 3), round(y1, 3), round(x2, 3), round(y2, 3))
                if t == "circle":
                    c = cmd.get("center", (0, 0, 0))
                    r = self._to_num(cmd.get("radius", 0), 0.0)
                    cx, cy = self._to_xy(c, (0.0, 0.0))
                    return ("circle", round(cx, 3), round(cy, 3), round(r, 3))
                if t == "polyline":
                    pts = tuple((round(self._to_num(p[0], 0.0), 3), round(self._to_num(p[1], 0.0), 3)) for p in cmd.get("points", []) if isinstance(p, (list, tuple)) and len(p) >= 2)
                    return ("polyline", pts, bool(cmd.get("closed", False)))
                return (t, str(cmd))
            except Exception:
                return ("unknown", str(cmd))

        for cmd in (drawing_commands or []):
            if not isinstance(cmd, dict):
                continue
            t = str(cmd.get("type", "")).lower()
            if t not in {"line", "circle", "rectangle", "polyline", "arc", "text", "star", "polygon"}:
                continue

            # 防御：超大多段线点数裁剪，避免复杂图形异常输出拖垮执行
            if t == "polyline":
                pts = cmd.get("points", []) or []
                if len(pts) > 300:
                    cmd = dict(cmd)
                    cmd["points"] = pts[:300]

            k = _key(cmd)
            if k in seen:
                continue
            seen.add(k)
            sanitized.append(cmd)
            if len(sanitized) >= max_commands:
                break

        return sanitized

    def _try_recover_drawing_from_text(self, response_text: str):
        """当模型把绘图JSON塞进response文本时，尝试恢复 drawing_commands。"""
        txt = (response_text or "").strip()
        if not txt or "drawing_commands" not in txt:
            return None

        parser = DrawingCommandParser()
        parsed = parser.parse_ai_response(txt)
        cmds = parsed.get("drawing_commands", []) if isinstance(parsed, dict) else []
        if cmds:
            return {
                "intent": "drawing",
                "response": parsed.get("response_text") or "已恢复绘图指令。",
                "drawing_commands": cmds,
            }

        # 二次恢复：从损坏JSON中提取局部图元对象（circle/rectangle/line/polyline/text）
        recovered_cmds = []
        for pat in [
            r'\{\s*"type"\s*:\s*"circle"[\s\S]*?\}',
            r'\{\s*"type"\s*:\s*"rectangle"[\s\S]*?\}',
            r'\{\s*"type"\s*:\s*"line"[\s\S]*?\}',
            r'\{\s*"type"\s*:\s*"polyline"[\s\S]*?\}',
            r'\{\s*"type"\s*:\s*"text"[\s\S]*?\}',
        ]:
            for m in re.finditer(pat, txt):
                snippet = m.group(0)
                try:
                    obj = json.loads(snippet)
                except Exception:
                    continue
                v = parser._validate_command(obj)
                if v:
                    recovered_cmds.append(v)
                if len(recovered_cmds) >= 80:
                    break
            if len(recovered_cmds) >= 80:
                break

        if recovered_cmds:
            # 去重
            uniq = []
            seen = set()
            for c in recovered_cmds:
                k = json.dumps(c, ensure_ascii=False, sort_keys=True)
                if k in seen:
                    continue
                seen.add(k)
                uniq.append(c)
                if len(uniq) >= 80:
                    break
            return {
                "intent": "drawing",
                "response": "已从损坏响应中恢复部分可执行绘图命令。",
                "drawing_commands": uniq,
            }

        # 中性回退：不写死任何图形模板，保持由大模型主导
        # 若检测到绘图JSON痕迹但无法完整恢复，返回None让上层触发重试/再生成
        tl = txt.lower()
        if any(k in tl for k in ["drawing_commands", '"type"', '"circle"', '"rectangle"', '"polyline"']):
            return None

        return None

    def _retry_failed_drawing_commands(self, drawing_commands, draw_result):
        """对失败命令做一次轻量修复重试。"""
        failed_cmds = []
        results = (draw_result or {}).get("results", [])
        for idx, r in enumerate(results):
            if not r.get("success") and idx < len(drawing_commands):
                failed_cmds.append(drawing_commands[idx])

        if not failed_cmds:
            return None

        repaired = []
        for cmd in failed_cmds:
            c = dict(cmd)
            t = c.get("type")
            # 圆/矩形/线 常见失败修复：整体平移，规避重叠与非法点
            if t == "circle":
                center = list(c.get("center", (0, 0, 0)))
                cx, cy = self._to_xy(center, (0.0, 0.0))
                c["center"] = [cx + 20, cy + 20, 0]
            elif t == "rectangle":
                c1 = list(c.get("corner1", (0, 0)))
                c2 = list(c.get("corner2", (100, 80)))
                x1, y1 = self._to_xy(c1, (0.0, 0.0))
                x2, y2 = self._to_xy(c2, (100.0, 80.0))
                c["corner1"] = [x1 + 20, y1 + 20]
                c["corner2"] = [x2 + 20, y2 + 20]
            elif t == "line":
                s = list(c.get("start", (0, 0, 0)))
                e = list(c.get("end", (100, 0, 0)))
                sx, sy = self._to_xy(s, (0.0, 0.0))
                ex, ey = self._to_xy(e, (100.0, 0.0))
                c["start"] = [sx + 20, sy + 20, 0]
                c["end"] = [ex + 20, ey + 20, 0]
            repaired.append(c)

        if not repaired:
            return None
        return self.acad.execute_drawing_commands(repaired)

    def _bbox_of_command(self, cmd):
        """计算命令的2D包围盒: (minx, miny, maxx, maxy)。"""
        t = (cmd or {}).get("type", "")
        try:
            if t == "rectangle":
                c1 = cmd.get("corner1", (0, 0))
                c2 = cmd.get("corner2", (0, 0))
                x1, y1 = self._to_xy(c1, (0.0, 0.0))
                x2, y2 = self._to_xy(c2, (0.0, 0.0))
                return (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))
            if t == "circle":
                c = cmd.get("center", (0, 0, 0))
                r = max(0.0, self._to_num(cmd.get("radius", 0), 0.0))
                x, y = self._to_xy(c, (0.0, 0.0))
                return (x - r, y - r, x + r, y + r)
            if t == "line":
                s = cmd.get("start", (0, 0, 0))
                e = cmd.get("end", (0, 0, 0))
                x1, y1 = self._to_xy(s, (0.0, 0.0))
                x2, y2 = self._to_xy(e, (0.0, 0.0))
                return (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))
            if t == "polyline":
                pts = cmd.get("points", [])
                if len(pts) >= 2:
                    norm = self._normalize_points(pts)
                    xs = [p[0] for p in norm]
                    ys = [p[1] for p in norm]
                    return (min(xs), min(ys), max(xs), max(ys))
            if t == "star":
                c = cmd.get("center", (0, 0, 0))
                r_out = max(0.0, self._to_num(cmd.get("outer_radius", 0), 0.0))
                x, y = self._to_xy(c, (0.0, 0.0))
                return (x - r_out, y - r_out, x + r_out, y + r_out)
        except Exception:
            return None
        return None

    def _bbox_overlap(self, a, b):
        if not a or not b:
            return False
        return not (a[2] <= b[0] or a[0] >= b[2] or a[3] <= b[1] or a[1] >= b[3])

    def _bbox_contains(self, outer, inner, eps: float = 1e-6) -> bool:
        """判断 inner 是否被 outer 完全包含（用于排除容器-子图元避让）。"""
        if not outer or not inner:
            return False
        return (
            outer[0] <= inner[0] + eps and
            outer[1] <= inner[1] + eps and
            outer[2] >= inner[2] - eps and
            outer[3] >= inner[3] - eps
        )

    def _detect_geometry_conflicts(self, commands):
        """检测命令间几何冲突（包围盒重叠），返回冲突对索引列表。"""
        bboxes = [self._bbox_of_command(c) for c in (commands or [])]
        conflicts = []
        for i in range(len(bboxes)):
            if bboxes[i] is None:
                continue
            for j in range(i + 1, len(bboxes)):
                if bboxes[j] is None:
                    continue
                if self._bbox_overlap(bboxes[i], bboxes[j]):
                    # 忽略容器-子图元关系：例如“背景矩形里有线/星”，不应把子图元顶出。
                    if self._bbox_contains(bboxes[i], bboxes[j]) or self._bbox_contains(bboxes[j], bboxes[i]):
                        continue
                    conflicts.append((i, j))
        return conflicts

    def _translate_command(self, cmd, dx, dy):
        c = dict(cmd or {})
        t = c.get("type", "")
        try:
            if t == "rectangle":
                c1 = list(c.get("corner1", (0, 0)))
                c2 = list(c.get("corner2", (0, 0)))
                c["corner1"] = [float(c1[0]) + dx, float(c1[1]) + dy]
                c["corner2"] = [float(c2[0]) + dx, float(c2[1]) + dy]
            elif t == "circle":
                center = list(c.get("center", (0, 0, 0)))
                if len(center) < 3:
                    center = [center[0], center[1], 0]
                center[0] = float(center[0]) + dx
                center[1] = float(center[1]) + dy
                c["center"] = center
            elif t == "line":
                s = list(c.get("start", (0, 0, 0)))
                e = list(c.get("end", (0, 0, 0)))
                if len(s) < 3:
                    s = [s[0], s[1], 0]
                if len(e) < 3:
                    e = [e[0], e[1], 0]
                s[0] = float(s[0]) + dx; s[1] = float(s[1]) + dy
                e[0] = float(e[0]) + dx; e[1] = float(e[1]) + dy
                c["start"] = s
                c["end"] = e
            elif t == "polyline":
                pts = c.get("points", [])
                c["points"] = [[float(p[0]) + dx, float(p[1]) + dy] for p in pts]
            elif t == "star":
                center = list(c.get("center", (0, 0, 0)))
                if len(center) < 2:
                    center = [0, 0, 0]
                if len(center) < 3:
                    center = [center[0], center[1], 0]
                center[0] = float(center[0]) + dx
                center[1] = float(center[1]) + dy
                c["center"] = center
        except Exception:
            return c
        return c

    def _apply_auto_layout(self, commands, spacing=20.0):
        """自动布局：检测冲突并对后续图形做平移避让。"""
        laid_out = [dict(c) for c in (commands or [])]
        moved = 0
        max_iter = 6

        for _ in range(max_iter):
            conflicts = self._detect_geometry_conflicts(laid_out)
            if not conflicts:
                break

            changed = False
            for i, j in conflicts:
                bi = self._bbox_of_command(laid_out[i])
                bj = self._bbox_of_command(laid_out[j])
                if not bi or not bj:
                    continue
                width_j = max(1.0, bj[2] - bj[0])
                height_j = max(1.0, bj[3] - bj[1])

                # 优先向右避让，若x方向空间不足则向上避让
                dx = (bi[2] - bj[0]) + spacing
                dy = 0.0
                if dx < spacing:
                    dx = width_j + spacing
                if dx > width_j * 4:
                    dx = 0.0
                    dy = (bi[3] - bj[1]) + spacing
                    if dy < spacing:
                        dy = height_j + spacing

                laid_out[j] = self._translate_command(laid_out[j], dx, dy)
                moved += 1
                changed = True

            if not changed:
                break

        remain = self._detect_geometry_conflicts(laid_out)
        if remain:
            laid_out, grid_moved = self._apply_grid_layout_fallback(laid_out, spacing=spacing)
            moved += grid_moved
            remain = self._detect_geometry_conflicts(laid_out)

        return laid_out, moved, remain

    def _apply_grid_layout_fallback(self, commands, spacing=20.0):
        """网格回退布局：对仍冲突的图元强制排列到网格位。"""
        arranged = [dict(c) for c in (commands or [])]
        if len(arranged) <= 1:
            return arranged, 0

        bboxes = [self._bbox_of_command(c) for c in arranged]
        valid = [b for b in bboxes if b]
        if not valid:
            return arranged, 0

        avg_w = sum((b[2] - b[0]) for b in valid) / len(valid)
        avg_h = sum((b[3] - b[1]) for b in valid) / len(valid)
        cell_w = max(20.0, avg_w + spacing)
        cell_h = max(20.0, avg_h + spacing)

        moved = 0
        cols = max(2, int(len(arranged) ** 0.5) + 1)
        origin_x, origin_y = 0.0, 0.0

        for idx, cmd in enumerate(arranged):
            bb = self._bbox_of_command(cmd)
            if not bb:
                continue
            row = idx // cols
            col = idx % cols
            target_min_x = origin_x + col * cell_w
            target_min_y = origin_y + row * cell_h
            dx = target_min_x - bb[0]
            dy = target_min_y - bb[1]
            if abs(dx) > 1e-6 or abs(dy) > 1e-6:
                arranged[idx] = self._translate_command(cmd, dx, dy)
                moved += 1

        return arranged, moved

    def _extract_layout_intent(self, user_text: str):
        """从用户语句中提取布局意图。"""
        t = (user_text or "").lower()
        if not t:
            return "none"
        if "居中" in t or "中心对齐" in t:
            return "center"
        if "一行" in t or "横向" in t or "从左到右" in t:
            return "row"
        if "一列" in t or "纵向" in t or "从上到下" in t:
            return "column"
        if "网格" in t or "矩阵" in t or "阵列" in t:
            return "grid"
        return "none"

    def _should_skip_layout_adjustment(self, user_text: str, commands) -> bool:
        """是否应跳过自动布局：尺寸/标注命令不应被平移打散。"""
        t = (user_text or "").lower()
        if any(k in t for k in ["标注", "尺寸", "dimension", "dim"]):
            return True

        cmds = [c for c in (commands or []) if isinstance(c, dict)]
        if not cmds:
            return False

        types = [str(c.get("type", "")).lower() for c in cmds]
        anno_count = sum(1 for tp in types if tp in {"text", "line"})
        shape_count = sum(1 for tp in types if tp in {"rectangle", "circle", "polyline", "polygon", "star", "arc"})

        # 以标注为主的命令集，保持原始坐标关系
        if anno_count >= max(3, int(len(types) * 0.6)) and shape_count <= 1:
            return True
        return False

    def _extract_layout_params(self, user_text: str):
        """从用户语句中提取布局参数（行列数/间距，支持每行N个）。"""
        import re
        t = (user_text or "").lower()
        params = {"rows": None, "cols": None, "spacing": None}

        # 间距/距离（支持单位：m/cm/mm，默认按当前图纸单位）
        spacing_match = re.search(r"(间距|间隔|距离)\s*([0-9]+\.?[0-9]*)\s*(m|cm|mm)?", t)
        if spacing_match:
            try:
                v = float(spacing_match.group(2))
                unit = spacing_match.group(3)
                if unit == "m":
                    v = v * 1000.0
                elif unit == "cm":
                    v = v * 10.0
                params["spacing"] = max(1.0, v)
            except Exception:
                pass

        # 3行4列 / 3x4 / 3×4
        grid_match = re.search(r"(\d+)\s*(行|列|x|×)\s*(\d+)", t)
        if grid_match:
            a = int(grid_match.group(1))
            b = int(grid_match.group(3))
            if grid_match.group(2) in {"行", "x", "×"}:
                params["rows"] = a
                params["cols"] = b
            else:
                params["cols"] = a
                params["rows"] = b

        # 每行N个 / 每列N个
        per_row = re.search(r"每\s*行\s*(\d+)\s*个", t)
        per_col = re.search(r"每\s*列\s*(\d+)\s*个", t)
        if per_row:
            params["cols"] = int(per_row.group(1))
        if per_col:
            params["rows"] = int(per_col.group(1))

        # 单独行/列数量
        rows_match = re.search(r"(\d+)\s*行", t)
        cols_match = re.search(r"(\d+)\s*列", t)
        if rows_match:
            params["rows"] = int(rows_match.group(1))
        if cols_match:
            params["cols"] = int(cols_match.group(1))

        return params

    def _apply_semantic_layout(self, commands, user_text: str, spacing=20.0):
        """按语义布局意图预布局图元：row/column/grid/center。"""
        mode = self._extract_layout_intent(user_text)
        params = self._extract_layout_params(user_text)
        arranged = [dict(c) for c in (commands or [])]
        if mode == "none" or len(arranged) <= 1:
            return arranged, "none"

        bboxes = [self._bbox_of_command(c) for c in arranged]
        valid = [b for b in bboxes if b]
        if not valid:
            return arranged, "none"

        spacing = params.get("spacing") if params.get("spacing") is not None else spacing
        avg_w = sum((b[2] - b[0]) for b in valid) / len(valid)
        avg_h = sum((b[3] - b[1]) for b in valid) / len(valid)
        step_x = max(20.0, avg_w + spacing)
        step_y = max(20.0, avg_h + spacing)

        if mode == "row":
            for i, cmd in enumerate(arranged):
                bb = self._bbox_of_command(cmd)
                if not bb:
                    continue
                target_x = i * step_x
                target_y = 0.0
                arranged[i] = self._translate_command(cmd, target_x - bb[0], target_y - bb[1])
            return arranged, "row"

        if mode == "column":
            for i, cmd in enumerate(arranged):
                bb = self._bbox_of_command(cmd)
                if not bb:
                    continue
                target_x = 0.0
                target_y = i * step_y
                arranged[i] = self._translate_command(cmd, target_x - bb[0], target_y - bb[1])
            return arranged, "column"

        if mode == "grid":
            cols = params.get("cols") or max(2, int(len(arranged) ** 0.5) + 1)
            rows = params.get("rows") or max(1, int((len(arranged) + cols - 1) / cols))

            for i, cmd in enumerate(arranged):
                bb = self._bbox_of_command(cmd)
                if not bb:
                    continue
                row = i // cols
                col = i % cols
                target_x = col * step_x
                target_y = row * step_y
                arranged[i] = self._translate_command(cmd, target_x - bb[0], target_y - bb[1])

            # 若用户指定了行列且目标格子大于图元数，保留前N个即可（由上游扩增控制数量）
            max_cells = rows * cols
            if max_cells > 0 and len(arranged) > max_cells:
                arranged = arranged[:max_cells]

            return arranged, "grid"

        if mode == "center":
            # 将整体包围盒平移到原点附近中心
            minx = min(b[0] for b in valid)
            miny = min(b[1] for b in valid)
            maxx = max(b[2] for b in valid)
            maxy = max(b[3] for b in valid)
            cx = (minx + maxx) / 2.0
            cy = (miny + maxy) / 2.0
            dx = -cx
            dy = -cy
            arranged = [self._translate_command(c, dx, dy) for c in arranged]
            return arranged, "center"

        return arranged, "none"

    def _extract_repeat_count(self, user_text: str):
        """提取用户要求的图元数量，如“画12个圆/12件/12个图形”。"""
        import re
        t = (user_text or "").lower()
        if not t:
            return None

        # 明确总数语义优先
        patterns = [
            r"共\s*(\d+)\s*(个|件|图形|图元)",
            r"总共\s*(\d+)\s*(个|件|图形|图元)",
            r"(\d+)\s*(个|件|图形|图元)"
        ]
        for p in patterns:
            m = re.search(p, t)
            if m:
                try:
                    n = int(m.group(1))
                    if n > 0:
                        return n
                except Exception:
                    return None

        # 若给出行列，推导总数
        params = self._extract_layout_params(user_text)
        rows = params.get("rows")
        cols = params.get("cols")
        if rows and cols and rows > 0 and cols > 0:
            return rows * cols

        return None

    def _expand_commands_by_count(self, commands, user_text: str):
        """当用户指定数量且模型仅返回少量图元时，自动扩增图元。"""
        target = self._extract_repeat_count(user_text)
        source = [dict(c) for c in (commands or [])]
        if not target or not source:
            return source, 0
        if len(source) >= target:
            return source[:target], 0

        expanded = list(source)
        idx = 0
        while len(expanded) < target:
            expanded.append(dict(source[idx % len(source)]))
            idx += 1
        return expanded, (len(expanded) - len(source))

    def execute_tool(self, tool_name: str, arguments: Dict) -> Dict:
        """执行工具调用"""
        print(f"[Tool] 执行工具: {tool_name}, 参数: {arguments}")

        if tool_name == "execute_cad_command":
            # 执行 CAD 命令
            command = arguments.get("command", "")
            if command:
                return {"success": True, "message": f"CAD命令已执行: {command}"}
            return {"success": False, "error": "未指定命令"}

        elif tool_name == "query_cad_status":
            # 查询 CAD 状态
            return {
                "success": True,
                "connected": self.acad.is_connected,
                "message": "已连接到AutoCAD" if self.acad.is_connected else "未连接"
            }

        elif tool_name == "search_knowledge_base":
            # 搜索知识库
            query = arguments.get("query", "")
            if not query:
                return {"success": False, "error": "未提供搜索关键词"}
            # 简单返回，实际会走编排器
            return {"success": True, "message": f"知识库搜索: {query}"}

        return {"success": False, "error": f"未知工具: {tool_name}"}

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

            # 优先恢复：若AI把绘图JSON塞进文本，先恢复为结构化绘图，避免被当成普通聊天丢失
            recovered = self._try_recover_drawing_from_text(response_text)
            if recovered:
                result = {**result, **recovered}
                intent = result.get("intent", intent)
                response_text = result.get("response", response_text)

            # AI主导兜底：明确绘图意图但模型返回空/聊天时，自动触发一次纯绘图重试
            if intent != "drawing" and self._is_operation_intent(self._last_user_input):
                no_payload = (not result.get("drawing_commands")) and (not response_text)
                looks_chat = intent == "chat"
                if looks_chat or no_payload:
                    try:
                        force_prompt = (
                            "用户请求是明确绘图操作。请只返回一个JSON对象："
                            "{\"intent\":\"drawing\",\"response\":\"...\",\"drawing_commands\":[...]}。"
                            "不要解释，不要markdown，不要代码块。\n"
                            f"用户请求：{self._last_user_input}"
                        )
                        forced_text = self.ai_model.generate_with_context(force_prompt)
                        parser = DrawingCommandParser()
                        forced_parsed = parser.parse_ai_response(forced_text)
                        forced_cmds = forced_parsed.get("drawing_commands", []) if isinstance(forced_parsed, dict) else []
                        if forced_cmds:
                            result = {
                                **result,
                                "intent": "drawing",
                                "response": forced_parsed.get("response_text") or "已按模型重试生成绘图命令。",
                                "drawing_commands": forced_cmds,
                            }
                            intent = "drawing"
                            response_text = result.get("response", response_text)
                    except Exception as _:
                        pass

            # 【调试日志】打印 AI 返回的完整结果
            print(f"\n[DEBUG] AI 返回结果:")
            print(f"  intent: {intent}")
            print(f"  response: {response_text[:100] if response_text else 'None'}...")
            print(f"  drawing_commands: {result.get('drawing_commands', [])}")
            print(f"  commands: {result.get('commands', [])}")
            print(f"  完整结果: {result}")

            # 【工具调用】处理 AI 返回的工具调用
            if intent == "tool_call":
                tool_calls = result.get("tool_calls", [])
                if tool_calls:
                    # 执行第一个工具调用
                    tc = tool_calls[0]
                    tool_name = tc.get("name", "")
                    tool_args = tc.get("arguments", {})

                    # 如果 arguments 是字符串，尝试解析
                    if isinstance(tool_args, str):
                        import json
                        try:
                            tool_args = json.loads(tool_args)
                        except:
                            tool_args = {}

                    self.add_chat_message("系统", f"🔧 调用工具: {tool_name}")

                    # 执行工具
                    tool_result = self.execute_tool(tool_name, tool_args)

                    # 把工具结果转为文本返回给用户
                    if tool_result.get("success"):
                        self.add_chat_message("AI", f"[OK] {tool_result.get('message', '执行成功')}")
                    else:
                        self.add_chat_message("AI", f"[错误] {tool_result.get('error', '执行失败')}")

                    # 工具执行完成，恢复状态
                    self.update_status_bar("[OK] 工具执行完成")
                    return

            # 【自动绘图】处理 AI 返回的绘图指令
            print(f"[DEBUG] 检查绘图意图: intent={intent}, is_drawing={intent == 'drawing'}")
            
            if intent == "drawing":
                drawing_commands = result.get("drawing_commands", [])
                drawing_commands = self._sanitize_drawing_commands(drawing_commands, max_commands=120)
                print(f"[DEBUG] drawing_commands(清洗后): {drawing_commands}")

                if not drawing_commands:
                    # 尝试从 response_text 中解析绘图命令
                    parser = DrawingCommandParser()
                    parsed = parser.parse_ai_response(response_text)
                    drawing_commands = parsed.get("drawing_commands", [])
                    print(f"[DEBUG] 从文本解析出的绘图命令: {drawing_commands}")
                    if parsed.get("response_text"):
                        response_text = parsed["response_text"]

                # 语义质量门：若明显不符合对象语义，触发一次模型重试
                ok, reason = self._semantic_quality_check(self._last_user_input, drawing_commands)
                if not ok:
                    try:
                        force_prompt = (
                            "用户请求是明确绘图操作，并且需要语义匹配。请严格根据对象语义生成绘图命令，"
                            "避免用不相关的模板替代。只返回JSON对象："
                            "{\"intent\":\"drawing\",\"response\":\"...\",\"drawing_commands\":[...]}。"
                            "不要解释，不要markdown，不要代码块。\n"
                            f"用户请求：{self._last_user_input}\n"
                            f"不合格原因：{reason}"
                        )
                        forced_text = self.ai_model.generate_with_context(force_prompt)
                        parser = DrawingCommandParser()
                        forced_parsed = parser.parse_ai_response(forced_text)
                        forced_cmds = forced_parsed.get("drawing_commands", []) if isinstance(forced_parsed, dict) else []
                        if forced_cmds:
                            drawing_commands = forced_cmds
                            response_text = forced_parsed.get("response_text") or response_text
                            print(f"[DEBUG] 语义重试后绘图命令: {drawing_commands}")
                    except Exception:
                        pass
                
                if drawing_commands:
                    # 检查 AutoCAD 连接状态
                    print(f"[DEBUG] 检查连接: is_connected={self.acad.is_connected}, acad_app={self.acad.acad_app is not None}")
                    if not self.acad.is_connected:
                        self.add_chat_message("系统", "⚠️ AutoCAD 未连接，正在尝试连接...")
                        self.connect_to_acad()
                        QApplication.processEvents()
                        print(f"[DEBUG] 连接后: is_connected={self.acad.is_connected}")
                    
                    if not self.acad.is_connected:
                        self.add_chat_message("系统", "❌ 无法连接 AutoCAD，请确保 AutoCAD 已启动")
                        self.is_processing = False
                        self.set_send_button_state(False)
                        return
                    
                    # 检查是否有活动文档
                    doc_ok = self.acad.ensure_document()
                    print(f"[DEBUG] 文档检查: ensure_document={doc_ok}, acad_doc={self.acad.acad_doc is not None}")
                    if not doc_ok:
                        self.add_chat_message("系统", "❌ AutoCAD 未打开任何图纸，请先打开一个 DWG 文件")
                        self.is_processing = False
                        self.set_send_button_state(False)
                        return
                    
                    normalized_commands = self._normalize_drawing_commands(drawing_commands)
                    expanded_commands, expanded_count = self._expand_commands_by_count(normalized_commands, self._last_user_input)
                    if expanded_count > 0:
                        self.add_chat_message("系统", f"🧬 已按数量语义自动扩增图元: +{expanded_count}")

                    if self._should_skip_layout_adjustment(self._last_user_input, expanded_commands):
                        semantic_commands = expanded_commands
                        semantic_mode = "none"
                        layout_commands = expanded_commands
                        moved_count, remain_conflicts = 0, []
                        self.add_chat_message("系统", "📐 检测为标注/尺寸场景，已保持原始几何关系（跳过自动布局）")
                    else:
                        semantic_commands, semantic_mode = self._apply_semantic_layout(expanded_commands, self._last_user_input, spacing=20.0)
                        if semantic_mode != "none":
                            self.add_chat_message("系统", f"🧩 已应用语义布局: {semantic_mode}")

                        layout_commands, moved_count, remain_conflicts = self._apply_auto_layout(semantic_commands, spacing=20.0)
                        if moved_count > 0:
                            self.add_chat_message("系统", f"🧭 已自动调整布局，避让 {moved_count} 处潜在重叠")
                        if remain_conflicts:
                            self.add_chat_message("系统", f"[提示] 仍有 {len(remain_conflicts)} 处潜在重叠，已尽量优化")

                    self.add_chat_message("系统", f"🎨 自动绘制 {len(layout_commands)} 个图形...")
                    self.update_status_bar("🎨 正在自动绘图...")

                    # 执行绘图命令
                    print(f"[DEBUG] 执行绘图命令(标准化+布局后): {layout_commands}")
                    draw_result = self.acad.execute_drawing_commands(layout_commands)
                    print(f"[DEBUG] 绘图结果: {draw_result}")

                    if not draw_result.get("success"):
                        # 失败命令进行一次轻量修复重试
                        retry_result = self._retry_failed_drawing_commands(layout_commands, draw_result)
                        if retry_result and retry_result.get("success"):
                            draw_result = retry_result
                            self.add_chat_message("系统", "🔁 失败命令已自动修复并重试成功")

                    if draw_result.get("success"):
                        self.add_chat_message("AI", f"✅ {response_text or '绘图完成'}")
                        # 缩放到全部图形
                        self.acad.zoom_extents()
                    else:
                        failed = draw_result.get("failed_count", 0)
                        # 显示详细错误信息
                        error_details = []
                        for r in draw_result.get("results", []):
                            if not r.get("success"):
                                error_details.append(f"  - {r.get('type', '未知')}: {r.get('message', '未知错误')}")
                        error_msg = "\n".join(error_details) if error_details else ""
                        self.add_chat_message("AI", f"⚠️ {response_text or '部分绘图失败'} (失败{failed}个)\n{error_msg}")
                    
                    # 写入对话历史（清洗，防止提示词污染）
                    hist_text = self._sanitize_history_content(response_text or "绘图完成")
                    self._chat_history.append({"role": "assistant", "content": hist_text or "绘图完成"})
                    if len(self._chat_history) > self._chat_history_max:
                        self._chat_history = self._chat_history[-self._chat_history_max:]
                    
                    self._bridge_last_ai_seq += 1
                    self._bridge_last_ai_message = str(response_text or "绘图完成")
                    
                    self.update_status_bar("[OK] 绘图完成")
                    self.is_processing = False
                    self.set_send_button_state(False)
                    self.reset_status()
                    return

            # ===== 导出意图处理 =====
            print(f"[DEBUG] 检查导出意图: intent={intent}, is_export={intent == 'export'}")
            
            if intent == "export":
                export_type = result.get("export_type", "all")
                print(f"[DEBUG] export_type: {export_type}")
                
                # 检查 AutoCAD 连接状态
                if not self.acad.is_connected:
                    self.add_chat_message("系统", "⚠️ AutoCAD 未连接，正在尝试连接...")
                    self.connect_to_acad()
                    QApplication.processEvents()
                
                if not self.acad.is_connected:
                    self.add_chat_message("系统", "❌ 无法连接 AutoCAD，请确保 AutoCAD 已启动")
                    self.is_processing = False
                    self.set_send_button_state(False)
                    return
                
                # 检查是否有活动文档
                doc_ok = self.acad.ensure_document()
                if not doc_ok:
                    self.add_chat_message("系统", "❌ AutoCAD 未打开任何图纸，请先打开一个 DWG 文件")
                    self.is_processing = False
                    self.set_send_button_state(False)
                    return
                
                # 生成导出文件路径
                import os
                from datetime import datetime
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                export_filename = f"CAD_导出_{timestamp}.xlsx"
                export_filepath = os.path.join(os.path.expanduser("~"), "Desktop", export_filename)
                
                self.add_chat_message("系统", f"📊 正在导出图纸信息...")
                self.update_status_bar("📊 正在导出到Excel...")
                
                # 执行导出
                export_result = self.acad.export_to_excel(export_filepath, export_type)
                print(f"[DEBUG] 导出结果: {export_result}")
                
                if export_result.get("success"):
                    self.add_chat_message("AI", f"✅ {response_text or '导出成功'}\n文件已保存到: {export_filepath}")
                else:
                    self.add_chat_message("AI", f"❌ {export_result.get('message', '导出失败')}")
                
                # 写入对话历史
                hist_text = self._sanitize_history_content(response_text or "导出完成")
                self._chat_history.append({"role": "assistant", "content": hist_text or "导出完成"})
                if len(self._chat_history) > self._chat_history_max:
                    self._chat_history = self._chat_history[-self._chat_history_max:]
                
                self._bridge_last_ai_seq += 1
                self._bridge_last_ai_message = str(response_text or "导出完成")
                
                self.update_status_bar("[OK] 导出完成")
                self.is_processing = False
                self.set_send_button_state(False)
                self.reset_status()
                return

            response_text = self.clean_ai_response(response_text)

            # ===== 写入答案缓存 =====
            if self.answer_cache and intent == "chat":
                user_input = self._pending_user_message or ""
                if user_input:
                    self.answer_cache.set(user_input, intent, response_text)

            self.add_chat_message("AI", response_text)
            self._bridge_last_ai_seq += 1
            self._bridge_last_ai_message = str(response_text or "")

            # 仅追加 AI 回复到对话历史（用户消息已在发送时写入，避免点停止后丢失上下文）
            hist_text = self._sanitize_history_content(response_text)
            self._chat_history.append({"role": "assistant", "content": hist_text})
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

            self.update_status_bar("[OK] 处理完成")
        except Exception as e:
            self.add_chat_message("系统", f"[错误] 处理AI结果时出错: {str(e)}")
            self.update_status_bar("[错误] 处理出错")
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
        try:
            if self._cad_worker is not None:
                self._cad_worker.wait(300)
        except Exception:
            pass
        self._cad_worker = None
        self._cad_executor = None
        self._cad_finish(was_stopped=stopped)

    def _cad_finish(self, was_stopped=None):
        """CAD 命令执行完毕或用户停止后的收尾。was_stopped 为 True 表示用户点击了停止。"""
        if was_stopped is None:
            was_stopped = self._user_requested_stop
        if self.is_processing and not was_stopped:
            self.add_chat_message("系统", "[OK] 命令执行完成")
        self._cad_command_queue.clear()
        self._cad_timer.stop()
        self._cad_worker = None
        self._cad_execution_active = False
        self._user_requested_stop = False
        self.is_processing = False
        self.set_send_button_state(False)
        self.reset_status()
        if not was_stopped:
            self.update_status_bar("[OK] 处理完成")
    
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

                # 仅在有实质内容时显示（不刷"命令执行结果: True"）
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
    
    def _deferred_init_after_bridge(self):
        """Bridge 启动后再执行慢初始化，避免影响 AIMIND 冷启动探活。"""
        # 先验证数据库连接状态
        self.check_database_connection_at_startup()

        try:
            self.connect_to_acad()
        except Exception as e:
            self.add_chat_message("系统", f"[警告] AutoCAD 连接初始化失败: {str(e)}")

        try:
            self.init_ai_model()
        except Exception as e:
            self.add_chat_message("系统", f"[警告] AI 模型初始化失败: {str(e)}")

        self.update_status_bar("就绪 - 输入指令控制AutoCAD")

    def check_database_connection_at_startup(self):
        """软件启动时验证数据库连接并更新状态指示。"""
        try:
            config_file = os.path.join(os.path.dirname(__file__), "ai_config.json")
            db_cfg = {}
            if os.path.exists(config_file):
                with open(config_file, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
                db_cfg = (cfg or {}).get("database", {}) if isinstance(cfg, dict) else {}

            if not db_cfg.get("enabled"):
                self.db_status_indicator.set_status("disconnected")
                self.db_status_label.setText("书库未启用")
                self.add_chat_message("系统", "[数据库] 数据库配置已预置，当前未启用（可在设置中启用）")
                return

            conn_str = (db_cfg.get("connection_string") or "").strip()
            if not conn_str:
                self.db_status_indicator.set_status("disconnected")
                self.db_status_label.setText("书库配置缺失")
                self.add_chat_message("系统", "[警告] 数据库已启用但连接字符串为空")
                return

            self.db_status_indicator.set_status("processing")
            self.db_status_label.setText("书库连接中...")
            QApplication.processEvents()

            store = ConfigDBStore(conn_str)
            _ = store.get_active_config((db_cfg.get("config_key") or "app/global").strip())

            self.db_status_indicator.set_status("connected")
            self.db_status_label.setText("书库已连接")
            self.add_chat_message("系统", "🗄 知识库数据库连接成功")
        except Exception as e:
            self.db_status_indicator.set_status("disconnected")
            self.db_status_label.setText("书库连接失败")
            self.add_chat_message("系统", f"[警告] 知识库数据库连接失败: {str(e)}")

    def update_status_bar(self, message):
        """更新状态栏"""
        self.statusBarWidget.showMessage(message)

    # ===== IPC Bridge 回调（可能来自非UI线程） =====
    def _bridge_show(self):
        QTimer.singleShot(0, self._show_from_bridge)

    def _bridge_stop(self):
        QTimer.singleShot(0, self.stop_processing)

    def _bridge_chat(self, text: str):
        message = (text or "").strip()
        if not message:
            return "请输入内容"
        self.bridge_chat_signal.emit(message)
        return "请求已提交到 AI，处理中..."

    def _bridge_chat_on_ui(self, message: str):
        self.input_field.setText(message)
        self.send_command()

    def _bridge_get_last_ai(self, since: int = 0):
        has_new = self._bridge_last_ai_seq > int(since or 0)
        return {
            "has_new": has_new,
            "seq": int(self._bridge_last_ai_seq),
            "message": self._bridge_last_ai_message if has_new else ""
        }

    def _show_from_bridge(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self.input_field.setFocus()

    def closeEvent(self, event):
        """关闭事件"""
        if self.acad.is_connected:
            reply = QMessageBox.question(
                self, "确认退出",
                "AutoCAD仍然连接，确定要退出吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                try:
                    if self._cad_worker is not None and self._cad_worker.isRunning():
                        self._cad_worker.stop()
                        self._cad_worker.wait(2000)
                except Exception:
                    pass
                try:
                    self.bridge.stop()
                except Exception:
                    pass
                self.acad.disconnect()
                event.accept()
            else:
                event.ignore()
        else:
            try:
                if self._cad_worker is not None and self._cad_worker.isRunning():
                    self._cad_worker.stop()
                    self._cad_worker.wait(2000)
            except Exception:
                pass
            try:
                self.bridge.stop()
            except Exception:
                pass
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

    def __init__(self, ai_model, command, history=None, context=None):
        super().__init__()
        self.ai_model = ai_model
        self.command = command
        self.history = history or []
        self.context = context or None
        self._stopped = False
        self.request_id = 0
    
    def stop(self):
        """停止线程"""
        self._stopped = True
    
    def run(self):
        """运行线程"""
        try:
            result = self.ai_model.process_command(self.command, self.context)
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
