# AI CAD - AutoCAD智能助手

一款基于AI大模型的AutoCAD智能控制工具，通过自然语言与AI对话，自动执行CAD命令。

## 功能特点

### 🤖 AI智能对话
- 支持多种AI大模型（OpenAI、Azure OpenAI、LM Studio、本地模型）
- 自然语言交互，无需记忆复杂命令
- 智能理解用户意图，自动转换为CAD命令

### 🎨 现代化界面
- 扁平化设计，简洁美观
- 窗口置顶，不遮挡AutoCAD操作
- 支持最大化/最小化/拖动
- 实时状态指示器

### ⚡ 快捷功能
- 常用命令一键执行
- 命令历史记录
- 双击功能树快速执行

### 🔧 AutoCAD集成
- 自动连接运行中的AutoCAD
- 支持AutoCAD命令执行
- 实时反馈执行状态

## 快速开始

### 环境要求
- Python 3.8+
- AutoCAD 2018+

### 安装依赖
```bash
pip install PyQt6 pywin32 requests
```

### 启动程序
```bash
python main_ai_cad.py
```

### 使用方法
1. 启动AutoCAD
2. 运行AI CAD程序，自动连接AutoCAD
3. 在设置中配置AI模型（API Key等）
4. 在输入框输入自然语言指令，如：
   - "画一个圆形"
   - "绘制一条直线"
   - "如何标注尺寸？"

## 项目结构

```
AutoOffice/
├── main_ai_cad.py        # 主程序入口
├── ai_model.py           # AI模型接口
├── autocad_controller.py # AutoCAD控制器
├── config_manager.py     # 配置管理
├── ai_config.json        # AI模型配置
├── config.ini            # 程序配置
├── requirements.txt      # 依赖列表
├── acad/
│   └── AI_CAD.lsp        # AutoCAD插件入口
└── ui/
    ├── __init__.py
    └── settings_window.py # 设置窗口
```

## 配置AI模型

### LM Studio（本地模型）
1. 下载并安装LM Studio
2. 加载支持的模型（如Qwen、Gemma等）
3. 启动本地服务器（默认端口1234）
4. 在设置中添加模型配置：
   - 类型：LM Studio
   - 端点：http://localhost:1234/v1
   - API Key：从LM Studio获取

### OpenAI
1. 获取OpenAI API Key
2. 在设置中添加模型配置：
   - 类型：OpenAI
   - API Key：sk-xxx
   - 模型：gpt-4 / gpt-3.5-turbo

## 快捷键

- `Enter` - 发送消息
- `双击标题栏` - 最大化/还原窗口

## 状态指示

- 🟢 绿色 - 已连接AutoCAD
- 🔴 红色 - 未连接
- 🔵 蓝色旋转 - 正在处理中

## 许可证

MIT License
