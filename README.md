# AI CAD - AutoCAD 智能助手

AutoCADMindAI 是一个基于 AI 大模型的 AutoCAD 智能助手：
通过自然语言与 AI 对话，自动生成 AutoCAD 命令并驱动 AutoCAD 执行。
它支持本地模型、OpenAI/Azure OpenAI、LM Studio 等多种模型，并且可与 AutoCAD 通过 COM + 本地 HTTP 桥无缝联动。

---

## ✅ 核心特性

### 🧠 智能语义驱动（自然语言→AutoCAD命令）
- 用户输入“画一个圆形、半径 10”即可自动生成 `CIRCLE` 命令并执行
- 可选择多种大模型：本地规则模型 / LM Studio / OpenAI / Azure OpenAI
- 支持命令型响应（`intent=command`）与对话型响应（`intent=chat`）

### 🧩 AutoCAD 集成
- 自动连接正在运行的 AutoCAD（兼容多版本）
- 通过 `SendCommand` + `SendStringToExecute` 执行命令
- 支持“停止”/“取消”命令（通过 COM 取消 + 键盘消息双保险）

### 🌐 本地桥接服务（HTTP）
- AutoCAD C# 插件可通过 HTTP 调用 Python UI（`/show`、`/chat`、`/stop`）
- 让 AI 助手与 AutoCAD 操作在同一窗口中协同工作

### 📚 企业知识库支持（可选）
- 集成 SQL Server 知识库检索（带领域/文档/章节级交互）
- 支持「问公司标准/流程」类型问答，自动进行知识库检索

---

## 🚀 快速上手

### 1) 环境要求
- Windows + AutoCAD 2018+
- Python 3.8+
- 推荐使用 `venv` 或其他虚拟环境

### 2) 安装依赖
```powershell
pip install -r requirements.txt
``` 
（如果没有 `requirements.txt`，可单独安装：`PyQt6 pywin32 requests`）

### 3) 启动方式
#### (A) 直接运行 Python UI：
```powershell
python main_ai_cad.py
```

#### (B) 从 AutoCAD 侧启动（推荐）
1. 运行 `build_plugin.bat` 编译插件（或直接使用已编译的 `AutoCADMindAI.Plugin.dll`）
2. 在 AutoCAD 命令行输入：
   - `NETLOAD` → 选择 `AutoCADMindAI.Plugin.dll`
3. 执行命令：
   - `AIMIND`：打开 AI 窗口（推荐）
   - `AICHAT`：输入一句话发送给 AI
   - `AISTOP`：停止当前执行

> 插件会自动在 DLL 同目录寻找 `start.py`/`start.bat`，无需手动修改路径。

---

## 🧱 项目目录说明

```
AutoCADMindAI/
├── main_ai_cad.py             # 主程序入口（PyQt6 UI + 逻辑）
├── ai_model.py                # AI 模型适配层（OpenAI / Azure / LM Studio / 本地）
├── autocad_controller.py      # AutoCAD COM 控制器（执行命令 / 取消命令）
├── ipc_bridge.py              # 本地 HTTP 桥（供 C# 插件调用）
├── core/                      # 核心流程（意图识别 + 编排 + 配置中心）
│   ├── orchestrator.py        # 业务流程编排（KB/命令/对话路由）
│   ├── ai_intent_analyzer.py  # AI 意图分析器
│   └── config_db_store.py     # SQL Server 配置中心
├── connectors/                # 各类外部数据源（知识库等）
│   └── kb_sqlserver/          # SQL Server 知识库检索实现
├── ui/                        # UI 窗口 & 设置
│   └── settings_window.py
├── acad/                      # AutoCAD C# 插件项目
│   └── AutoCADMindAI.Plugin.cs
├── ai_config.json             # 模型 / AutoCAD / 数据库配置
├── config.ini                 # 窗口尺寸+连接配置（简单持久化）
├── requirements.txt           # Python 依赖（可用 pip install -r）
└── README.md                  # 本文档
```

---

## ⚙️ 配置说明（关键）

### `ai_config.json`（首选配置）
- **models**：多模型配置列表（本地/OpenAI/Azure/LM Studio）
- **autocad**：连接超时、命令执行延迟、是否自动连接
- **database**：知识库（SQL Server）启用配置
- **general**：主题、语言、对话历史长度

> 程序会优先从数据库配置中心读取（如果启用了 `database.enabled`），否则使用本地 `ai_config.json`。

#### 典型 LM Studio 配置
```json
{
  "model_type": "lmstudio",
  "endpoint": "http://localhost:1234/v1",
  "api_key": "",
  "model_name": "qwen/qwen3-4b-thinking-2507"
}
```

---

## 🛠️ 各模块功能说明（快速定位）

### 🔹 AI 模型层（`ai_model.py`）
- 统一接口 `process_command()` 和异步 `get_request_params()`
- 支持多种模型：本地规则 / OpenAI / Azure / LM Studio
- LM Studio 输出 JSON 格式 (`intent`/`response`/`commands`)，从而安全判断是否执行 CAD 命令

### 🔹 AutoCAD 控制层（`autocad_controller.py`）
- 通过 COM 连接 AutoCAD
- 管理命令发送、文档刷新、失败重试
- 提供强制取消：COM `^C^C` + 键盘 `ESC`（确保可以中断长时间执行的命令）

### 🔹 流程编排层（`core/orchestrator.py`）
- 意图识别 → 路由到知识库/命令/对话
- 支持多轮引导：选择领域、文档、章节，用自然语言继续筛选
- 与知识库检索结合，输出“知识库摘要 + 引用来源”

### 🔹 本地桥接（`ipc_bridge.py`）
- 本地 HTTP 服务（`127.0.0.1:8765`）
- 提供 UI 展示 / 停止 / 发送请求接口

### 🔹 AutoCAD 插件（`acad/AutoCADMindAI.Plugin.cs`）
- AutoCAD 命令宏：AIMIND/AICHAT/AISTOP 等
- 负责启动 Python UI 并检查桥接是否就绪

---

## 📌 常见使用场景

### ✅ 快速绘图（直接发 CAD 命令）
```text
请帮我画一个半径 10 的圆
```

### ✅ 问公司流程/标准（知识库检索）
```text
公司中线CAD的节点标注规范是什么？
```

### ✅ 核心调试命令（AutoCAD）
- `AIPING`：检查桥接服务是否可用
- `AISTOP`：停止当前执行

---

## 🧩 进阶扩展建议
- 🚀 让插件支持“命令预览 + 确认执行”模式，避免误操作
- 🧠 增强意图判断（如：`execute`/`ask` 模式区分）
- 📦 打包为独立可执行（PyInstaller + 安装器）
- 🌐 增加外部搜索（Web/ERP/文件检索）能力

---

## 📄 许可证
MIT License
