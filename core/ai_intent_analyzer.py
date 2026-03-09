#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI 驱动的用户需求分析器（输出结构化意图）。"""

from __future__ import annotations

import json
import re
from typing import Dict, Any, Optional


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    text = text.strip()
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass

    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
        if isinstance(obj, dict):
            return obj
    except Exception:
        return None
    return None


class AIIntentAnalyzer:
    def __init__(self, ai_model):
        self.ai_model = ai_model

    def analyze(self, user_text: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        t = (user_text or "").lower()
        kb_markers = ["公司", "知识库", "文档", "流程", "规范", "cad", "中线", "手册", "标准"]

        # 性能优化：明显与知识库无关的普通对话，直接走 chat，避免每次都额外请求模型导致UI卡顿
        if not any(k in t for k in kb_markers):
            return {
                "intent": "chat",
                "source": "unknown",
                "domain_hint": "",
                "doc_hint": "",
                "section_hint": "",
                "wants_full": False,
                "need_clarify": False,
                "clarify_question": "",
            }

        prompt = (
            "你是企业知识问答的意图分析器。只输出JSON。"
            "JSON字段: {\"intent\":\"kb_qa|chat|command\",\"source\":\"kb|web|both|unknown\","
            "\"domain_hint\":\"\",\"doc_hint\":\"\",\"section_hint\":\"\","
            "\"wants_full\":true|false,\"need_clarify\":true|false,\"clarify_question\":\"\"}。"
            "不要输出解释文本。"
        )
        merged = {"analysis_prompt": prompt}
        if context:
            merged.update(context)

        try:
            result = self.ai_model.process_command(user_text, merged)
            response_text = ""
            if isinstance(result, dict):
                response_text = str(result.get("response", "") or "")
            else:
                response_text = str(result or "")

            obj = _extract_json(response_text)
            if isinstance(obj, dict):
                return {
                    "intent": obj.get("intent", "chat"),
                    "source": obj.get("source", "unknown"),
                    "domain_hint": obj.get("domain_hint", "") or "",
                    "doc_hint": obj.get("doc_hint", "") or "",
                    "section_hint": obj.get("section_hint", "") or "",
                    "wants_full": bool(obj.get("wants_full", False)),
                    "need_clarify": bool(obj.get("need_clarify", False)),
                    "clarify_question": obj.get("clarify_question", "") or "",
                }
        except Exception:
            pass

        # 回退规则（仅兜底）
        t = (user_text or "").lower()
        kb_markers = ["公司", "知识库", "文档", "流程", "规范", "cad", "中线"]
        if any(k in t for k in kb_markers):
            return {
                "intent": "kb_qa",
                "source": "kb",
                "domain_hint": "",
                "doc_hint": "",
                "section_hint": "",
                "wants_full": any(x in t for x in ["全部", "完整", "所有", "不全面", "有哪些"]),
                "need_clarify": False,
                "clarify_question": "",
            }

        return {
            "intent": "chat",
            "source": "unknown",
            "domain_hint": "",
            "doc_hint": "",
            "section_hint": "",
            "wants_full": False,
            "need_clarify": False,
            "clarify_question": "",
        }
