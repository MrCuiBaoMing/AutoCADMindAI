# AutoCADMindAI 企业级知识与业务扩展改造方案（SQL Server 2014）

> 目标升级：不再局限“中线CAD”，而是建设**面向全公司**的统一智能能力底座，支持：
>
> 1. 企业知识库问答（SOP/制度/规范/作业指导书）
> 2. CAD 领域专业问答与可控执行
> 3. 金蝶 ERP API 对接（Token + 业务API调用）
> 4. 局域网共享文件自动检索（资料室/共享盘）
>
> 核心要求：**高扩展性、可配置、可审计、可灰度上线**。

---

## 1. 结合当前项目的现状与可扩展改造方向

当前项目核心模块：

- `main_ai_cad.py`：主 UI、对话流程、`intent=command` 才执行 CAD（关键安全门）
- `ai_model.py`：模型适配层（OpenAI/Azure/LMStudio/Local）
- `autocad_controller.py`：CAD 命令执行/取消
- `ipc_bridge.py`：本地 HTTP Bridge
- `ui/settings_window.py`：已有设置窗口基础

### 当前优势（可直接复用）

1. **已有意图执行闸门**：`intent == command` 才下发 CAD。
2. **已有多轮上下文**：`_chat_history` 可用于注入检索证据。
3. **已有模型抽象层**：便于新增“工具调用编排（知识库/ERP/文件检索）”。

### 当前缺口（本次需要补齐）

1. 没有统一“知识/工具”路由层（现在是直接问模型）
2. 没有数据库连接配置（尤其 SQL Server 2014）
3. 没有 ERP 对接框架（Token 生命周期、API 目录）
4. 没有共享目录检索能力（UNC 路径）

---

## 2. 总体架构（面向全公司，不限中线CAD）

建议采用“**能力插件化 + 统一编排层**”架构：

```text
用户输入
  -> 意图识别/任务编排 Orchestrator
      -> KB Retriever（SQL Server）
      -> ERP Connector（金蝶 API）
      -> File Finder（局域网共享检索）
      -> CAD Executor（仅 intent=command）
  -> 结果合成（带来源）
  -> UI 展示 / Bridge 返回
```

### 设计原则

1. **能力解耦**：知识库、ERP、文件检索、CAD 执行独立模块
2. **配置驱动**：所有连接参数可在 Python 端设置窗口配置
3. **可插拔**：后续接 OA/MES/PLM 只需新增 Connector
4. **审计闭环**：每次检索/调用/回答都可追踪

---

## 3. 新增模块目录建议（扩展优先）

```text
core/
  orchestrator.py            # 统一任务编排（最核心）
  intent_router.py           # 多域意图识别（规则+模型）
  response_composer.py       # 统一输出模板（含引用/来源）

connectors/
  kb_sqlserver/
    db.py
    repository.py
    retriever.py
    schema.sql
    ingest.py
  erp_kingdee/
    client.py                # token获取/刷新、API调用
    apis.py                  # API目录与参数协议
    mapping.py               # 自然语言到ERP字段映射
  file_share/
    finder.py                # UNC共享目录检索
    indexer.py               # 可选：离线索引加速

config/
  app_config.json            # 总配置（模型、KB、ERP、共享目录）
  secrets.local.json         # 可选：敏感信息单独存放（不入库）

ui/
  settings_window.py         # 扩展配置页签：模型/KB/ERP/共享目录
```

---

## 4. SQL Server 2014 知识库设计（全公司通用版）

> 不仅 CAD，支持制度、流程、质检、采购、仓储、财务等多域文档。

## 4.1 域与文档

