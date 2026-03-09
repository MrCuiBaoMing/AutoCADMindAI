/* =====================================================
   AutoCADMindAI - Phase 1 Schema (SQL Server 2014)
   包含核心表 + 扩展属性（MS_Description）
   ===================================================== */

SET NOCOUNT ON;

/* ------------------------------
   1) 知识域
------------------------------ */
IF OBJECT_ID('dbo.kb_domain', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.kb_domain (
        domain_id BIGINT IDENTITY(1,1) PRIMARY KEY,
        domain_code NVARCHAR(50) NOT NULL UNIQUE,
        domain_name NVARCHAR(100) NOT NULL,
        is_active BIT NOT NULL DEFAULT 1,
        created_at DATETIME NOT NULL DEFAULT GETDATE()
    );
END;
GO

EXEC sys.sp_addextendedproperty @name=N'MS_Description', @value=N'知识领域主表（CAD/HR/FIN等）',
@level0type=N'SCHEMA',@level0name=N'dbo',@level1type=N'TABLE',@level1name=N'kb_domain';
GO

/* ------------------------------
   2) 文档主表
------------------------------ */
IF OBJECT_ID('dbo.kb_document', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.kb_document (
        doc_id BIGINT IDENTITY(1,1) PRIMARY KEY,
        domain_id BIGINT NOT NULL,
        doc_code NVARCHAR(64) NOT NULL UNIQUE,
        title NVARCHAR(300) NOT NULL,
        category NVARCHAR(100) NOT NULL,
        source_type NVARCHAR(20) NOT NULL,
        source_path NVARCHAR(500) NULL,
        owner_dept NVARCHAR(100) NULL,
        status TINYINT NOT NULL DEFAULT 1,
        current_version_id BIGINT NULL,
        created_at DATETIME NOT NULL DEFAULT GETDATE(),
        updated_at DATETIME NOT NULL DEFAULT GETDATE(),
        CONSTRAINT FK_kb_doc_domain FOREIGN KEY(domain_id) REFERENCES dbo.kb_domain(domain_id)
    );
END;
GO

EXEC sys.sp_addextendedproperty @name=N'MS_Description', @value=N'知识文档主表',
@level0type=N'SCHEMA',@level0name=N'dbo',@level1type=N'TABLE',@level1name=N'kb_document';
GO

/* ------------------------------
   3) 文档版本
------------------------------ */
IF OBJECT_ID('dbo.kb_document_version', 'U') IS NULL
BEGIN
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
END;
GO

EXEC sys.sp_addextendedproperty @name=N'MS_Description', @value=N'文档版本表',
@level0type=N'SCHEMA',@level0name=N'dbo',@level1type=N'TABLE',@level1name=N'kb_document_version';
GO

/* ------------------------------
   4) 文档分块
------------------------------ */
IF OBJECT_ID('dbo.kb_chunk', 'U') IS NULL
BEGIN
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
END;
GO

EXEC sys.sp_addextendedproperty @name=N'MS_Description', @value=N'文档分块表（检索核心）',
@level0type=N'SCHEMA',@level0name=N'dbo',@level1type=N'TABLE',@level1name=N'kb_chunk';
GO

/* ------------------------------
   5) 标签与同义词
------------------------------ */
IF OBJECT_ID('dbo.kb_tag', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.kb_tag (
        tag_id BIGINT IDENTITY(1,1) PRIMARY KEY,
        tag_name NVARCHAR(100) NOT NULL UNIQUE
    );
END;
GO

IF OBJECT_ID('dbo.kb_chunk_tag', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.kb_chunk_tag (
        chunk_id BIGINT NOT NULL,
        tag_id BIGINT NOT NULL,
        PRIMARY KEY(chunk_id, tag_id),
        CONSTRAINT FK_kb_chunk_tag_chunk FOREIGN KEY(chunk_id) REFERENCES dbo.kb_chunk(chunk_id),
        CONSTRAINT FK_kb_chunk_tag_tag FOREIGN KEY(tag_id) REFERENCES dbo.kb_tag(tag_id)
    );
END;
GO

IF OBJECT_ID('dbo.kb_synonym', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.kb_synonym (
        syn_id BIGINT IDENTITY(1,1) PRIMARY KEY,
        domain_id BIGINT NULL,
        canonical_term NVARCHAR(100) NOT NULL,
        synonym_term NVARCHAR(100) NOT NULL,
        CONSTRAINT FK_kb_syn_domain FOREIGN KEY(domain_id) REFERENCES dbo.kb_domain(domain_id)
    );
END;
GO

EXEC sys.sp_addextendedproperty @name=N'MS_Description', @value=N'标签主表',
@level0type=N'SCHEMA',@level0name=N'dbo',@level1type=N'TABLE',@level1name=N'kb_tag';
GO

EXEC sys.sp_addextendedproperty @name=N'MS_Description', @value=N'分块与标签关联表',
@level0type=N'SCHEMA',@level0name=N'dbo',@level1type=N'TABLE',@level1name=N'kb_chunk_tag';
GO

EXEC sys.sp_addextendedproperty @name=N'MS_Description', @value=N'同义词表（用于检索召回扩展）',
@level0type=N'SCHEMA',@level0name=N'dbo',@level1type=N'TABLE',@level1name=N'kb_synonym';
GO

/* ------------------------------
   6) 配置中心（版本化）
------------------------------ */
IF OBJECT_ID('dbo.sys_config_item', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.sys_config_item (
        config_id BIGINT IDENTITY(1,1) PRIMARY KEY,
        config_key NVARCHAR(100) NOT NULL,
        version_no INT NOT NULL,
        config_json NVARCHAR(MAX) NOT NULL,
        status TINYINT NOT NULL DEFAULT 1,  -- 1启用 0禁用
        created_by NVARCHAR(100) NULL,
        created_at DATETIME NOT NULL DEFAULT GETDATE()
    );
END;
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes WHERE name = 'UX_sys_config_item_active' AND object_id = OBJECT_ID('dbo.sys_config_item')
)
BEGIN
    CREATE UNIQUE INDEX UX_sys_config_item_active
    ON dbo.sys_config_item(config_key, status)
    WHERE status = 1;
END;
GO

EXEC sys.sp_addextendedproperty @name=N'MS_Description', @value=N'系统配置版本表（INSERT新版本并禁用旧版本）',
@level0type=N'SCHEMA',@level0name=N'dbo',@level1type=N'TABLE',@level1name=N'sys_config_item';
GO

/* ------------------------------
   6) 管理员密钥与审计
------------------------------ */
IF OBJECT_ID('dbo.sys_admin_secret', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.sys_admin_secret (
        secret_id BIGINT IDENTITY(1,1) PRIMARY KEY,
        secret_name NVARCHAR(50) NOT NULL UNIQUE,
        secret_hash NVARCHAR(500) NOT NULL,
        salt NVARCHAR(200) NULL,
        status TINYINT NOT NULL DEFAULT 1,
        rotated_at DATETIME NOT NULL DEFAULT GETDATE(),
        rotated_by NVARCHAR(100) NULL
    );
END;
GO

IF OBJECT_ID('dbo.sys_admin_auth_log', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.sys_admin_auth_log (
        auth_id BIGINT IDENTITY(1,1) PRIMARY KEY,
        user_id NVARCHAR(100) NULL,
        action NVARCHAR(50) NOT NULL,
        success BIT NOT NULL,
        client_ip NVARCHAR(50) NULL,
        created_at DATETIME NOT NULL DEFAULT GETDATE(),
        remark NVARCHAR(500) NULL
    );
END;
GO

IF OBJECT_ID('dbo.sys_config_change_log', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.sys_config_change_log (
        log_id BIGINT IDENTITY(1,1) PRIMARY KEY,
        config_key NVARCHAR(100) NOT NULL,
        old_config_id BIGINT NULL,
        new_config_id BIGINT NOT NULL,
        changed_by NVARCHAR(100) NULL,
        changed_at DATETIME NOT NULL DEFAULT GETDATE(),
        reason NVARCHAR(500) NULL
    );
END;
GO

/* ------------------------------
   7) 索引建议
------------------------------ */
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_kb_document_domain' AND object_id = OBJECT_ID('dbo.kb_document'))
    CREATE INDEX IX_kb_document_domain ON dbo.kb_document(domain_id);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_kb_chunk_doc_ver' AND object_id = OBJECT_ID('dbo.kb_chunk'))
    CREATE INDEX IX_kb_chunk_doc_ver ON dbo.kb_chunk(doc_id, version_id);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_kb_chunk_step_order' AND object_id = OBJECT_ID('dbo.kb_chunk'))
    CREATE INDEX IX_kb_chunk_step_order ON dbo.kb_chunk(step_order);
GO
