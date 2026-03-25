#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""主流程编排器：意图识别 -> 工具路由 -> 返回统一结果"""

from __future__ import annotations

from typing import Dict, Any, List, Optional
import json

from core.intent_router import detect_intent
from connectors.kb_sqlserver.retriever import KBRetriever


# Web 搜索 Prompt 模板（优化：更简洁，减少 token 数量）
WEB_SEARCH_PROMPT = """基于以下网络信息回答问题:

{web_content}

问题: {question}

要求:
1. 用1-2句话简洁回答
2. 标注信息来源
3. 信息不足时直接说明

回答:"""


# CAD 绘图分析 Prompt 模板
CAD_ANALYSIS_PROMPT = """你是一个专业的AutoCAD绘图规划师。请分析用户绘图需求，生成详细的绘图计划。

用户需求: {user_input}

请按以下格式返回JSON分析结果：
{{
  "drawing_type": "建筑/机械/电气/其他",
  "complexity": "简单/中等/复杂",
  "components": [
    {{
      "name": "组件名称",
      "description": "组件描述",
      "coordinates": "坐标计算逻辑",
      "dimensions": "尺寸要求",
      "layer": "图层名称"
    }}
  ],
  "layout_strategy": "布局策略描述",
  "dimension_annotations": ["需要标注的尺寸"],
  "execution_order": ["绘制顺序"],
  "estimated_commands": 预计命令数量
}}

分析要点：
1. 识别图形类型和复杂度
2. 确定基准点和坐标系
3. 计算各组件的精确坐标
4. 规划绘制顺序（先大后小，先结构后细节）
5. 确定尺寸标注位置
6. 考虑图层组织

只返回JSON，不要其他文本。"""