```sql
CREATE TABLE dbo.kb_domain (
    domain_id BIGINT IDENTITY(1,1) PRIMARY KEY,
    domain_code NVARCHAR(50) NOT NULL UNIQUE,      -- CAD/HR/FIN/PROC/QA...
    domain_name NVARCHAR(100) NOT NULL,
    is_active BIT NOT NULL DEFAULT 1,
    created_at DATETIME NOT NULL DEFAULT GETDATE()
);

CREATE TABLE dbo.kb_document (
    doc_id BIGINT IDENTITY(1,1) PRIMARY KEY,
    domain_id BIGINT NOT NULL,
    doc_code NVARCHAR(64) NOT NULL UNIQUE,
    title NVARCHAR(300) NOT NULL,
    category NVARCHAR(100) NOT NULL,
    source_type NVARCHAR(20) NOT NULL,             -- pdf/word/md/url
    source_path NVARCHAR(500) NULL,
    owner_dept NVARCHAR(100) NULL,
    status TINYINT NOT NULL DEFAULT 1,
    current_version_id BIGINT NULL,
    created_at DATETIME NOT NULL DEFAULT GETDATE(),
    updated_at DATETIME NOT NULL DEFAULT GETDATE(),
    CONSTRAINT FK_kb_doc_domain FOREIGN KEY(domain_id) REFERENCES dbo.kb_domain(domain_id)
);
```

## 4.2 版本与分块

```sql
CREATE TABLE dbo.kb_document_version (
    version_id BIGINT IDENTITY(1,1) PRIMARY KEY,
    doc_id BIGINT NOT NULL,
    version_no NVARCHAR(50) NOT NULL,
    effective_date DATETIME NOT NULL,
    expire_date DATETIME NULL,
    is_active BIT NOT NULL DEFAULT 1,
    change_summary NVARCHAR(MAX) NULL,
    created_at DATETIME NOT NULL DEFAULT GETDATE(),
    CONSTRAINT FK_kb_ver_doc FOREIGN KEY(doc_id) REFERENCES dbo.kb_document(doc_id)
);

CREATE TABLE dbo.kb_chunk (
    chunk_id BIGINT IDENTITY(1,1) PRIMARY KEY,
    doc_id BIGINT NOT NULL,
    version_id BIGINT NOT NULL,
    section_no NVARCHAR(50) NULL,
    section_title NVARCHAR(300) NULL,
    chunk_text NVARCHAR(MAX) NOT NULL,
    step_order INT NULL,
    keywords NVARCHAR(1000) NULL,
    token_count INT NULL,
    is_key_step BIT NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL DEFAULT GETDATE(),
    CONSTRAINT FK_kb_chunk_doc FOREIGN KEY(doc_id) REFERENCES dbo.kb_document(doc_id),
    CONSTRAINT FK_kb_chunk_ver FOREIGN KEY(version_id) REFERENCES dbo.kb_document_version(version_id)
);
```

## 4.3 标签、同义词、权限

```sql
CREATE TABLE dbo.kb_tag (
    tag_id BIGINT IDENTITY(1,1) PRIMARY KEY,
    tag_name NVARCHAR(100) NOT NULL UNIQUE
);

CREATE TABLE dbo.kb_chunk_tag (
    chunk_id BIGINT NOT NULL,
    tag_id BIGINT NOT NULL,
    PRIMARY KEY(chunk_id, tag_id),
    CONSTRAINT FK_chunk_tag_chunk FOREIGN KEY(chunk_id) REFERENCES dbo.kb_chunk(chunk_id),
    CONSTRAINT FK_chunk_tag_tag FOREIGN KEY(tag_id) REFERENCES dbo.kb_tag(tag_id)
);

CREATE TABLE dbo.kb_synonym (
    syn_id BIGINT IDENTITY(1,1) PRIMARY KEY,
    domain_id BIGINT NULL,
    canonical_term NVARCHAR(100) NOT NULL,
    synonym_term NVARCHAR(100) NOT NULL,
    CONSTRAINT FK_syn_domain FOREIGN KEY(domain_id) REFERENCES dbo.kb_domain(domain_id)
);

CREATE TABLE dbo.kb_acl (
    acl_id BIGINT IDENTITY(1,1) PRIMARY KEY,
    doc_id BIGINT NOT NULL,
    role_code NVARCHAR(100) NOT NULL,
    can_read BIT NOT NULL DEFAULT 1,
    CONSTRAINT FK_acl_doc FOREIGN KEY(doc_id) REFERENCES dbo.kb_document(doc_id)
);
```

## 4.4 调用审计（知识库 + ERP + 文件检索）

