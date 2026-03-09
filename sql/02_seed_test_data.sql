/* =====================================================
   AutoCADMindAI - 测试数据脚本（知识库）
   说明：执行前请先执行 01_schema_with_description.sql
   ===================================================== */

SET NOCOUNT ON;

BEGIN TRY
    BEGIN TRAN;

    /* 1) 领域 */
    IF NOT EXISTS (SELECT 1 FROM dbo.kb_domain WHERE domain_code = N'CAD')
    BEGIN
        INSERT INTO dbo.kb_domain(domain_code, domain_name, is_active)
        VALUES (N'CAD', N'CAD工程设计', 1);
    END

    IF NOT EXISTS (SELECT 1 FROM dbo.kb_domain WHERE domain_code = N'SOP')
    BEGIN
        INSERT INTO dbo.kb_domain(domain_code, domain_name, is_active)
        VALUES (N'SOP', N'企业标准作业', 1);
    END

    DECLARE @domain_cad BIGINT = (SELECT TOP 1 domain_id FROM dbo.kb_domain WHERE domain_code = N'CAD');

    /* 2) 文档主表 */
    IF NOT EXISTS (SELECT 1 FROM dbo.kb_document WHERE doc_code = N'SOP-CAD-001')
    BEGIN
        INSERT INTO dbo.kb_document(
            domain_id, doc_code, title, category, source_type, source_path,
            owner_dept, status
        )
        VALUES (
            @domain_cad, N'SOP-CAD-001', N'中线CAD标准操作流程', N'中线CAD',
            N'md', N'//192.168.10.7/资料室/中线CAD标准操作流程.md',
            N'工程技术部', 1
        );
    END

    DECLARE @doc_id BIGINT = (SELECT TOP 1 doc_id FROM dbo.kb_document WHERE doc_code = N'SOP-CAD-001');

    /* 3) 文档版本 */
    IF NOT EXISTS (
        SELECT 1 FROM dbo.kb_document_version
        WHERE doc_id = @doc_id AND version_no = N'v1.0'
    )
    BEGIN
        INSERT INTO dbo.kb_document_version(
            doc_id, version_no, effective_date, is_active, change_summary
        )
        VALUES (
            @doc_id, N'v1.0', GETDATE(), 1, N'初版测试数据'
        );
    END

    DECLARE @version_id BIGINT = (
        SELECT TOP 1 version_id
        FROM dbo.kb_document_version
        WHERE doc_id = @doc_id AND is_active = 1
        ORDER BY version_id DESC
    );

    /* 4) 分块（流程步骤） */
    IF NOT EXISTS (
        SELECT 1 FROM dbo.kb_chunk
        WHERE doc_id = @doc_id AND version_id = @version_id AND step_order = 1
    )
    BEGIN
        INSERT INTO dbo.kb_chunk(doc_id, version_id, section_no, section_title, chunk_text, step_order, keywords, is_key_step)
        VALUES
        (@doc_id, @version_id, N'1', N'准备环境', N'启动AutoCAD与中线CAD插件，确认项目图纸版本正确，并加载公司标准图层模板。', 1, N'中线CAD,准备,图层模板,项目图纸', 1),
        (@doc_id, @version_id, N'2', N'导入基础数据', N'导入控制点、线路中心桩号及地形参考数据，检查坐标系与单位一致性。', 2, N'导入,控制点,坐标系,桩号', 1),
        (@doc_id, @version_id, N'3', N'建立中线', N'使用中线生成工具创建主中线，按设计速度与曲线半径约束进行校核。', 3, N'中线生成,曲线半径,设计速度', 1),
        (@doc_id, @version_id, N'4', N'节点标注', N'对转角点、交点、里程关键点进行节点标注，标注格式按公司出图标准执行。', 4, N'节点标注,里程,交点,出图标准', 1),
        (@doc_id, @version_id, N'5', N'回路与连接器', N'根据电装规范填写回路号并调取连接器，校核型号一致性及安装方向。', 5, N'回路号,连接器,电装规范', 1),
        (@doc_id, @version_id, N'6', N'质量校核与导出', N'执行自检清单：图层、标注、BOM一致性，确认无误后导出BOM与图纸文件。', 6, N'质量校核,BOM,导出,自检', 1);
    END

    /* 5) 标签 */
    IF NOT EXISTS (SELECT 1 FROM dbo.kb_tag WHERE tag_name = N'中线CAD')
        INSERT INTO dbo.kb_tag(tag_name) VALUES (N'中线CAD');

    IF NOT EXISTS (SELECT 1 FROM dbo.kb_tag WHERE tag_name = N'标准流程')
        INSERT INTO dbo.kb_tag(tag_name) VALUES (N'标准流程');

    DECLARE @tag_cad BIGINT = (SELECT TOP 1 tag_id FROM dbo.kb_tag WHERE tag_name = N'中线CAD');
    DECLARE @tag_sop BIGINT = (SELECT TOP 1 tag_id FROM dbo.kb_tag WHERE tag_name = N'标准流程');

    INSERT INTO dbo.kb_chunk_tag(chunk_id, tag_id)
    SELECT c.chunk_id, @tag_cad
    FROM dbo.kb_chunk c
    WHERE c.doc_id = @doc_id
      AND NOT EXISTS (
          SELECT 1 FROM dbo.kb_chunk_tag ct
          WHERE ct.chunk_id = c.chunk_id AND ct.tag_id = @tag_cad
      );

    INSERT INTO dbo.kb_chunk_tag(chunk_id, tag_id)
    SELECT c.chunk_id, @tag_sop
    FROM dbo.kb_chunk c
    WHERE c.doc_id = @doc_id
      AND NOT EXISTS (
          SELECT 1 FROM dbo.kb_chunk_tag ct
          WHERE ct.chunk_id = c.chunk_id AND ct.tag_id = @tag_sop
      );

    /* 6) 同义词（提升召回） */
    IF NOT EXISTS (SELECT 1 FROM dbo.kb_synonym WHERE canonical_term = N'中线CAD' AND synonym_term = N'中线cad')
        INSERT INTO dbo.kb_synonym(domain_id, canonical_term, synonym_term) VALUES (@domain_cad, N'中线CAD', N'中线cad');

    IF NOT EXISTS (SELECT 1 FROM dbo.kb_synonym WHERE canonical_term = N'中线CAD' AND synonym_term = N'中心线CAD')
        INSERT INTO dbo.kb_synonym(domain_id, canonical_term, synonym_term) VALUES (@domain_cad, N'中线CAD', N'中心线CAD');

    IF NOT EXISTS (SELECT 1 FROM dbo.kb_synonym WHERE canonical_term = N'标准流程' AND synonym_term = N'操作流程')
        INSERT INTO dbo.kb_synonym(domain_id, canonical_term, synonym_term) VALUES (@domain_cad, N'标准流程', N'操作流程');

    /* 7) 更新当前版本指针 */
    UPDATE dbo.kb_document
    SET current_version_id = @version_id,
        updated_at = GETDATE()
    WHERE doc_id = @doc_id;

    COMMIT TRAN;
    PRINT N'[OK] 测试数据写入完成';
END TRY
BEGIN CATCH
    IF @@TRANCOUNT > 0 ROLLBACK TRAN;
    DECLARE @err NVARCHAR(4000) = ERROR_MESSAGE();
    PRINT N'[ERR] 写入失败: ' + @err;
    THROW;
END CATCH;

/* ---------- 验证查询 ---------- */
SELECT TOP 1 d.doc_code, d.title, v.version_no, d.current_version_id
FROM dbo.kb_document d
LEFT JOIN dbo.kb_document_version v ON d.current_version_id = v.version_id
WHERE d.doc_code = N'SOP-CAD-001';

SELECT TOP 20 c.step_order, c.section_title, c.chunk_text
FROM dbo.kb_chunk c
INNER JOIN dbo.kb_document d ON c.doc_id = d.doc_id
WHERE d.doc_code = N'SOP-CAD-001'
ORDER BY c.step_order;
