#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SQL Server 连接封装（知识库）"""

from __future__ import annotations

from typing import Optional

try:
    import pyodbc
except Exception:  # pragma: no cover
    pyodbc = None


class KBSQLServerDB:
    def __init__(self, connection_string: str):
        if not connection_string:
            raise ValueError("connection_string 不能为空")
        self.connection_string = connection_string

    def connect(self):
        if pyodbc is None:
            raise RuntimeError("未安装 pyodbc，请先安装依赖")
        return pyodbc.connect(self.connection_string, autocommit=False)

    def ping(self) -> bool:
        try:
            with self.connect() as conn:
                cur = conn.cursor()
                cur.execute("SELECT 1")
                row: Optional[tuple] = cur.fetchone()
                return bool(row and row[0] == 1)
        except Exception:
            return False