```sql
CREATE TABLE dbo.ai_task_log (
    task_id BIGINT IDENTITY(1,1) PRIMARY KEY,
    session_id NVARCHAR(100) NULL,
    user_id NVARCHAR(100) NULL,
    user_query NVARCHAR(MAX) NOT NULL,
    intent NVARCHAR(50) NULL,
    route NVARCHAR(100) NULL,                    -- kb/erp/file/cad/chat
    status NVARCHAR(20) NOT NULL,                -- success/failed/partial
    error_message NVARCHAR(MAX) NULL,
    created_at DATETIME NOT NULL DEFAULT GETDATE()
);

CREATE TABLE dbo.ai_tool_call_log (
    log_id BIGINT IDENTITY(1,1) PRIMARY KEY,
    task_id BIGINT NOT NULL,
    tool_name NVARCHAR(50) NOT NULL,             -- kb_retriever/kingdee_api/file_finder
    request_payload NVARCHAR(MAX) NULL,
    response_summary NVARCHAR(MAX) NULL,
    latency_ms INT NULL,
    success BIT NOT NULL,
    created_at DATETIME NOT NULL DEFAULT GETDATE(),
    CONSTRAINT FK_tool_task FOREIGN KEY(task_id) REFERENCES dbo.ai_task_log(task_id)
);
```

## 4.5 全局配置中心（配置也入库，防配置文件丢失）

> 目标：即使本地 `json/ini` 丢失，只要数据库可用，系统可恢复全部默认配置。

```sql
CREATE TABLE dbo.sys_config_group (
    group_id BIGINT IDENTITY(1,1) PRIMARY KEY,
    group_code NVARCHAR(50) NOT NULL UNIQUE,      -- MODEL/KB/ERP/FILE_SHARE/SECURITY
    group_name NVARCHAR(100) NOT NULL,
    is_active BIT NOT NULL DEFAULT 1,
    created_at DATETIME NOT NULL DEFAULT GETDATE()
);

CREATE TABLE dbo.sys_config_version (
    config_id BIGINT IDENTITY(1,1) PRIMARY KEY,
    group_id BIGINT NOT NULL,
    config_key NVARCHAR(100) NOT NULL,            -- 如 kb.connection.default
    config_json NVARCHAR(MAX) NOT NULL,           -- 一条配置完整快照（JSON）
    status TINYINT NOT NULL DEFAULT 1,            -- 0禁用 1启用
    version_no INT NOT NULL,
    change_reason NVARCHAR(500) NULL,
    created_by NVARCHAR(100) NULL,
    created_at DATETIME NOT NULL DEFAULT GETDATE(),
    CONSTRAINT FK_cfg_group FOREIGN KEY(group_id) REFERENCES dbo.sys_config_group(group_id)
);

CREATE TABLE dbo.sys_config_change_log (
    log_id BIGINT IDENTITY(1,1) PRIMARY KEY,
    config_key NVARCHAR(100) NOT NULL,
    old_config_id BIGINT NULL,
    new_config_id BIGINT NOT NULL,
    action NVARCHAR(20) NOT NULL,                 -- insert/disable/rollback
    changed_by NVARCHAR(100) NULL,
    changed_at DATETIME NOT NULL DEFAULT GETDATE(),
    remark NVARCHAR(500) NULL
);

-- 约束规则（通过事务+唯一过滤索引保证“同一配置仅一个启用”）
CREATE UNIQUE INDEX UX_sys_config_key_active
ON dbo.sys_config_version(config_key)
WHERE status = 1;
```

---

## 5. 配置中心设计（你特别要求）

你提到必须在 Python 端配置数据库连接，这里建议在 `ui/settings_window.py` 扩展为多页签：

1. **模型配置**（已有）
2. **知识库配置（新增）**
3. **金蝶 ERP 配置（新增）**
4. **共享文件配置（新增）**
5. **安全配置（新增：配置管理密码）**

并增加一层“全局配置守卫”：

- 点击“配置/保存”前必须先通过密码验证
- 验证通过后才允许进入配置编辑态
- 密码验证与配置变更均写审计日志

