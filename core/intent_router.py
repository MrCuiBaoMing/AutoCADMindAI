#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""多域意图路由（规则优先）"""

from __future__ import annotations

from typing import Literal

Intent = Literal["KB_QA", "ERP_QUERY", "FILE_SEARCH", "CAD_COMMAND", "CHAT"]


def detect_intent(text: str) -> Intent:
    t = (text or "").strip().lower()
    if not t:
        return "CHAT"

    # 单词级简短输入（如“流程”“规范”）默认归为知识问答
    if t in {"流程", "规范", "标准", "步骤", "操作", "操作流程"}:
        return "KB_QA"

    erp_markers = ["料号", "物料", "erp", "金蝶", "库存", "规格"]
    file_markers = ["找文件", "资料室", "共享", "路径", "文件"]
    cad_markers = ["绘制", "画", "命令", "插入", "删除", "移动", "旋转", "修剪"]
    qa_markers = [
        "流程", "规范", "标准", "步骤", "如何", "怎么", "说明", "指引", "中线cad", "cad规范", "操作过程",
        "帮助文档", "文档", "手册", "指南", "知识库", "质量", "回路", "节点", "导入", "建立中线", "校核"
    ]

    if any(k in t for k in erp_markers):
        return "ERP_QUERY"
    if any(k in t for k in file_markers):
        return "FILE_SEARCH"
    if any(k in t for k in cad_markers):
        return "CAD_COMMAND"
    if any(k in t for k in qa_markers):
        return "KB_QA"
    return "CHAT"
