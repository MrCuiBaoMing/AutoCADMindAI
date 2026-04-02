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

    def _detect_web_need(self, text: str, base_intent: str, context: Optional[Dict[str, Any]] = None) -> bool:
        """
        判断是否需要联网检索

        Args:
            text: 用户输入
            base_intent: 基础意图类型
            context: 上下文信息(可能包含 kb_hit 等标记)

        Returns:
            True 表示需要联网检索
        """
        t = (text or "").lower()

        # 规则 1: 用户明确要求联网
        if any(w in t for w in ["联网", "网络", "网上", "互联网", "百度", "搜索"]):
            return True

        # 规则 2: 时间/天气/新闻类关键词(需要实时信息)
        time_weather_news = ["今天", "明天", "昨天", "天气", "气温", "温度", "新闻", "最新", "实时", "当前", "现在"]
        if any(kw in t for kw in time_weather_news):
            return True

        # 规则 2.5: 建筑/工程规范类图纸绘制，建议参考外部资料（提高尺寸/规范精度）
        architecture_keywords = ["楼房", "建筑", "立面", "平面图", "建筑规范", "层高", "结构", "建筑设计"]
        if any(kw in t for kw in architecture_keywords):
            return True

        # 规则 3: chat 意图且知识库未命中(由 Orchestrator 传入 context)
        if base_intent == "chat":
            kb_hit = context.get("kb_hit", False) if context else False
            if not kb_hit:
                # 可能需要联网获取外部信息
                # 这里先保守处理: 只有包含特定关键词才触发
                external_info_keywords = ["价格", "汇率", "股市", "股票", "汇率", "行情", "报价"]
                if any(kw in t for kw in external_info_keywords):
                    return True

        # 其他情况不触发联网
        return False

    def _extract_keywords(self, text: str, for_web: bool = False) -> str:
        """
        提取关键词用于检索

        Args:
            text: 用户输入
            for_web: 是否为网络检索(简化关键词)

        Returns:
            关键词字符串
        """
        if for_web:
            # 网络检索: 去除无意义词
            t = text.strip()
            # 移除常见的对话式前缀/后缀
            prefixes = ["请问", "帮我", "帮我查一下", "告诉我", "我想知道"]
            for p in prefixes:
                if t.startswith(p):
                    t = t[len(p):].strip()
            # 移除标点符号
            import re
            t = re.sub(r'[?？!！,，。]', '', t)
            return t
        else:
            # 知识库检索: 原始文本
            return text

    def analyze(self, user_text: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        t = (user_text or "").lower()
        kb_markers = ["公司", "知识库", "文档", "流程", "规范", "cad", "中线", "手册", "标准"]
        
        # 绘图关键词检测
        drawing_markers = ["画", "绘制", "创建", "生成", "画一个", "画一个圆", "画一个矩形", "画一个五角星", 
                          "画一条线", "画一个三角形", "画一个正方形", "画一个多边形", "画一个椭圆",
                          "绘图", "作图", "制图", "画图", "绘制图形", "创建图形", "生成图形",
                          "circle", "rectangle", "line", "polygon", "star", "triangle", "square",
                          "圆", "矩形", "线", "多边形", "五角星", "三角形", "正方形", "椭圆", "图形"]
        
        # 优先检测绘图意图
        if any(k in t for k in drawing_markers):
            base_intent = "command"
            needs_web = self._detect_web_need(user_text, base_intent, context)
            print(f"[IntentAnalyzer Debug] text='{user_text}', base_intent={base_intent} (drawing detected), needs_web={needs_web}")
            return {
                "intent": base_intent,
                "needs_web": needs_web,
                "web_keywords": self._extract_keywords(user_text, for_web=needs_web),
                "kb_keywords": [],
                "source": "unknown",
                "domain_hint": "",
                "doc_hint": "",
                "section_hint": "",
                "wants_full": False,
                "need_clarify": False,
                "clarify_question": "",
            }

        # 性能优化：明显与知识库无关的普通对话，直接走 chat，避免每次都额外请求模型导致UI卡顿
        if not any(k in t for k in kb_markers):
            base_intent = "chat"
            needs_web = self._detect_web_need(user_text, base_intent, context)
            print(f"[IntentAnalyzer Debug] text='{user_text}', base_intent={base_intent}, needs_web={needs_web}")
            return {
                "intent": base_intent,
                "needs_web": needs_web,
                "web_keywords": self._extract_keywords(user_text, for_web=needs_web),
                "kb_keywords": [],
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
                base_intent = obj.get("intent", "chat")
                needs_web = self._detect_web_need(user_text, base_intent, context)
                return {
                    "intent": base_intent,
                    "needs_web": needs_web,
                    "web_keywords": self._extract_keywords(user_text, for_web=needs_web),
                    "kb_keywords": self._extract_keywords(user_text, for_web=False) if base_intent == "kb_qa" else [],
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
            base_intent = "kb_qa"
            needs_web = self._detect_web_need(user_text, base_intent, context)
            return {
                "intent": base_intent,
                "needs_web": needs_web,
                "web_keywords": self._extract_keywords(user_text, for_web=needs_web),
                "kb_keywords": self._extract_keywords(user_text, for_web=False),
                "source": "kb",
                "domain_hint": "",
                "doc_hint": "",
                "section_hint": "",
                "wants_full": any(x in t for x in ["全部", "完整", "所有", "不全面", "有哪些"]),
                "need_clarify": False,
                "clarify_question": "",
            }

        base_intent = "chat"
        needs_web = self._detect_web_need(user_text, base_intent, context)
        return {
            "intent": base_intent,
            "needs_web": needs_web,
            "web_keywords": self._extract_keywords(user_text, for_web=needs_web),
            "kb_keywords": [],
            "source": "unknown",
            "domain_hint": "",
            "doc_hint": "",
            "section_hint": "",
            "wants_full": False,
            "need_clarify": False,
            "clarify_question": "",
        }