### 5.0 配置写入策略（你提出的版本化要求，强制执行）

配置变更必须遵循：**Insert New + Disable Old**，禁止直接 `UPDATE` 覆盖。

### 5.0.1 事务流程

1. 查询当前启用配置（`status=1`）
2. 插入新配置版本（`status=1`, `version_no=old+1`）
3. 将旧版本置为禁用（`status=0`）
4. 写 `sys_config_change_log`
5. 提交事务

### 5.0.2 一致性规则

- 同一 `config_key` 在任意时刻只能有一个 `status=1`
- 任意配置可回滚：插入一条历史版本的拷贝为新启用版本
- 启用失败自动回滚，确保系统始终有可用配置

### 5.0.3 启动加载策略

应用启动时优先读取数据库启用配置；若数据库不可用才降级读取本地缓存配置。

---

## 5.1 知识库配置项（SQL Server 2014）

- `enabled`
- `driver`（如 ODBC Driver 17/SQL Server Native Client）
- `server`
- `port`
- `database`
- `username`
- `password`
- `encrypt`（内网可选）
- `trust_server_certificate`
- `connect_timeout`
- `query_timeout`

并提供：
- “测试连接”按钮
- “初始化表结构”按钮（执行 `schema.sql`）

### 5.1.1 配置权限控制（单独密码）

为避免全局配置被误改，建议增加“配置管理口令（管理员密码）”：

- 密码不明文存储，数据库仅存哈希（如 PBKDF2/bcrypt）
- 连续输错锁定（如 5 次锁 15 分钟）
- 支持密码轮换（保留最近 N 次历史，防止复用）

建议新增表：

```sql
CREATE TABLE dbo.sys_admin_secret (
    secret_id BIGINT IDENTITY(1,1) PRIMARY KEY,
    secret_name NVARCHAR(50) NOT NULL UNIQUE,      -- CONFIG_ADMIN
    secret_hash NVARCHAR(500) NOT NULL,
    salt NVARCHAR(200) NULL,
    status TINYINT NOT NULL DEFAULT 1,             -- 1有效
    rotated_at DATETIME NOT NULL DEFAULT GETDATE(),
    rotated_by NVARCHAR(100) NULL
);

CREATE TABLE dbo.sys_admin_auth_log (
    auth_id BIGINT IDENTITY(1,1) PRIMARY KEY,
    user_id NVARCHAR(100) NULL,
    action NVARCHAR(50) NOT NULL,                  -- config_unlock/config_save
    success BIT NOT NULL,
    client_ip NVARCHAR(50) NULL,
    created_at DATETIME NOT NULL DEFAULT GETDATE(),
    remark NVARCHAR(500) NULL
);
```

---

### 5.2 金蝶 ERP 配置项

- `enabled`
- `base_url`
- `auth_path`（获取 token 的地址）
- `client_id`
- `client_secret`
- `username`（可选）
- `password`（可选）
- `scope`（可选）
- `token_cache_seconds`
- `material_query_api_path`
- “测试认证”按钮
- “测试物料查询”按钮

### 5.3 共享文件配置项

- `enabled`
- `roots`（多个 UNC 根路径）
  - 例：`\\192.168.10.7\资料室`
- `include_patterns`（`*.pdf;*.docx;*.dwg;*.test`）
- `exclude_dirs`
- `max_depth`
- `scan_timeout_sec`
- `use_index_mode`（实时扫描 or 索引模式）
- “测试检索”按钮

---

## 6. AI 编排逻辑（最关键：怎么知道该操作什么）

核心放在 `core/orchestrator.py`：

## 6.1 意图分类（多域）

- `KB_QA`：知识问答（制度、规范、SOP、CAD步骤）
- `ERP_QUERY`：业务数据查询（物料、库存、订单等）
- `FILE_SEARCH`：共享文件查找
- `CAD_COMMAND`：执行CAD命令
- `CHAT`：一般对话

## 6.2 路由规则（建议）

