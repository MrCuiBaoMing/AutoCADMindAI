#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配置中心（SQL Server 2014）最小实现
规则：INSERT 新版本 + 禁用旧版本（禁止覆盖式 UPDATE）
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

try:
    import pyodbc
except Exception:  # pragma: no cover
    pyodbc = None


class ConfigDBStore:
    def __init__(self, connection_string: str):
        if not connection_string:
            raise ValueError("connection_string 不能为空")
        self.connection_string = connection_string

    @staticmethod
    def _to_int(value, default=0) -> int:
        try:
            if value is None:
                return int(default)
            return int(value)
        except Exception:
            return int(default)

    def _connect(self):
        if pyodbc is None:
            raise RuntimeError("未安装 pyodbc，请先安装依赖")
        return pyodbc.connect(self.connection_string, autocommit=False)

    def get_active_config(self, config_key: str) -> Optional[Dict[str, Any]]:
        sql = """
        SELECT TOP 1 config_id, config_key, version_no, config_json, status, created_by, created_at
        FROM dbo.sys_config_item
        WHERE config_key = ? AND status = 1
        ORDER BY version_no DESC, config_id DESC
        """
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(sql, (config_key,))
            row = cur.fetchone()
            if not row:
                return None
            return {
                "config_id": self._to_int(row[0], 0),
                "config_key": str(row[1]) if row[1] is not None else "",
                "version_no": self._to_int(row[2], 0),
                "config_json": json.loads(row[3]) if row[3] else {},
                "status": self._to_int(row[4], 0),
                "created_by": row[5],
                "created_at": row[6],
            }

    def save_new_version(self, config_key: str, config_data: Dict[str, Any], changed_by: str = "system", reason: str = "") -> int:
        """保存新版本配置并禁用旧版本，返回新 config_id。"""
        if not config_key:
            raise ValueError("config_key 不能为空")

        payload = json.dumps(config_data, ensure_ascii=False)

        with self._connect() as conn:
            cur = conn.cursor()

            cur.execute(
                """
                SELECT TOP 1 config_id, version_no
                FROM dbo.sys_config_item
                WHERE config_key = ? AND status = 1
                ORDER BY version_no DESC, config_id DESC
                """,
                (config_key,),
            )
            active = cur.fetchone()
            old_id = self._to_int(active[0], 0) if active else None
            current_ver = self._to_int(active[1], 0) if active else 0
            next_ver = current_ver + 1

            # 先禁用旧版本，再插入新版本，避免唯一索引（config_key+status=1）冲突
            if old_id is not None:
                cur.execute(
                    "UPDATE dbo.sys_config_item SET status = 0 WHERE config_id = ?",
                    (old_id,),
                )

            # 使用 OUTPUT INSERTED.config_id 稳定获取新主键（比 SCOPE_IDENTITY 在某些驱动下更稳）
            cur.execute(
                """
                INSERT INTO dbo.sys_config_item(config_key, version_no, config_json, status, created_by)
                OUTPUT INSERTED.config_id
                VALUES (?, ?, ?, 1, ?)
                """,
                (config_key, next_ver, payload, changed_by),
            )

            out_row = cur.fetchone()
            new_id = self._to_int(out_row[0] if out_row else None, 0)

            # 兜底：若 OUTPUT 未返回，按最新记录回查
            if new_id <= 0:
                cur.execute(
                    """
                    SELECT TOP 1 config_id
                    FROM dbo.sys_config_item
                    WHERE config_key = ?
                    ORDER BY config_id DESC
                    """,
                    (config_key,),
                )
                fallback = cur.fetchone()
                new_id = self._to_int(fallback[0] if fallback else None, 0)

            if new_id <= 0:
                raise RuntimeError("新配置版本写入失败：未获取到有效 config_id")

            # 确保只有当前新版本为启用态
            cur.execute(
                """
                UPDATE dbo.sys_config_item
                SET status = CASE WHEN config_id = ? THEN 1 ELSE 0 END
                WHERE config_key = ?
                """,
                (new_id, config_key),
            )

            old_for_log = old_id if old_id and old_id > 0 else None

            cur.execute(
                """
                INSERT INTO dbo.sys_config_change_log(config_key, old_config_id, new_config_id, changed_by, reason)
                VALUES (?, ?, ?, ?, ?)
                """,
                (config_key, old_for_log, new_id, changed_by, reason),
            )

            conn.commit()
            return new_id
