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

## 方案C（长期架构）：AutoCAD C# DLL + Python UI保留

你当前项目已支持该架构的第一版骨架：

- Python UI 继续作为主交互界面（`main_ai_cad.py`）
- Python UI 内嵌本地桥接服务（`ipc_bridge.py`，默认 `http://127.0.0.1:8765`）
- AutoCAD 侧使用 C# 插件 DLL（`acad/AutoCADMindAI.Plugin.cs`）

### Python Bridge API

- `GET /health`：健康检查
- `POST /show`：显示并激活 Python UI
- `POST /chat`：发送文本到 UI（等价于用户输入后点发送）
- `POST /stop`：触发 UI 停止逻辑

请求示例：

```json
{"text":"绘制一个圆形"}
```

### AutoCAD C# 插件命令

当前示例提供三个命令：

- `AIMIND`：确保 Python UI 启动并显示
- `AICHAT`：在 AutoCAD 命令行输入一句话并转发给 Python UI
- `AISTOP`：请求停止

### 一键编译 / 一键打包（推荐）

项目根目录新增了两个脚本：

- `build_plugin.bat`：一键编译 C# 插件 DLL
- `package_release.bat`：一键打包可交付目录（自动先编译）

> 首次使用如果提示找不到 MSBuild，请安装 Build Tools for Visual Studio（MSBuild + .NET Framework 4.8）。

### 给新手的最简使用方式（推荐）

你只需要记住 AutoCAD 的一个命令：`NETLOAD`

1. 把下面 4 个文件放到同一个目录：
   - `AutoCADMindAI.Plugin.dll`
   - `main_ai_cad.py`
   - `start.py`
   - `start.bat`
2. 在 AutoCAD 命令行输入 `NETLOAD`，选择并加载 `AutoCADMindAI.Plugin.dll`
3. 加载后，Ribbon 顶部会出现 `MindAI` 选项卡（按钮：打开AI / 发送到AI / 停止）
4. 推荐命令顺序：`AISTART`（启动Python）→ `AIPING`（检查桥接）→ `AIMIND`（唤起窗口）
5. 你也可以使用：`AICHAT` / `AISTOP`

> 插件会自动在 DLL 同目录寻找 `start.bat`/`start.py`，不需要手改 Python 路径。

### 构建 C# 插件（开发者）

1. 使用 Visual Studio 打开 `acad/AutoCADMindAI.Plugin.csproj`
2. 按本机 AutoCAD 安装目录修改 `AcMgd.dll / AcDbMgd.dll` 的 `HintPath`
3. 编译生成 `AutoCADMindAI.Plugin.dll`
4. 将 DLL 复制到你的部署目录后，按上面的 `NETLOAD` 步骤使用

## 许可证

MIT License