1. 若句子含“查料号/物料规格/库存/ERP/金蝶”等 -> `ERP_QUERY`
2. 若句子含“帮我找文件/资料室/共享盘/路径” -> `FILE_SEARCH`
3. 若句子是“画/绘制/执行命令/插入块”等明确动作 -> `CAD_COMMAND`
4. 其他偏“流程/规范/如何做/标准” -> `KB_QA`
5. 不确定 -> `CHAT` 并追问

> 保持你现有安全机制：**只有 `CAD_COMMAND` 才允许下发 CAD 命令**。

---

## 7. 金蝶 ERP 对接方案（后续扩展主线）

## 7.1 标准调用链

1. `ERP_QUERY` 意图命中
2. 解析槽位（如料号、工厂、组织）
3. 若缺料号 -> AI 追问“请告诉我要查询的料号”
4. 调 `auth_path` 获取 Token（缓存）
5. 带 Token 调物料 API
6. 结构化回传并自然语言总结

## 7.2 Token 管理策略

- 内存缓存：`access_token + expires_at`
- 过期前 2~5 分钟自动刷新
- API 401 自动触发一次重取再重试
- 失败记录 `ai_tool_call_log`

## 7.3 ERP Connector 统一接口

```python
class KingdeeClient:
    def get_token(self) -> str: ...
    def query_material(self, material_no: str) -> dict: ...
```

后续如果要接其他系统（SAP/OA），只需新增 Connector 并在 Orchestrator 注册。

---

## 8. 局域网共享文件检索方案

## 8.1 场景

用户：“请帮我在资料室查找文件：测试.test”

系统流程：
1. 命中 `FILE_SEARCH`
2. 在配置的 `roots` 下检索
3. 返回命中路径列表，如：`//192.168.10.7/资料室/测试.test`

## 8.2 两种检索模式

1. **实时扫描模式**（实现快）
   - `os.walk` + 超时控制 + 深度限制
2. **索引模式**（性能高）
   - 定时扫描生成索引表 `file_index`
   - 查询时走数据库，速度更快

建议：先上实时扫描，再演进索引模式。

---

## 8.3 自动入库（你提出的“扔文档就永久记忆”）

这个需求**可以实现**，而且建议做成标准能力：`KB_INGEST`。

### 8.3.1 目标行为

用户把文档（PDF/Word/MD/TXT）交给 AI 后：

1. 自动识别文档类型与编码
2. 自动抽取文本与结构（标题/章节/步骤）
3. 自动切块并生成关键词/标签
4. 自动写入 SQL Server（`INSERT` 到 `kb_document/kb_document_version/kb_chunk/...`）
5. 入库成功后立即可被全员检索（受权限控制）

> 这就是“持久化记忆”：知识进入数据库后，不依赖原始文件是否还在。

### 8.3.2 关键原则（避免误入库）

1. **两阶段入库**：`staging -> publish`
   - 先入临时表，质检通过后发布为正式版本
2. **去重与版本化**：
   - 文档哈希（MD5/SHA）避免重复入库
   - 相同 `doc_code` 生成新 `version_no`
3. **可回滚**：
   - 发布失败可回退，不污染正式知识库
4. **权限与审批**（可选）：
   - 关键制度文档可走“审核后生效”

### 8.3.3 建议新增表

```sql
CREATE TABLE dbo.kb_ingest_job (
    job_id BIGINT IDENTITY(1,1) PRIMARY KEY,
    source_name NVARCHAR(300) NOT NULL,
    source_path NVARCHAR(500) NULL,
    source_hash NVARCHAR(128) NULL,
    domain_id BIGINT NULL,
    status NVARCHAR(20) NOT NULL,             -- pending/processing/failed/published
    error_message NVARCHAR(MAX) NULL,
    created_by NVARCHAR(100) NULL,
    created_at DATETIME NOT NULL DEFAULT GETDATE(),
    finished_at DATETIME NULL
);

CREATE TABLE dbo.kb_ingest_staging_chunk (
    staging_id BIGINT IDENTITY(1,1) PRIMARY KEY,
    job_id BIGINT NOT NULL,
    section_no NVARCHAR(50) NULL,
    section_title NVARCHAR(300) NULL,
    chunk_text NVARCHAR(MAX) NOT NULL,
    step_order INT NULL,
    keywords NVARCHAR(1000) NULL,
    quality_score FLOAT NULL,
    CONSTRAINT FK_staging_job FOREIGN KEY(job_id) REFERENCES dbo.kb_ingest_job(job_id)
);
```

