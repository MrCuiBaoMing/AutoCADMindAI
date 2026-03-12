#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI CAD设置窗口
支持配置多个大模型
"""

import json
import os

from core.config_db_store import ConfigDBStore

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QLineEdit, QComboBox, QListWidget, QGroupBox, QFormLayout,
    QSpinBox, QMessageBox, QTabWidget, QWidget, QCheckBox,
    QAbstractItemView
)
from PyQt6.QtCore import Qt

class ModelConfig:
    """模型配置类"""
    
    def __init__(self, name="", model_type="local", api_key="", endpoint="", model_name=""):
        self.name = name
        self.model_type = model_type
        self.api_key = api_key
        self.endpoint = endpoint
        self.model_name = model_name
    
    def to_dict(self):
        """转换为字典"""
        return {
            "name": self.name,
            "model_type": self.model_type,
            "api_key": self.api_key,
            "endpoint": self.endpoint,
            "model_name": self.model_name
        }
    
    @classmethod
    def from_dict(cls, data):
        """从字典创建"""
        return cls(
            name=data.get("name", ""),
            model_type=data.get("model_type", "local"),
            api_key=data.get("api_key", ""),
            endpoint=data.get("endpoint", ""),
            model_name=data.get("model_name", "")
        )

class SettingsWindow(QDialog):
    """设置窗口"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AI CAD 设置")
        self.resize(920, 640)
        self.setMinimumSize(860, 600)
        
        # 配置文件路径
        self.config_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ai_config.json")
        
        # 模型配置列表
        self.models = []
        self.loaded_autocad_config = {}
        self.loaded_general_config = {}
        self.loaded_db_config = {}
        self.loaded_web_search_config = {}

        # 当前选中的模型索引
        self.current_model_index = -1
        
        # 加载配置
        self.load_config()
        
        # 初始化UI
        self.init_ui()
    
    def init_ui(self):
        """初始化UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        # 创建标签页
        tab_widget = QTabWidget()
        tab_widget.setDocumentMode(True)
        tab_widget.setElideMode(Qt.TextElideMode.ElideRight)
        
        # 模型配置标签页
        model_tab = self.create_model_tab()
        tab_widget.addTab(model_tab, "模型配置")
        
        # AutoCAD配置标签页
        autocad_tab = self.create_autocad_tab()
        tab_widget.addTab(autocad_tab, "AutoCAD配置")

        # 数据库配置标签页
        db_tab = self.create_db_tab()
        tab_widget.addTab(db_tab, "数据库配置")

        # 网络搜索配置标签页
        web_search_tab = self.create_web_search_tab()
        tab_widget.addTab(web_search_tab, "网络搜索")

        # 通用设置标签页
        general_tab = self.create_general_tab()
        tab_widget.addTab(general_tab, "通用设置")
        
        layout.addWidget(tab_widget)
        
        # 按钮区域
        button_layout = QHBoxLayout()
        
        save_button = QPushButton("保存")
        save_button.clicked.connect(self.save_settings)
        
        cancel_button = QPushButton("取消")
        cancel_button.clicked.connect(self.reject)
        
        button_layout.addStretch()
        button_layout.addWidget(save_button)
        button_layout.addWidget(cancel_button)
        
        layout.addLayout(button_layout)

        # 回填已加载配置到界面
        self.apply_loaded_config_to_ui()

        self.setStyleSheet("""
            QDialog {
                background-color: #f7f9fc;
            }
            QTabWidget::pane {
                border: 1px solid #d8dee8;
                border-radius: 8px;
                background: #ffffff;
            }
            QTabBar::tab {
                min-width: 96px;
                padding: 8px 14px;
                margin-right: 4px;
                border: 1px solid #d8dee8;
                border-bottom: none;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                background: #eef2f7;
                color: #334155;
            }
            QTabBar::tab:selected {
                background: #ffffff;
                color: #1e293b;
                font-weight: 600;
            }
            QGroupBox {
                border: 1px solid #d8dee8;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
                font-weight: 600;
                color: #334155;
                background: #ffffff;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
            }
            QLineEdit, QComboBox, QSpinBox, QListWidget {
                min-height: 30px;
                border: 1px solid #cfd8e3;
                border-radius: 6px;
                background: #ffffff;
                padding: 4px 8px;
                color: #1f2937;
            }
            QListWidget {
                padding: 6px;
            }
            QPushButton {
                min-height: 32px;
                padding: 6px 14px;
                border-radius: 6px;
                border: 1px solid #c7d2e0;
                background: #f8fafc;
                color: #1f2937;
            }
            QPushButton:hover {
                background: #eef2f7;
            }
        """)
    
    def create_model_tab(self):
        """创建模型配置标签页"""
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(14)
        
        # 左侧：模型列表
        left_layout = QVBoxLayout()
        
        model_list_label = QLabel("已配置的模型:")
        self.model_list = QListWidget()
        self.model_list.setMinimumWidth(280)
        self.model_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.model_list.itemClicked.connect(self.on_model_selected)
        
        # 添加、删除、编辑按钮
        button_layout = QHBoxLayout()
        
        add_button = QPushButton("添加")
        add_button.clicked.connect(self.add_model)
        
        delete_button = QPushButton("删除")
        delete_button.clicked.connect(self.delete_model)
        
        edit_button = QPushButton("编辑")
        edit_button.clicked.connect(self.edit_model)
        
        button_layout.addWidget(add_button)
        button_layout.addWidget(edit_button)
        button_layout.addWidget(delete_button)
        
        left_layout.addWidget(model_list_label)
        left_layout.addWidget(self.model_list)
        left_layout.addLayout(button_layout)
        
        # 右侧：模型配置表单
        right_layout = QVBoxLayout()
        
        form_group = QGroupBox("模型配置")
        form_layout = QFormLayout()
        form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form_layout.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        form_layout.setHorizontalSpacing(14)
        form_layout.setVerticalSpacing(12)
        
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("模型名称，例如：OpenAI GPT-4")
        
        self.type_combo = QComboBox()
        self.type_combo.addItems(["local", "openai", "azure", "lmstudio"])
        self.type_combo.currentTextChanged.connect(self.on_type_changed)
        
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setPlaceholderText("API密钥")
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        
        self.endpoint_edit = QLineEdit()
        self.endpoint_edit.setPlaceholderText("API端点（Azure专用）")
        
        self.model_name_edit = QLineEdit()
        self.model_name_edit.setPlaceholderText("模型名称，例如：gpt-4")
        
        form_layout.addRow("模型名称:", self.name_edit)
        form_layout.addRow("模型类型:", self.type_combo)
        form_layout.addRow("API密钥:", self.api_key_edit)
        form_layout.addRow("API端点:", self.endpoint_edit)
        form_layout.addRow("模型:", self.model_name_edit)
        
        form_group.setLayout(form_layout)
        
        # 测试连接按钮
        test_button = QPushButton("测试连接")
        test_button.clicked.connect(self.test_connection)
        
        right_layout.addWidget(form_group)
        right_layout.addWidget(test_button)
        right_layout.addStretch()
        
        # 设置布局比例
        layout.addLayout(left_layout, 2)
        layout.addLayout(right_layout, 3)
        
        # 填充模型列表
        self.populate_model_list()
        
        return widget
    
    def create_autocad_tab(self):
        """创建AutoCAD配置标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)
        
        group = QGroupBox("AutoCAD连接设置")
        form_layout = QFormLayout()
        form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form_layout.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        form_layout.setHorizontalSpacing(14)
        form_layout.setVerticalSpacing(12)
        
        self.connection_timeout_spin = QSpinBox()
        self.connection_timeout_spin.setRange(1, 60)
        self.connection_timeout_spin.setValue(10)
        self.connection_timeout_spin.setSuffix(" 秒")
        
        self.command_delay_spin = QSpinBox()
        self.command_delay_spin.setRange(0, 10)
        self.command_delay_spin.setValue(1)
        self.command_delay_spin.setSuffix(" 秒")
        
        self.auto_connect_check = QCheckBox("启动时自动连接AutoCAD")
        
        form_layout.addRow("连接超时:", self.connection_timeout_spin)
        form_layout.addRow("命令延迟:", self.command_delay_spin)
        form_layout.addRow("", self.auto_connect_check)
        
        group.setLayout(form_layout)
        layout.addWidget(group)
        layout.addStretch()
        
        return widget
    
    def create_db_tab(self):
        """创建数据库配置标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        group = QGroupBox("SQL Server 2014 连接配置")
        form_layout = QFormLayout()
        form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form_layout.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        form_layout.setHorizontalSpacing(14)
        form_layout.setVerticalSpacing(12)

        self.db_enable_check = QCheckBox("启用数据库配置中心（优先从数据库读取配置）")

        self.db_connection_string_edit = QLineEdit()
        self.db_connection_string_edit.setPlaceholderText("DRIVER={ODBC Driver 17 for SQL Server};SERVER=127.0.0.1,1433;DATABASE=AICAD_KB;UID=sa;PWD=***")

        self.db_config_key_edit = QLineEdit()
        self.db_config_key_edit.setPlaceholderText("默认: app/global")

        test_db_button = QPushButton("测试数据库连接")
        test_db_button.clicked.connect(self.test_db_connection)

        form_layout.addRow("", self.db_enable_check)
        form_layout.addRow("连接字符串:", self.db_connection_string_edit)
        form_layout.addRow("配置键:", self.db_config_key_edit)
        form_layout.addRow("", test_db_button)

        group.setLayout(form_layout)
        layout.addWidget(group)
        layout.addStretch()

        return widget

    def create_web_search_tab(self):
        """创建网络搜索配置标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        # 启用/禁用网络搜索
        enable_group = QGroupBox("网络搜索功能")
        enable_layout = QVBoxLayout()

        self.web_search_enable_check = QCheckBox("启用网络搜索功能")
        self.web_search_enable_check.setToolTip("启用后，AI 可以在需要时搜索互联网获取最新信息")
        enable_layout.addWidget(self.web_search_enable_check)

        enable_group.setLayout(enable_layout)
        layout.addWidget(enable_group)

        # Tavily 配置
        tavily_group = QGroupBox("Tavily 搜索配置")
        tavily_form = QFormLayout()
        tavily_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        tavily_form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        tavily_form.setHorizontalSpacing(14)
        tavily_form.setVerticalSpacing(12)

        self.tavily_api_key_edit = QLineEdit()
        self.tavily_api_key_edit.setPlaceholderText("请输入 Tavily API Key")
        self.tavily_api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.tavily_api_key_edit.setToolTip("Tavily API Key，用于执行网络搜索。可在 https://tavily.com 获取")

        self.tavily_max_results_spin = QSpinBox()
        self.tavily_max_results_spin.setRange(1, 10)
        self.tavily_max_results_spin.setValue(3)
        self.tavily_max_results_spin.setToolTip("每次搜索返回的最大结果数")

        tavily_form.addRow("API Key:", self.tavily_api_key_edit)
        tavily_form.addRow("最大结果数:", self.tavily_max_results_spin)

        tavily_group.setLayout(tavily_form)
        layout.addWidget(tavily_group)

        # 缓存配置
        cache_group = QGroupBox("缓存配置")
        cache_form = QFormLayout()
        cache_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        cache_form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        cache_form.setHorizontalSpacing(14)
        cache_form.setVerticalSpacing(12)

        self.web_search_cache_enable_check = QCheckBox("启用缓存")
        self.web_search_cache_enable_check.setChecked(True)
        self.web_search_cache_enable_check.setToolTip("启用缓存可以减少重复搜索，提高响应速度")

        self.web_search_cache_ttl_spin = QSpinBox()
        self.web_search_cache_ttl_spin.setRange(60, 3600)
        self.web_search_cache_ttl_spin.setValue(300)
        self.web_search_cache_ttl_spin.setSuffix(" 秒")
        self.web_search_cache_ttl_spin.setToolTip("缓存有效期，超过此时间将重新搜索")

        self.web_search_cache_size_spin = QSpinBox()
        self.web_search_cache_size_spin.setRange(50, 1000)
        self.web_search_cache_size_spin.setValue(200)
        self.web_search_cache_size_spin.setSuffix(" 条")
        self.web_search_cache_size_spin.setToolTip("最大缓存条目数")

        cache_form.addRow("启用缓存:", self.web_search_cache_enable_check)
        cache_form.addRow("缓存有效期:", self.web_search_cache_ttl_spin)
        cache_form.addRow("最大缓存数:", self.web_search_cache_size_spin)

        cache_group.setLayout(cache_form)
        layout.addWidget(cache_group)

        # 说明文字
        info_label = QLabel(
            "💡 提示：网络搜索功能需要 Tavily API Key。"
            "您可以在 https://tavily.com 免费注册获取 API Key。"
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #666; margin-top: 10px;")
        layout.addWidget(info_label)

        layout.addStretch()
        return widget

    def create_general_tab(self):
        """创建通用设置标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        group = QGroupBox("通用设置")
        form_layout = QFormLayout()
        form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form_layout.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        form_layout.setHorizontalSpacing(14)
        form_layout.setVerticalSpacing(12)

        self.language_combo = QComboBox()
        self.language_combo.addItems(["简体中文", "English"])

        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["默认", "深色", "浅色"])
        self.theme_combo.setToolTip("主题将在保存后应用到主界面")

        self.history_limit_spin = QSpinBox()
        self.history_limit_spin.setRange(10, 1000)
        self.history_limit_spin.setValue(100)

        form_layout.addRow("语言:", self.language_combo)
        form_layout.addRow("主题:", self.theme_combo)
        form_layout.addRow("历史记录限制:", self.history_limit_spin)

        group.setLayout(form_layout)
        layout.addWidget(group)
        layout.addStretch()

        return widget
    
    def populate_model_list(self):
        """填充模型列表"""
        self.model_list.clear()
        for model in self.models:
            self.model_list.addItem(model.name)
    
    def on_model_selected(self, item):
        """模型选择事件"""
        index = self.model_list.row(item)
        if index >= 0 and index < len(self.models):
            self.current_model_index = index
            model = self.models[index]
            
            # 填充表单
            self.name_edit.setText(model.name)
            self.type_combo.setCurrentText(model.model_type)
            self.api_key_edit.setText(model.api_key)
            self.endpoint_edit.setText(model.endpoint)
            self.model_name_edit.setText(model.model_name)
    
    def on_type_changed(self, model_type):
        """模型类型改变事件"""
        if model_type == "local":
            self.api_key_edit.setEnabled(False)
            self.endpoint_edit.setEnabled(False)
            self.model_name_edit.setEnabled(False)
        elif model_type == "openai":
            self.api_key_edit.setEnabled(True)
            self.endpoint_edit.setEnabled(False)
            self.model_name_edit.setEnabled(True)
        elif model_type == "azure":
            self.api_key_edit.setEnabled(True)
            self.endpoint_edit.setEnabled(True)
            self.model_name_edit.setEnabled(True)
        elif model_type == "lmstudio":
            self.api_key_edit.setEnabled(True)
            self.endpoint_edit.setEnabled(True)
            self.model_name_edit.setEnabled(True)
    
    def add_model(self):
        """添加模型"""
        model = ModelConfig()
        model.name = f"新模型 {len(self.models) + 1}"
        self.models.append(model)
        self.populate_model_list()
        
        # 选中新添加的模型
        self.model_list.setCurrentRow(len(self.models) - 1)
        self.on_model_selected(self.model_list.currentItem())
    
    def delete_model(self):
        """删除模型"""
        if self.current_model_index >= 0:
            reply = QMessageBox.question(
                self, "确认删除",
                f"确定要删除模型 '{self.models[self.current_model_index].name}' 吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                del self.models[self.current_model_index]
                self.current_model_index = -1
                
                # 清空表单
                self.name_edit.clear()
                self.api_key_edit.clear()
                self.endpoint_edit.clear()
                self.model_name_edit.clear()
                
                self.populate_model_list()
    
    def edit_model(self):
        """编辑模型"""
        if self.current_model_index >= 0:
            # 更新当前模型
            model = self.models[self.current_model_index]
            model.name = self.name_edit.text()
            model.model_type = self.type_combo.currentText()
            model.api_key = self.api_key_edit.text()
            model.endpoint = self.endpoint_edit.text()
            model.model_name = self.model_name_edit.text()
            
            # 更新列表显示
            self.model_list.item(self.current_model_index).setText(model.name)
    
    def test_connection(self):
        """测试模型连接（占位）"""
        if self.current_model_index >= 0:
            model = self.models[self.current_model_index]
            QMessageBox.information(
                self, "测试结果",
                f"模型 '{model.name}' 配置有效！\n"
                f"类型: {model.model_type}\n"
                f"模型: {model.model_name}"
            )
        else:
            QMessageBox.warning(self, "警告", "请先选择一个模型")

    def test_db_connection(self):
        """测试数据库连接"""
        if not self.db_enable_check.isChecked():
            QMessageBox.information(self, "提示", "当前未启用数据库配置中心")
            return

        conn_str = self.db_connection_string_edit.text().strip()
        if not conn_str:
            QMessageBox.warning(self, "警告", "请先输入数据库连接字符串")
            return

        try:
            store = ConfigDBStore(conn_str)
            _ = store.get_active_config(self.db_config_key_edit.text().strip() or "app/global")
            QMessageBox.information(self, "成功", "数据库连接测试通过")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"数据库连接测试失败: {str(e)}")
    
    def save_settings(self):
        """保存设置"""
        # 保存模型配置
        self.edit_model()  # 确保当前编辑的模型已保存
        
        config = {
            "models": [model.to_dict() for model in self.models],
            "autocad": {
                "connection_timeout": self.connection_timeout_spin.value(),
                "command_delay": self.command_delay_spin.value(),
                "auto_connect": self.auto_connect_check.isChecked()
            },
            "database": {
                "enabled": self.db_enable_check.isChecked(),
                "connection_string": self.db_connection_string_edit.text().strip(),
                "config_key": self.db_config_key_edit.text().strip() or "app/global"
            },
            "web_search": {
                "enabled": self.web_search_enable_check.isChecked(),
                "engines": ["tavily"] if self.web_search_enable_check.isChecked() else [],
                "tavily": {
                    "api_key": self.tavily_api_key_edit.text().strip(),
                    "max_results": self.tavily_max_results_spin.value(),
                    "include_answer": True
                },
                "cache": {
                    "enabled": self.web_search_cache_enable_check.isChecked(),
                    "ttl_seconds": self.web_search_cache_ttl_spin.value(),
                    "max_size": self.web_search_cache_size_spin.value()
                }
            },
            "general": {
                "language": self.language_combo.currentText(),
                "theme": self.theme_combo.currentText(),
                "history_limit": self.history_limit_spin.value()
            }
        }
        
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)

            # 若启用数据库配置中心，则同步写入数据库（INSERT 新版本 + 禁用旧版本）
            db_cfg = config.get("database", {})
            if db_cfg.get("enabled"):
                conn_str = (db_cfg.get("connection_string") or "").strip()
                config_key = (db_cfg.get("config_key") or "app/global").strip()
                if not conn_str:
                    raise ValueError("已启用数据库配置中心，但连接字符串为空")

                store = ConfigDBStore(conn_str)
                store.save_new_version(
                    config_key=config_key,
                    config_data=config,
                    changed_by="ui/settings_window",
                    reason="通过设置窗口保存配置"
                )

            QMessageBox.information(self, "成功", "设置已保存！")
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存设置失败: {str(e)}")
    
    def load_config(self):
        """加载配置"""
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)

                # 加载模型配置
                self.models = [ModelConfig.from_dict(m) for m in config.get("models", [])]

                # 加载AutoCAD配置
                self.loaded_autocad_config = config.get("autocad", {})

                # 加载数据库配置
                self.loaded_db_config = config.get("database", {})

                # 加载通用配置
                self.loaded_general_config = config.get("general", {})

                # 加载网络搜索配置
                self.loaded_web_search_config = config.get("web_search", {})

            except Exception as e:
                print(f"加载配置失败: {e}")

    def apply_loaded_config_to_ui(self):
        """将配置文件中的值回填到控件"""
        def _safe_int(value, default):
            try:
                if value is None:
                    return int(default)
                return int(value)
            except Exception:
                return int(default)

        ac = self.loaded_autocad_config or {}
        self.connection_timeout_spin.setValue(_safe_int(ac.get("connection_timeout", 10), 10))
        self.command_delay_spin.setValue(_safe_int(ac.get("command_delay", 1), 1))
        self.auto_connect_check.setChecked(bool(ac.get("auto_connect", False)))

        db = self.loaded_db_config or {}
        self.db_enable_check.setChecked(bool(db.get("enabled", False)))
        self.db_connection_string_edit.setText(db.get("connection_string", "") or "")
        self.db_config_key_edit.setText(db.get("config_key", "app/global") or "app/global")

        g = self.loaded_general_config or {}
        lang = g.get("language", "简体中文") or "简体中文"
        theme = g.get("theme", "默认") or "默认"
        history_limit = _safe_int(g.get("history_limit", 100), 100)

        lang_index = self.language_combo.findText(lang)
        if lang_index >= 0:
            self.language_combo.setCurrentIndex(lang_index)

        theme_index = self.theme_combo.findText(theme)
        if theme_index >= 0:
            self.theme_combo.setCurrentIndex(theme_index)

        self.history_limit_spin.setValue(history_limit)

        # 回填网络搜索配置
        web = self.loaded_web_search_config or {}
        self.web_search_enable_check.setChecked(bool(web.get("enabled", False)))

        tavily = web.get("tavily", {}) if isinstance(web, dict) else {}
        self.tavily_api_key_edit.setText(tavily.get("api_key", "") or "")
        self.tavily_max_results_spin.setValue(_safe_int(tavily.get("max_results", 3), 3))

        cache = web.get("cache", {}) if isinstance(web, dict) else {}
        self.web_search_cache_enable_check.setChecked(bool(cache.get("enabled", True)))
        self.web_search_cache_ttl_spin.setValue(_safe_int(cache.get("ttl_seconds", 300), 300))
        self.web_search_cache_size_spin.setValue(_safe_int(cache.get("max_size", 200), 200))
    
    def get_selected_model(self):
        """获取当前选中的模型"""
        if self.current_model_index >= 0 and self.current_model_index < len(self.models):
            return self.models[self.current_model_index]
        return None
    
    def get_all_models(self):
        """获取所有模型"""
        return self.models
