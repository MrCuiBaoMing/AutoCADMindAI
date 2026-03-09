#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""知识库数据访问层"""

from __future__ import annotations

from typing import Dict, List
import re

from .db import KBSQLServerDB


class KBRepository:
    def __init__(self, db: KBSQLServerDB):
        self.db = db

    def list_domains(self) -> List[Dict]:
        sql = """
        SELECT dm.domain_code, dm.domain_name, COUNT(DISTINCT d.doc_id) AS doc_count
        FROM dbo.kb_domain dm
        LEFT JOIN dbo.kb_document d ON d.domain_id = dm.domain_id AND d.status = 1
        WHERE dm.is_active = 1
        GROUP BY dm.domain_code, dm.domain_name
        ORDER BY dm.domain_name ASC
        """
        rows: List[Dict] = []
        with self.db.connect() as conn:
            cur = conn.cursor()
            cur.execute(sql)
            for r in cur.fetchall():
                rows.append({"domain_code": r[0], "domain_name": r[1], "doc_count": int(r[2] or 0)})
        return rows

    def list_docs(self, domain_code: str = "") -> List[Dict]:
        sql = """
        SELECT d.doc_code, d.title, d.category, dm.domain_code, dm.domain_name
        FROM dbo.kb_document d
        INNER JOIN dbo.kb_domain dm ON d.domain_id = dm.domain_id
        WHERE d.status = 1
          AND (? = '' OR dm.domain_code = ?)
        ORDER BY d.updated_at DESC, d.doc_id DESC
        """
        rows: List[Dict] = []
        with self.db.connect() as conn:
            cur = conn.cursor()
            cur.execute(sql, (domain_code, domain_code))
            for r in cur.fetchall():
                rows.append({
                    "doc_code": r[0],
                    "doc_title": r[1],
                    "category": r[2],
                    "domain_code": r[3],
                    "domain_name": r[4],
                })
        return rows

    def list_sections(self, doc_code: str, version_no: str = "") -> List[Dict]:
        if not doc_code:
            return []

        sql = """
        SELECT
            c.section_title,
            MIN(c.step_order) AS step_order,
            MIN(c.section_no) AS section_no,
            COUNT(*) AS chunk_count
        FROM dbo.kb_chunk c
        INNER JOIN dbo.kb_document d ON c.doc_id = d.doc_id
        INNER JOIN dbo.kb_document_version v ON c.version_id = v.version_id
        WHERE d.doc_code = ?
          AND d.status = 1
          AND v.is_active = 1
          AND (? = '' OR v.version_no = ?)
          AND ISNULL(c.section_title, '') <> ''
        GROUP BY c.section_title
        ORDER BY
            CASE WHEN MIN(c.step_order) IS NULL THEN 999999 ELSE MIN(c.step_order) END,
            c.section_title ASC
        """

        rows: List[Dict] = []
        with self.db.connect() as conn:
            cur = conn.cursor()
            cur.execute(sql, (doc_code, version_no, version_no))
            for r in cur.fetchall():
                rows.append(
                    {
                        "section_title": r[0],
                        "step_order": int(r[1]) if r[1] is not None else None,
                        "section_no": r[2],
                        "chunk_count": int(r[3] or 0),
                    }
                )
        return rows

    def search_domain_candidates(self, query: str, top_n: int = 5) -> List[Dict]:
        tokens = self._extract_tokens(query)
        if not tokens:
            tokens = [query.strip()] if query and query.strip() else []

        token_conditions = []
        params: List = [top_n]
        for tk in tokens:
            like_tk = f"%{tk}%"
            token_conditions.append("(dm.domain_name LIKE ? OR dm.domain_code LIKE ? OR d.category LIKE ? OR d.title LIKE ?)")
            params.extend([like_tk, like_tk, like_tk, like_tk])

        where_tokens = " OR ".join(token_conditions)
        sql = f"""
        SELECT TOP (?)
            dm.domain_code,
            dm.domain_name,
            COUNT(DISTINCT d.doc_id) AS doc_count
        FROM dbo.kb_document d
        INNER JOIN dbo.kb_domain dm ON d.domain_id = dm.domain_id
        WHERE d.status = 1
          AND ({where_tokens})
        GROUP BY dm.domain_code, dm.domain_name
        ORDER BY COUNT(DISTINCT d.doc_id) DESC, dm.domain_name ASC
        """

        rows: List[Dict] = []
        with self.db.connect() as conn:
            cur = conn.cursor()
            cur.execute(sql, tuple(params))
            for r in cur.fetchall():
                rows.append(
                    {
                        "domain_code": r[0],
                        "domain_name": r[1],
                        "doc_count": int(r[2] or 0),
                    }
                )
        return rows

    def search_document_candidates(self, query: str, top_n: int = 5, domain_code: str = "") -> List[Dict]:
        tokens = self._extract_tokens(query)
        if not tokens:
            tokens = [query.strip()] if query and query.strip() else []

        if not tokens:
            return []

        token_conditions = []
        params: List = [top_n]
        for tk in tokens:
            like_tk = f"%{tk}%"
            token_conditions.append("(d.title LIKE ? OR d.category LIKE ? OR dm.domain_name LIKE ?)")
            params.extend([like_tk, like_tk, like_tk])

        where_tokens = " OR ".join(token_conditions)
        sql = f"""
        SELECT TOP (?)
            d.doc_code,
            d.title,
            d.category,
            dm.domain_code,
            dm.domain_name
        FROM dbo.kb_document d
        INNER JOIN dbo.kb_domain dm ON d.domain_id = dm.domain_id
        WHERE d.status = 1
          AND ({where_tokens})
          AND (? = '' OR dm.domain_code = ?)
        ORDER BY d.updated_at DESC, d.doc_id DESC
        """

        params.extend([domain_code, domain_code])

        rows: List[Dict] = []
        with self.db.connect() as conn:
            cur = conn.cursor()
            cur.execute(sql, tuple(params))
            for r in cur.fetchall():
                rows.append(
                    {
                        "doc_code": r[0],
                        "doc_title": r[1],
                        "category": r[2],
                        "domain_code": r[3],
                        "domain_name": r[4],
                    }
                )
        return rows

    def _extract_tokens(self, query: str) -> List[str]:
        text = (query or "").strip()
        if not text:
            return []

        # 1) 基础分段（中文/英文数字连续段）
        raw = re.findall(r"[\u4e00-\u9fffA-Za-z0-9]+", text)

        # 2) 关键词字典（针对企业流程问答场景）
        keyword_dict = [
            "中线", "cad", "autocad", "流程", "规范", "步骤", "标准", "操作", "帮助文档", "手册", "指南", "知识库",
            "bpm", "审批", "电装", "回路", "连接器", "bom", "图层", "标注"
        ]
        derived = []
        lower_text = text.lower()
        for kw in keyword_dict:
            if kw in lower_text:
                derived.append(kw)

        stop_words = {"请", "告诉", "我", "的", "是", "什么", "如何", "怎么", "一下", "一下子", "之类", "有吗", "方面"}
        tokens = []
        for t in raw + derived:
            t = t.strip()
            if not t or t in stop_words:
                continue
            if len(t) >= 2:
                tokens.append(t)

        # 若出现超长中文串，补充 2~4 字滑窗切片提升召回
        for t in list(tokens):
            if re.fullmatch(r"[\u4e00-\u9fff]+", t) and len(t) >= 6:
                for n in (2, 3, 4):
                    for i in range(0, len(t) - n + 1):
                        sub = t[i : i + n]
                        if sub not in stop_words:
                            tokens.append(sub)

        # 去重保序
        uniq = []
        seen = set()
        for t in tokens:
            key = t.lower()
            if key not in seen:
                seen.add(key)
                uniq.append(t)
        return uniq[:20]

    def search_chunks(self, query: str, top_k: int = 8, domain_code: str = "", doc_code: str = "") -> List[Dict]:
        tokens = self._extract_tokens(query)
        if not tokens:
            tokens = [query.strip()] if query and query.strip() else []

        token_conditions = []
        params: List = [top_k]
        for tk in tokens:
            like_tk = f"%{tk}%"
            token_conditions.append("(c.chunk_text LIKE ? OR c.section_title LIKE ? OR c.keywords LIKE ?)")
            params.extend([like_tk, like_tk, like_tk])

        if not token_conditions:
            token_conditions.append("1=0")

        where_tokens = " OR ".join(token_conditions)

        sql = f"""
        SELECT TOP (?)
            c.chunk_id,
            d.doc_code,
            d.title,
            v.version_no,
            c.section_no,
            c.section_title,
            c.step_order,
            c.chunk_text
        FROM dbo.kb_chunk c
        INNER JOIN dbo.kb_document d ON c.doc_id = d.doc_id
        INNER JOIN dbo.kb_document_version v ON c.version_id = v.version_id
        INNER JOIN dbo.kb_domain dm ON d.domain_id = dm.domain_id
        WHERE d.status = 1
          AND v.is_active = 1
          AND ({where_tokens} OR d.title LIKE ?)
          AND (? = '' OR dm.domain_code = ?)
          AND (? = '' OR d.doc_code = ?)
        ORDER BY
            CASE WHEN c.step_order IS NULL THEN 999999 ELSE c.step_order END,
            c.chunk_id DESC
        """

        params.append(f"%{(query or '').strip()}%")
        params.extend([domain_code, domain_code])
        params.extend([doc_code, doc_code])

        rows: List[Dict] = []
        with self.db.connect() as conn:
            cur = conn.cursor()
            cur.execute(sql, tuple(params))
            for r in cur.fetchall():
                rows.append(
                    {
                        "chunk_id": int(r[0]),
                        "doc_code": r[1],
                        "doc_title": r[2],
                        "version_no": r[3],
                        "section_no": r[4],
                        "section_title": r[5],
                        "step_order": r[6],
                        "chunk_text": r[7],
                    }
                )
        return rows