### 8.3.4 流程（可直接落地）

1. 用户上传或指定文档路径
2. 创建 `kb_ingest_job`
3. 解析文档并写 `kb_ingest_staging_chunk`
4. 自动质检（空块、乱码、超短块、重复块）
5. 通过后事务发布到正式表：
   - `kb_document`
   - `kb_document_version`
   - `kb_chunk`
   - `kb_chunk_tag`
6. 更新 `kb_document.current_version_id`
7. `job.status = published`

### 8.3.5 与当前项目的集成点

- 在 `core/orchestrator.py` 增加 `KB_INGEST` 路由
- 在 UI 增加“知识入库”入口（选择文件/目录、域、分类、是否直接发布）
- 复用现有聊天：支持命令式触发，如“把这份《XX制度》入库到行政域”

### 8.3.6 示例对话（你描述的场景）

- 用户：`请把这份《中线CAD工艺标准V2》加入知识库`
- AI：`已识别文档，准备入库到“CAD域/工艺标准”，是否立即发布为正式版本？`
- 用户：`是`
- AI：`已完成入库：文档编码 SOP-CAD-023，版本 v2.0，共 86 个知识分块。`

此后其他人提问时，检索直接来自 SQL Server，即使原文件丢失，知识仍可用。

---

## 9. 与当前代码的最小侵入改造点

## 9.1 `main_ai_cad.py`

在 `send_command/process_with_ai` 前加入：

1. `orchestrator.route(user_text)`
2. 根据 route 调 connector：
   - kb -> retrieve + answer
   - erp -> token + api
   - file -> search share
   - cad -> 交回原有 `ai_model` 命令路径
3. 统一结果写回 `add_chat_message`

## 9.2 `ai_model.py`

保留当前模型调用，但将其定位为：

- 对检索结果做“答案组织器”
- 对 CAD 场景做“命令生成器”

并将 system prompt 改成“可工具协同”的格式，禁止无依据编造。

## 9.3 `ui/settings_window.py`

扩展 UI 页签（模型/KB/ERP/共享目录/安全）并改造保存逻辑：

1. 点“保存配置”先弹“管理员密码验证”
2. 验证通过后执行“insert新版本 + 旧版本禁用”事务
3. 写入 `sys_config_change_log` 与 `sys_admin_auth_log`
4. 本地仅缓存最后一次生效快照（用于数据库不可用时兜底）

---

## 10. 可扩展性设计要点（你最关注）

1. **统一 Tool 协议**
   - 每个能力都实现：`can_handle(query)`, `execute(context)`
2. **配置热更新**
   - 配置改动后无需重启（可选）
3. **多租户/多部门扩展**
   - `kb_acl` + 组织字段
4. **可观测性**
   - 调用耗时、失败率、召回率
5. **降级策略**
   - ERP 不可用时回退“告知稍后重试”
   - 文件服务器不可达时返回明确错误
6. **能力注册表**
   - 新增业务能力只需注册 Connector，不改主流程

---

## 11. 分阶段实施路线（建议）

### Phase 1：底座（2~3周）

- 知识库表结构与导入
- 设置窗口增加 KB 配置
- `orchestrator + kb retriever` 上线
- 支持“全公司文档问答 + 引用”

### Phase 2：业务扩展（2周）

- ERP 配置页 + Kingdee Token/API 调用
- 物料查询闭环（缺参数追问）
- 工具调用日志落库

### Phase 3：文件检索（1~2周）

- 共享目录配置页
- 实时检索上线
- 常用文件类型优化

### Phase 4：增强（持续）

- 向量混合检索
- 文件索引模式
- 权限精细化与审批流

---

## 12. 验收标准（企业级）