class Orchestrator:
    def __init__(self, db_enabled: bool, db_connection_string: str, db_domain_code: str = "",
                 web_retriever=None, web_cfg=None, ai_model=None):
        self.db_enabled = bool(db_enabled)
        self.db_connection_string = db_connection_string or ""
        self.db_domain_code = db_domain_code or ""
        self.kb = KBRetriever(self.db_connection_string) if self.db_enabled and self.db_connection_string else None

        # Web 检索器
        self.web_retriever = web_retriever
        self.web_cfg = web_cfg or {}
        self.ai_model = ai_model

        self.pending_source_choice: bool = False
        self.pending_source_query: str = ""
        self.source_preference: str = ""  # kb/web/both
        self.pending_kb_domains: Optional[List[Dict[str, Any]]] = None
        self.pending_kb_options: Optional[List[Dict[str, Any]]] = None
        self.pending_kb_sections: Optional[List[Dict[str, Any]]] = None

        self.last_kb_query: str = ""
        self.last_kb_domain_code: str = ""
        self.last_kb_doc_title: str = ""
        self.last_kb_sections: List[str] = []
        self.active_doc_code: str = ""

    def _match_user_choice(self, text: str, options: Optional[List[Dict[str, Any]]], name_key: str, code_key: str) -> Optional[Dict[str, Any]]:
        if not options:
            return None
        t = (text or "").strip()
        if not t:
            return None

        if t.isdigit():
            idx = int(t)
            if 1 <= idx <= len(options):
                return options[idx - 1]

        tl = t.lower()
        for d in options:
            name = str(d.get(name_key) or "").lower()
            code = str(d.get(code_key) or "").lower()
            if tl in name or tl == code:
                return d
        return None

    def _is_short_followup(self, text: str) -> bool:
        t = (text or "").strip()
        if not t:
            return False
        return t in {"流程", "规范", "步骤", "这个", "继续", "详细", "展开"} or len(t) <= 3

    def _compose_query_with_context(self, user_text: str) -> str:
        t = (user_text or "").strip()
        if not t:
            return t

        # 显式章节词优先：不再只按上次 query 盲目拼接
        chapter_words = ["准备环境", "导入基础数据", "建立中线", "节点标注", "回路", "连接器", "质量校核", "导出", "质量"]
        if any(w in t for w in chapter_words):
            base = self.last_kb_doc_title or self.last_kb_query or ""
            return f"{base} {t}".strip() if base else t

        if self._is_short_followup(t) and self.last_kb_query:
            return f"{self.last_kb_query} {t}".strip()
        return t

    def _analyze_user_need(self, user_text: str) -> Dict[str, Any]:
        """轻量需求分析：从当前句+会话锚点提取检索策略。"""
        t = (user_text or "").strip().lower()
        analysis = {
            "wants_full_flow": False,
            "section_hint": "",
            "prefer_doc_locked": bool(self.active_doc_code),
        }

        full_flow_markers = ["有哪些", "完整", "不全面", "全部", "全流程", "整体流程"]
        if any(m in t for m in full_flow_markers):
            analysis["wants_full_flow"] = True

        section_keywords = ["准备环境", "导入基础数据", "建立中线", "节点标注", "回路", "连接器", "质量校核", "导出", "质量"]
        for k in section_keywords:
            if k in t:
                analysis["section_hint"] = k
                break

        return analysis

    def _need_source_clarification(self, text: str) -> bool:
        # 仅在会话未确定来源时询问一次，避免反复“1/2/3”打断
        if self.source_preference:
            return False
        t = (text or "").lower()
        kb_words = ["公司", "标准", "规范", "流程", "文档", "手册", "知识库", "中线", "cad"]
        web_words = ["网络", "网上", "互联网", "公开", "官网", "外部"]
        has_kb = any(w in t for w in kb_words)
        has_web = any(w in t for w in web_words)
        # 只有“来源模糊且不是明确内部查询”才触发
        if has_web:
            return False
        return ("文档" in t or "资料" in t or "帮助" in t) and not ("公司" in t or "内部" in t or "知识库" in t)

    def _parse_source_choice(self, text: str) -> str:
        t = (text or "").strip().lower()
        if t in {"1", "公司", "公司知识库", "内部", "内部文档", "标准库"}:
            return "kb"
        if t in {"2", "网络", "外部", "公开资料", "官网"}:
            return "web"
        if t in {"3", "都要", "都查", "都可以", "都看"}:
            return "both"
        return ""

    def _build_section_list_response(self, sections: List[Dict[str, Any]]) -> Dict[str, Any]:
        # 智能体对话模式：保留完整候选池，由用户自然语言继续筛选
        self.pending_kb_sections = sections

        # 展示前若干代表项即可，避免刷屏，但不引导分页命令
        preview_size = 12
        preview = sections[:preview_size]

        lines = ["我已在该文档中定位到以下章节方向（可直接说关键词继续筛选）："]
        for s in preview:
            title = s.get("section_title") or f"步骤{s.get('step_order')}"
            step = s.get("step_order")
            if step is not None:
                lines.append(f"- [{step}] {title}")
            else:
                lines.append(f"- {title}")

        if len(sections) > preview_size:
            lines.append(f"当前还有 {len(sections) - preview_size} 个章节未展示。你可以直接说想看的内容，比如“质量校核”“回路”“标注”。")
        else:
            lines.append("你可以直接说想看的内容，比如“质量校核”“回路”“标注”。")

        return {
            "intent": "chat",
            "route": "kb",
            "response": "\n".join(lines),
            "commands": [],
            "citations": [],
        }

    def _build_web_content(self, results: List[Dict[str, Any]]) -> str:
        """构建网络检索结果文本（优化：减少内容长度以加快大模型处理速度）"""
        lines = []
        # 只取前 2 条结果，减少 prompt 长度
        for r in results[:2]:
            title = r.get("title", "")
            content = r.get("content", "")
            # 截断内容长度(省 token) - 从 500 减少到 300
            if len(content) > 300:
                content = content[:300] + "..."
            lines.append(f"- {title}: {content}")
        return "\n".join(lines)

    def _generate_with_web(self, question: str, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """使用网络检索结果生成回答"""
        if not self.ai_model:
            return {
                "intent": "chat",
                "route": "web",
                "response": "AI 模型未配置,无法融合检索结果。",
                "commands": [],
                "web_sources": []
            }

        try:
            # 构建 web prompt
            web_content = self._build_web_content(results)
            prompt = WEB_SEARCH_PROMPT.format(
                web_content=web_content,
                question=question
            )

            # 调用 AI 生成回答
            response = self.ai_model.generate_with_context(prompt, {"web_search_results": results})

            # 提取来源信息(前 2 个)
            web_sources = [{"title": r.get("title", ""), "url": r.get("url", "")} for r in results[:2]]

            return {
                "intent": "chat",
                "route": "web",
                "response": response,
                "commands": [],
                "web_sources": web_sources
            }

        except Exception as e:
            # 降级: 直接返回检索结果摘要
            print(f"[Orchestrator] Web 生成失败: {e}")
            summary = "\n".join([f"{r.get('title', '')}: {r.get('content', '')[:200]}" for r in results[:2]])
            return {
                "intent": "chat",
                "route": "web",
                "response": f"已联网获取信息:\n{summary}",
                "commands": [],
                "web_sources": [{"title": r.get("title", ""), "url": r.get("url", "")} for r in results[:2]]
            }

    def _build_kb_context_result(self, user_query: str, chunks: List[Dict[str, Any]]) -> Dict[str, Any]:
        dedup = {}
        for c in chunks:
            dedup[c.get("chunk_id")] = c
        ordered = sorted(
            dedup.values(),
            key=lambda x: (999999 if x.get("step_order") is None else int(x.get("step_order")), int(x.get("chunk_id") or 0))
        )

        citations = []
        lines = ["根据公司知识库检索结果，建议如下："]
        for idx, c in enumerate(ordered[:6], start=1):
            section = f"{c.get('section_no') or ''} {c.get('section_title') or ''}".strip()
            lines.append(f"{idx}. {c.get('chunk_text', '')[:180]}")
            citations.append(
                {
                    "doc_code": c.get("doc_code"),
                    "doc_title": c.get("doc_title"),
                    "version_no": c.get("version_no"),
                    "section": section,
                    "chunk_id": c.get("chunk_id"),
                }
            )

        # 记录最近命中的章节，供后续短问承接
        self.last_kb_sections = [str(c.get("section_title") or "") for c in ordered[:6] if c.get("section_title")]
        if citations:
            self.active_doc_code = str(citations[0].get("doc_code") or "")

        return {
            "intent": "command_proxy",
            "route": "kb_context",
            "response": "",
            "commands": [],
            "citations": citations,
            "kb_context": {
                "user_query": user_query,
                "summary": "\n".join(lines),
                "chunks": ordered[:6],
                "citations": citations,
            },
        }

    def _analyze_cad_drawing(self, user_text: str) -> Dict[str, Any]:
        """分析CAD绘图需求，生成结构化绘图计划"""
        if not self.ai_model:
            return {"error": "AI模型未配置"}

        try:
            # 使用分析prompt生成绘图计划
            analysis_prompt = CAD_ANALYSIS_PROMPT.format(user_input=user_text)
            analysis_result = self.ai_model.generate_with_context(analysis_prompt)

            # 解析JSON结果
            analysis_data = json.loads(analysis_result.strip())

            return {
                "success": True,
                "analysis": analysis_data,
                "user_input": user_text
            }

        except Exception as e:
            print(f"[Orchestrator] CAD分析失败: {e}")
            return {
                "success": False,
                "error": str(e),
                "fallback": True
            }

    def _generate_cad_commands_from_analysis(self, analysis: Dict[str, Any]) -> List[str]:
        """基于分析结果生成AutoCAD命令序列"""
        if not analysis.get("success", False):
            return []

        analysis_data = analysis.get("analysis", {})
        user_input = analysis.get("user_input", "")

        # 构建详细的命令生成prompt
        command_prompt = f"""基于以下绘图分析结果，生成具体的AutoCAD命令序列：

分析结果: {json.dumps(analysis_data, ensure_ascii=False, indent=2)}

用户原始需求: {user_input}

请生成可直接执行的AutoCAD命令列表。要求：

1. 按分析中的execution_order顺序生成命令
2. 使用精确坐标，避免重叠
3. 包含必要的图层设置 (LAYER, SET)
4. 添加尺寸标注 (DIMLINEAR, DIMALIGNED等)
5. 对于复杂图形，使用多条简单命令组合
6. 坐标系：X向右为正，Y向上为正，从(0,0)开始

返回格式：JSON {{"commands": ["命令1", "命令2", ...]}}

只返回JSON，不要其他文本。"""

        try:
            command_result = self.ai_model.generate_with_context(command_prompt)
            command_data = json.loads(command_result.strip())

            return command_data.get("commands", [])

        except Exception as e:
            print(f"[Orchestrator] 命令生成失败: {e}")
            return []

    def handle(self, user_text: str, analysis: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        effective_query = self._compose_query_with_context(user_text)
        analysis = analysis or {}

        # 0) 来源澄清
        if self.pending_source_choice:
            choice = self._parse_source_choice(user_text)
            if not choice:
                return {
                    "intent": "chat",
                    "route": "kb",
                    "response": "请回复 1/2/3 选择查询来源：1)公司知识库 2)外部网络 3)两者都要。",
                    "commands": [],
                    "citations": [],
                }
            self.pending_source_choice = False
            self.source_preference = choice
            # 用户刚选完来源，继续用当时触发的原问题执行检索
            if self.pending_source_query:
                effective_query = self.pending_source_query
                self.pending_source_query = ""
            if choice in {"web", "both"}:
                return {
                    "intent": "chat",
                    "route": "chat",
                    "response": "已收到，外部网络检索能力将在下一阶段接入。当前先为您检索公司知识库。",
                    "commands": [],
                    "citations": [],
                }

        # 0.5) 待选章节（支持自然语言筛选，不要求序号）
        if self.pending_kb_sections and self.kb is not None:
            section_choice = self._match_user_choice(user_text, self.pending_kb_sections, "section_title", "section_title")
            if not section_choice:
                t = (user_text or "").strip().lower()
                filtered = [
                    s for s in self.pending_kb_sections
                    if t and t in str(s.get("section_title") or "").lower()
                ]
                if len(filtered) == 1:
                    section_choice = filtered[0]
                elif len(filtered) >= 2:
                    return self._build_section_list_response(filtered)

            if section_choice:
                self.pending_kb_sections = None
                section_query = str(section_choice.get("section_title") or user_text)
                chunks = self.kb.retrieve(
                    query=f"{self.last_kb_doc_title} {section_query}".strip(),
                    top_k=8,
                    domain_code=self.last_kb_domain_code,
                    doc_code=self.active_doc_code,
                )
                if chunks:
                    return self._build_kb_context_result(section_query, chunks)

        # 1) 待选领域
        domain_choice = self._match_user_choice(user_text, self.pending_kb_domains, "domain_name", "domain_code")
        if domain_choice and self.kb is not None:
            chosen_domain_code = str(domain_choice.get("domain_code") or "")
            self.pending_kb_domains = None

            doc_candidates = self.kb.retrieve_candidates(effective_query, top_n=5, domain_code=chosen_domain_code)
            if len(doc_candidates) >= 2:
                self.pending_kb_options = doc_candidates[:4]
                options = [f"{i}) {d.get('doc_title')}（{d.get('domain_name')}/{d.get('category')}）" for i, d in enumerate(self.pending_kb_options, 1)]
                return {
                    "intent": "chat",
                    "route": "kb",
                    "response": "已定位到目标领域，请继续确认具体文档：\n" + "\n".join(options) + "\n请回复序号或文档名称。",
                    "commands": [],
                    "citations": [],
                }

            chunks = self.kb.retrieve(query=effective_query, top_k=8, domain_code=chosen_domain_code, doc_code=self.active_doc_code)
            if chunks:
                self.last_kb_domain_code = chosen_domain_code
                self.last_kb_query = effective_query
                return self._build_kb_context_result(effective_query, chunks)

        # 2) 待选文档
        doc_choice = self._match_user_choice(user_text, self.pending_kb_options, "doc_title", "doc_code")
        if doc_choice and self.kb is not None:
            target_query = str(doc_choice.get("doc_title") or effective_query)
            domain_code = str(doc_choice.get("domain_code") or self.db_domain_code)
            self.pending_kb_options = None
            self.last_kb_doc_title = str(doc_choice.get("doc_title") or "")
            self.last_kb_domain_code = domain_code
            self.last_kb_query = self.last_kb_doc_title or effective_query

            chunks = self.kb.retrieve(query=target_query, top_k=8, domain_code=domain_code, doc_code=self.active_doc_code)
            if not chunks:
                chunks = self.kb.retrieve(query=target_query, top_k=8, domain_code="", doc_code=self.active_doc_code)
            if chunks:
                return self._build_kb_context_result(effective_query, chunks)

        ai_intent = str(analysis.get("intent", "")).lower()
        if ai_intent == "kb_qa":
            intent = "KB_QA"
        elif ai_intent == "command":
            intent = "CAD_COMMAND"
        elif ai_intent == "chat":
            intent = "CHAT"
        else:
            intent = detect_intent(user_text)

        if intent == "KB_QA":
            if self.kb is None:
                return {"intent": "chat", "route": "kb", "response": "知识库未启用或未配置数据库连接。", "commands": [], "citations": []}

            if self._need_source_clarification(user_text):
                self.pending_source_choice = True
                self.pending_source_query = effective_query
                return {
                    "intent": "chat",
                    "route": "kb",
                    "response": "请先确认查询来源：\n1) 公司知识库（内部标准）\n2) 外部网络资料\n3) 两者都要\n请回复序号。",
                    "commands": [],
                    "citations": [],
                }

            ai_source = str(analysis.get("source", "") or "").lower()
            domain_hint = str(analysis.get("domain_hint", "") or "").strip()
            doc_hint = str(analysis.get("doc_hint", "") or "").strip()
            section_hint_ai = str(analysis.get("section_hint", "") or "").strip()

            # AI要求澄清时，优先给出数据库真实候选清单
            if bool(analysis.get("need_clarify", False)):
                all_domains = self.kb.list_domains()
                if all_domains:
                    self.pending_kb_domains = all_domains[:6]
                    options = [f"{i}) {d.get('domain_name')}（{d.get('domain_code')}，文档数 {d.get('doc_count')}）" for i, d in enumerate(self.pending_kb_domains, 1)]
                    q = str(analysis.get("clarify_question", "") or "请先确认您要查询的知识领域：")
                    return {
                        "intent": "chat",
                        "route": "kb",
                        "response": q + "\n" + "\n".join(options) + "\n请回复序号或领域名称。",
                        "commands": [],
                        "citations": [],
                    }

            # 通用“公司文档/标准”请求：直接列领域，不盲查chunk
            generic_doc_ask = any(k in (effective_query or "") for k in ["文档", "手册", "标准", "知识库", "流程"])
            if generic_doc_ask and not domain_hint and not doc_hint and (ai_source in {"", "kb", "both", "unknown"}):
                all_domains = self.kb.list_domains()
                if len(all_domains) >= 2:
                    self.pending_kb_domains = all_domains[:6]
                    options = [f"{i}) {d.get('domain_name')}（{d.get('domain_code')}，文档数 {d.get('doc_count')}）" for i, d in enumerate(self.pending_kb_domains, 1)]
                    return {
                        "intent": "chat",
                        "route": "kb",
                        "response": "我已定位到公司知识库。请先选择您要查询的领域：\n" + "\n".join(options) + "\n请回复序号或领域名称。",
                        "commands": [],
                        "citations": [],
                    }

            domain_candidates = self.kb.retrieve_domain_candidates(effective_query, top_n=5)
            if len(domain_candidates) >= 2:
                self.pending_kb_domains = domain_candidates[:4]
                self.last_kb_query = effective_query
                options = [f"{i}) {d.get('domain_name')}（{d.get('domain_code')}，文档数 {d.get('doc_count')}）" for i, d in enumerate(self.pending_kb_domains, 1)]
                return {
                    "intent": "chat",
                    "route": "kb",
                    "response": "检测到多个可能领域，请先确认查询范围：\n" + "\n".join(options) + "\n请回复序号或领域名称。",
                    "commands": [],
                    "citations": [],
                }

            chosen_domain_code = ""
            if domain_hint:
                for d in self.kb.list_domains():
                    if domain_hint.lower() in str(d.get("domain_name", "")).lower() or domain_hint.lower() == str(d.get("domain_code", "")).lower():
                        chosen_domain_code = str(d.get("domain_code") or "")
                        break
            if not chosen_domain_code:
                chosen_domain_code = domain_candidates[0].get("domain_code") if len(domain_candidates) == 1 else self.db_domain_code

            candidates = self.kb.retrieve_candidates(doc_hint or effective_query, top_n=5, domain_code=str(chosen_domain_code or ""))
            if len(candidates) >= 2:
                self.pending_kb_options = candidates[:6]
                options = [f"{i}) {d.get('doc_title')}（{d.get('domain_name')}/{d.get('category')}）" for i, d in enumerate(self.pending_kb_options, 1)]
                return {
                    "intent": "chat",
                    "route": "kb",
                    "response": "检测到多个可能文档，请继续确认：\n" + "\n".join(options) + "\n请回复序号或文档名称。",
                    "commands": [],
                    "citations": [],
                }

            analysis = self._analyze_user_need(user_text)
            search_domain = str(chosen_domain_code or self.last_kb_domain_code or self.db_domain_code)

            # 若用户表达“流程有哪些/不全面”等，直接拉全流程（不再只返回局部）
            top_k = 20 if analysis.get("wants_full_flow") else 8

            search_query = effective_query
            if analysis.get("section_hint") and self.last_kb_doc_title:
                search_query = f"{self.last_kb_doc_title} {analysis.get('section_hint')}"

            chunks = self.kb.retrieve(
                query=search_query,
                top_k=top_k,
                domain_code=search_domain,
                doc_code=self.active_doc_code,
            )

            # 二次检索：使用最近文档标题增强
            if (not chunks) and self.last_kb_doc_title:
                refined_query = f"{self.last_kb_doc_title} {user_text}".strip()
                chunks = self.kb.retrieve(
                    query=refined_query,
                    top_k=top_k,
                    domain_code=search_domain,
                    doc_code=self.active_doc_code,
                )

            if not chunks and search_domain:
                chunks = self.kb.retrieve(
                    query=search_query,
                    top_k=top_k,
                    domain_code="",
                    doc_code=self.active_doc_code,
                )

            if not chunks:
                return {
                    "intent": "chat",
                    "route": "kb",
                    "response": "未检索到相关公司标准文档，请补充关键词（如模块名、部门名或文档名）。",
                    "commands": [],
                    "citations": [],
                }

            self.last_kb_query = effective_query
            self.last_kb_domain_code = search_domain
            if chunks:
                self.last_kb_doc_title = str(chunks[0].get("doc_title") or self.last_kb_doc_title)

            # 若用户在问“全部/完整/不全面”，先列出所有章节供继续细化
            if analysis.get("wants_full_flow"):
                doc_code_for_sections = self.active_doc_code or str(chunks[0].get("doc_code") or "")
                sections = self.kb.list_sections(doc_code=doc_code_for_sections)
                if sections:
                    self.active_doc_code = doc_code_for_sections
                    return self._build_section_list_response(sections)

            return self._build_kb_context_result(effective_query, chunks)

        if intent == "CAD_COMMAND":
            # 先进行绘图分析
            analysis = self._analyze_cad_drawing(user_text)

            if analysis.get("success"):
                # 基于分析结果生成命令
                commands = self._generate_cad_commands_from_analysis(analysis)
                analysis_data = analysis.get("analysis", {})

                response = f"已分析绘图需求：{analysis_data.get('drawing_type', '未知')}类型，复杂度{analysis_data.get('complexity', '未知')}，预计{analysis_data.get('estimated_commands', 0)}个命令。"
                response += f"\n布局策略：{analysis_data.get('layout_strategy', '标准布局')}"

                return {
                    "intent": "command_proxy",
                    "route": "cad",
                    "response": response,
                    "commands": commands,
                    "drawing_analysis": analysis_data
                }
            else:
                # 分析失败，回退到原有逻辑
                print(f"[Orchestrator] CAD分析失败，使用回退模式: {analysis.get('error', '未知错误')}")
                return {"intent": "command_proxy", "route": "cad", "response": "绘图分析失败，使用简化模式。", "commands": []}

        if intent == "ERP_QUERY":
            return {"intent": "chat", "route": "erp", "response": "ERP 查询能力正在接入中（下一阶段）。", "commands": [], "citations": []}

        if intent == "FILE_SEARCH":
            return {"intent": "chat", "route": "file", "response": "共享文件检索能力正在接入中（下一阶段）。", "commands": [], "citations": []}

        # ===== 新增: Web 检索路由 =====
        if intent == "CHAT":
            # 检查是否需要联网检索
            needs_web = analysis.get("needs_web", False)
            web_enabled = self.web_cfg.get("enabled", False)
            print(f"[Orchestrator Debug] intent={intent}, needs_web={needs_web}, web_enabled={web_enabled}")

            # 触发条件: 明确需要联网 (仅当 needs_web 为 True 时才触发)
            # 注意: 不再使用 "web_enabled and not kb_hit" 作为触发条件，
            # 避免普通对话也触发网络搜索
            if needs_web and web_enabled:
                try:
                    # 执行网络检索
                    query = analysis.get("web_keywords") or user_text
                    # 从 tavily 配置中读取 max_results
                    tavily_cfg = self.web_cfg.get("tavily", {})
                    max_results = tavily_cfg.get("max_results", 3)

                    if self.web_retriever:
                        web_results = self.web_retriever.search(query, max_results=max_results)

                        if web_results:
                            print(f"[Orchestrator] Web 检索成功: {len(web_results)} 条结果")
                            # 生成融合回答
                            return self._generate_with_web(user_text, web_results)
                        else:
                            print(f"[Orchestrator] Web 检索无结果: {query}")
                except Exception as e:
                    print(f"[Orchestrator] Web 检索失败: {e}")
                    # 降级到本地回答

            # 不需要联网或检索失败 → 返回空,由后续流程处理
            pass

        return {"intent": "command_proxy", "route": "chat", "response": "", "commands": [], "citations": []}