1. 非 CAD 场景可回答全公司 SOP/制度问题，并附出处
2. ERP 询问物料规格可完成“追问料号 -> 调API -> 返回结果”
3. 文件检索可返回真实 UNC 路径
4. CAD 执行安全门不被破坏（仅 `intent=command` 执行）
5. 所有工具调用可审计（谁、何时、调了什么、是否成功）

---

## 12.1 结合当前项目的深层优化建议（参考企业主流实践）

下面这些建议是在你当前代码基础上“可逐步实施”的，不是推倒重来。

### A. 从“检索增强”升级为“任务编排 + 工具协同”

你当前已经具备 `intent=chat/command` 的执行闸门，建议升级为三层：

1. `Intent Router`：判定 KB/ERP/File/CAD
2. `Planner`：拆分多步骤任务（如“查规范 + 查ERP料号 + 给出操作建议”）
3. `Tool Executor`：顺序调用工具并回填证据

收益：能处理复合问题，不再是单轮单工具。

### B. 知识库检索从“能查到”升级为“可评估可优化”

新增离线评测集（至少 200 条真实问句），每条含“标准答案片段ID”。

核心指标：
- Recall@5 / Recall@10（有没有召回正确片段）
- MRR（正确答案排序是否靠前）
- 引用覆盖率（回答是否附来源）
- 幻觉率（回答中无依据陈述比例）

收益：每次改检索/提示词都有量化结果，不靠体感。

### C. SQL2014 下做“混合检索网关”

短期：`Full-Text + 关键词同义词扩展`。
中期：外挂向量服务（可先本地 FAISS），由 Python 网关做融合重排。

- 关键词召回 TopK
- 语义召回 TopK
- 统一重排（规则/小模型）

收益：兼容现有 SQL2014，同时为未来升级留接口。

### D. 文档入库加“质量闸门”

你已规划自动入库，建议再加四道闸：

1. 结构完整性检查（标题/步骤/表格）
2. 重复率检查（防重复文档污染）
3. 风险词检查（涉密/禁用词）
4. 抽样人工确认（关键制度文档）

只有通过质量闸门的版本才允许 `published`。

### E. 配置中心做“双层容灾”

你已定义配置入库，建议补：

1. 数据库主配置（唯一可信源）
2. 本地只读缓存快照（紧急降级）

启动策略：
- 先读 DB 当前启用配置
- DB 不可达时读本地快照并告警
- DB 恢复后自动回切

收益：既防配置文件丢失，也防数据库短时故障。

### F. 安全增强（尤其 ERP 与共享文件）

1. 凭据统一加密存储（Windows DPAPI 或企业密钥服务）
2. ERP API 白名单域名 + 超时 + 重试上限
3. 共享目录访问最小权限账号
4. 输出脱敏（手机号、身份证、价格权限字段）

### G. 从“日志”升级到“可观测性”

建议建立统一 Trace ID（每次会话/请求贯穿）：

- UI 请求
- Orchestrator 路由
- Tool 调用（KB/ERP/File）
- 模型生成
- 最终回答

并看板化关键指标：
- 平均响应时间 P50/P95
- 工具调用成功率
- ERP token 刷新失败率
- 文件检索超时率
- KB 无结果率

### H. 人机协同机制（企业落地成功关键）

在 UI 增加“答案反馈”：
- 正确 / 不准确 / 过期
- 一键提交“纠正建议 + 文档链接”

把反馈回流到：
- 检索评测集
- 同义词表
- 文档更新任务

收益：系统会随企业知识演进不断变准。

### I. 渐进式发布策略

避免一次性全量替换，建议：

1. 先灰度 10% 用户/部门
2. 对比旧流程：响应时间、满意度、误答率
3. 达标后逐步扩容到全员

---

## 13. 结论

你的方向完全正确：这个系统应当是“**企业智能中枢**”，不是单一中线CAD助手。

在当前项目上，最佳做法是：

- 保留现有稳定的 CAD 控制链路
- 新增 Orchestrator 做多能力路由
- 把 SQL Server 2014 知识库、金蝶 ERP API、共享文件检索都插件化
- 所有连接均由 Python 设置窗口配置并可测试

这样既能快速上线当前需求，也为后续持续扩展（ERP/OA/MES/更多知识域）留出标准接口。