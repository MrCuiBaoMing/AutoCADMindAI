#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""主流程编排器：意图识别 -> 工具路由 -> 返回统一结果"""

from __future__ import annotations

from typing import Dict, Any, List, Optional, Tuple
import json
import re

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

    def _collect_drawing_context(self, user_text: str) -> Dict[str, Any]:
        """从自然语言中提取上下文约束，支撑复杂图形/建筑绘制。"""
        text = (user_text or "").strip()
        lower = text.lower()

        intent_markers = {
            "building": ["建筑", "楼", "房", "立面", "平面图", "结构"],
            "mechanical": ["机械", "轴", "孔", "法兰", "零件"],
            "symbol": ["logo", "标志", "国旗", "图标", "纹样"],
        }
        domain = "general"
        for k, ws in intent_markers.items():
            if any(w in lower for w in ws):
                domain = k
                break

        style = "2d_plan"
        if any(w in lower for w in ["立面", "正视", "侧视"]):
            style = "2d_elevation"
        elif any(w in lower for w in ["三维", "3d", "立体"]):
            style = "3d_like"

        scale = "unknown"
        if any(w in lower for w in ["米", "m", "层高", "建筑"]):
            scale = "architectural"
        elif any(w in lower for w in ["mm", "毫米", "公差"]):
            scale = "mechanical"

        must_constraints = []
        if any(w in lower for w in ["对称", "中心对齐"]):
            must_constraints.append("symmetry")
        if any(w in lower for w in ["比例", "按比例"]):
            must_constraints.append("proportion")
        if any(w in lower for w in ["尺寸", "标注", "层高"]):
            must_constraints.append("dimensioning")
        if any(w in lower for w in ["不要重叠", "避免重叠"]):
            must_constraints.append("no_overlap")

        numbers = re.findall(r"\d+(?:\.\d+)?", text)

        return {
            "domain": domain,
            "drawing_style": style,
            "scale_hint": scale,
            "must_constraints": must_constraints,
            "number_tokens": numbers[:20],
            "raw_text": text,
        }

    def _refine_requirements(self, user_text: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """需求完善层：把模糊需求补全为可执行规格。"""
        c = context or {}
        refined = {
            "goal": (user_text or "").strip(),
            "domain": c.get("domain", "general"),
            "drawing_style": c.get("drawing_style", "2d_plan"),
            "scale_hint": c.get("scale_hint", "unknown"),
            "must_constraints": list(c.get("must_constraints") or []),
            "assumptions": [],
        }

        if "dimensioning" not in refined["must_constraints"]:
            refined["must_constraints"].append("dimensioning")
            refined["assumptions"].append("默认补充关键尺寸标注")

        if "no_overlap" not in refined["must_constraints"]:
            refined["must_constraints"].append("no_overlap")
            refined["assumptions"].append("默认做组件间隔与冲突规避")

        if refined["domain"] == "building":
            refined["assumptions"].append("默认先主体轴线与外轮廓，再门窗与细部")
        elif refined["domain"] == "mechanical":
            refined["assumptions"].append("默认先基准几何，再孔位与倒角圆角")
        else:
            refined["assumptions"].append("默认先主轮廓，再子图元与标注")

        return refined

    def _build_hierarchical_plan(self, requirement: Dict[str, Any]) -> Dict[str, Any]:
        """层级规划：将复杂图形拆解为阶段与子任务。"""
        domain = requirement.get("domain", "general")

        phases: List[Dict[str, Any]] = [
            {"phase": 1, "name": "coordinate_setup", "tasks": ["定义原点", "设定基准方向", "设定单位与尺度"]},
            {"phase": 2, "name": "primary_structure", "tasks": ["绘制主轮廓", "建立分区/层级"]},
            {"phase": 3, "name": "secondary_components", "tasks": ["补充内部结构", "放置重复构件"]},
            {"phase": 4, "name": "annotation_and_validation", "tasks": ["关键尺寸标注", "几何冲突检查", "可执行性检查"]},
        ]

        if domain == "building":
            phases[1]["tasks"] = ["绘制建筑外轮廓", "建立轴线网格", "定义层高分割"]
            phases[2]["tasks"] = ["门窗与立面分格", "楼梯/阳台等构件", "重复楼层阵列"]
        elif domain == "mechanical":
            phases[1]["tasks"] = ["基准外形", "基准圆/轴", "关键参考线"]
            phases[2]["tasks"] = ["孔槽细节", "阵列复制", "圆角倒角"]

        return {
            "strategy": "hierarchical_decomposition",
            "phases": phases,
            "success_criteria": ["命令可执行", "图元不重叠", "结构层次清晰", "关键尺寸可读"],
        }

    def _analyze_cad_drawing(self, user_text: str) -> Dict[str, Any]:
        """分析CAD绘图需求，生成结构化绘图计划"""
        if not self.ai_model:
            return {"error": "AI模型未配置"}

        try:
            context_pack = self._collect_drawing_context(user_text)
            refined_requirement = self._refine_requirements(user_text, context_pack)
            hierarchical_plan = self._build_hierarchical_plan(refined_requirement)

            # 使用分析prompt生成绘图计划
            analysis_prompt = CAD_ANALYSIS_PROMPT.format(user_input=user_text)
            analysis_result = self.ai_model.generate_with_context(analysis_prompt)
            
            # 检查返回结果
            if not analysis_result or not analysis_result.strip():
                print("[Orchestrator] AI 返回空结果，使用简化模式")
                return {
                    "success": False,
                    "error": "AI返回空结果",
                    "fallback": True,
                    "user_input": user_text
                }

            # 解析JSON结果
            try:
                analysis_data = json.loads(analysis_result.strip())
            except json.JSONDecodeError as e:
                # 尝试从文本中提取 JSON
                print(f"[Orchestrator] JSON 解析失败，尝试提取: {e}")
                json_match = re.search(r'\{[\s\S]*\}', analysis_result)
                if json_match:
                    try:
                        analysis_data = json.loads(json_match.group(0))
                    except Exception:
                        print("[Orchestrator] JSON 提取失败，使用简化模式")
                        return {
                            "success": False,
                            "error": "JSON解析失败",
                            "fallback": True,
                            "user_input": user_text
                        }
                else:
                    print("[Orchestrator] 未找到 JSON，使用简化模式")
                    return {
                        "success": False,
                        "error": "未找到有效JSON",
                        "fallback": True,
                        "user_input": user_text
                    }
            
            analysis_data["context_pack"] = context_pack
            analysis_data["refined_requirement"] = refined_requirement
            analysis_data["hierarchical_plan"] = hierarchical_plan

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
                "fallback": True,
                "user_input": user_text
            }

    def _generate_cad_commands_from_analysis(self, analysis: Dict[str, Any]) -> List[str]:
        """基于分析结果生成AutoCAD命令序列（命令行模式，兼容保留）。"""
        if not analysis.get("success", False):
            return []

        analysis_data = analysis.get("analysis", {})
        user_input = analysis.get("user_input", "")

        command_prompt = f"""基于以下绘图分析结果，生成具体的AutoCAD命令序列：

分析结果: {json.dumps(analysis_data, ensure_ascii=False, indent=2)}

用户原始需求: {user_input}

请生成可直接执行的AutoCAD命令列表。要求：
1. 按分析中的execution_order顺序生成命令
2. 使用精确坐标，避免重叠
3. 对于复杂图形，使用多条简单命令组合
4. 坐标系：X向右为正，Y向上为正，从(0,0)开始

返回格式：JSON {{"commands": ["命令1", "命令2", ...]}}
只返回JSON，不要其他文本。"""

        try:
            command_result = self.ai_model.generate_with_context(command_prompt)
            command_data = json.loads(command_result.strip())
            return command_data.get("commands", []) if isinstance(command_data, dict) else []
        except Exception as e:
            print(f"[Orchestrator] 命令生成失败: {e}")
            return []

    def _generate_structured_drawing_commands(self, analysis: Dict[str, Any]) -> List[Dict[str, Any]]:
        """基于分析结果生成结构化绘图命令（优先用于复杂图形）。"""
        if not analysis.get("success", False):
            return []

        analysis_data = analysis.get("analysis", {})
        user_input = analysis.get("user_input", "")

        def _extract_drawing_commands(raw_text: str) -> List[Dict[str, Any]]:
            raw_text = (raw_text or "").strip()
            if not raw_text:
                return []
            try:
                data = json.loads(raw_text)
            except Exception:
                # 容错：模型如果夹杂少量文本，仍尽量提取最外层 JSON 对象
                m = re.search(r"\{[\s\S]*\}", raw_text)
                if not m:
                    return []
                try:
                    data = json.loads(m.group(0))
                except Exception:
                    return []

            if isinstance(data, dict) and isinstance(data.get("drawing_commands"), list):
                return data.get("drawing_commands", [])
            return []

        def _needs_star_fix(text: str, commands: List[Dict[str, Any]]) -> bool:
            t = (text or "").lower()
            need = any(k in t for k in ["国旗", "旗帜", "旗", "星", "五角星", "star", "pentagram"])
            if not need:
                return False
            return not any(isinstance(c, dict) and str(c.get("type", "")).lower() == "star" for c in commands)

        drawing_prompt = f"""你是AutoCAD绘图命令生成器。请基于分析结果输出结构化绘图JSON。

分析结果：{json.dumps(analysis_data, ensure_ascii=False)}
用户需求：{user_input}

要求：
1) 只输出一个JSON对象
2) JSON格式必须是：{{"drawing_commands":[...]}}
3) drawing_commands 中每个元素必须是以下类型之一：
   - line: {{"type":"line","start":[x,y,0],"end":[x,y,0]}}
   - circle: {{"type":"circle","center":[x,y,0],"radius":r}}
   - rectangle: {{"type":"rectangle","corner1":[x1,y1],"corner2":[x2,y2]}}
   - polyline: {{"type":"polyline","points":[[x1,y1],[x2,y2],...],"closed":true|false}}
   - arc: {{"type":"arc","center":[x,y,0],"radius":r,"start_angle":a,"end_angle":b}}
   - text: {{"type":"text","content":"文字","position":[x,y,0],"height":h}}
   - star: {{"type":"star","center":[x,y,0],"outer_radius":r1,"inner_radius":r2,"points":p,"start_angle":a}}
4) 复杂图形拆解规则：先主体轮廓，再内部结构，再标注文本；每一步都生成独立命令
5) 坐标规则：优先正坐标；相邻组件至少间隔10；避免“互相完全重合”。允许“底图容器包含子图元”（例如星在旗帜矩形内部）
6) 数值规则：radius>0；rectangle 的 corner1 必须是左下点，corner2 必须是右上点
7) 多段线规则：points 至少2个点；如用于闭合轮廓，closed=true
8) 星形规则：如果用户描述了星/五角星/国旗/旗帜中的星，星形必须用 type='star' 输出（不要用 polygon(sides=5) 近似）
9) 不要输出解释文本，不要Markdown，不要代码块
"""

        try:
            raw = self.ai_model.generate_with_context(drawing_prompt)
            commands = _extract_drawing_commands(raw)

            # 针对“星形语义”做一次强制重试（避免把星画成五边形）
            if _needs_star_fix(user_input, commands):
                retry_prompt = drawing_prompt + "\n强制要求：星形符号必须输出 type='star'，并确保 points=5（五角星）或与用户描述一致；禁止使用 polygon 来当星形。"
                raw2 = self.ai_model.generate_with_context(retry_prompt)
                commands = _extract_drawing_commands(raw2) or commands

            # 结构化校验：过滤掉不符合 schema 的命令，减少后续执行异常
            from core.drawing_parser import DrawingCommandParser
            validator = DrawingCommandParser()
            validated = []
            for cmd in commands:
                if not isinstance(cmd, dict):
                    continue
                v = validator._validate_command(cmd)
                if v:
                    validated.append(v)
            return validated
        except Exception as e:
            print(f"[Orchestrator] 结构化绘图命令生成失败: {e}")
        return []

    def _generate_fallback_drawing_commands(self, user_text: str) -> List[Dict[str, Any]]:
        """降级方案：当复杂分析失败时，使用简化 prompt 直接生成绘图命令"""
        if not self.ai_model:
            return []
        
        fallback_prompt = f"""你是AutoCAD绘图助手。请根据用户需求生成绘图命令。

用户需求：{user_text}

要求：
1) 只输出一个JSON对象，格式：{{"drawing_commands":[...]}}
2) 支持的命令类型：
   - line: {{"type":"line","start":[x,y,0],"end":[x,y,0]}}
   - circle: {{"type":"circle","center":[x,y,0],"radius":r}}
   - rectangle: {{"type":"rectangle","corner1":[x1,y1],"corner2":[x2,y2]}}
   - polyline: {{"type":"polyline","points":[[x1,y1],[x2,y2],...],"closed":true|false}}
   - star: {{"type":"star","center":[x,y,0],"outer_radius":r1,"inner_radius":r2,"points":5,"start_angle":90}}
3) 坐标使用正数，半径大于0
4) 不要输出解释文本，只输出JSON

示例：
用户："画一个圆"
输出：{{"drawing_commands":[{{"type":"circle","center":[0,0,0],"radius":50}}]}}

用户："画一个五角星"
输出：{{"drawing_commands":[{{"type":"star","center":[0,0,0],"outer_radius":100,"inner_radius":38.2,"points":5,"start_angle":90}}]}}
"""
        
        try:
            raw = self.ai_model.generate_with_context(fallback_prompt)
            if not raw or not raw.strip():
                return []
            
            # 提取 JSON
            try:
                data = json.loads(raw.strip())
            except json.JSONDecodeError:
                # 尝试提取 JSON
                m = re.search(r'\{[\s\S]*\}', raw)
                if not m:
                    return []
                try:
                    data = json.loads(m.group(0))
                except Exception:
                    return []
            
            if not isinstance(data, dict):
                return []
            
            commands = data.get("drawing_commands", [])
            if not isinstance(commands, list):
                return []
            
            # 验证命令
            from core.drawing_parser import DrawingCommandParser
            validator = DrawingCommandParser()
            validated = []
            for cmd in commands:
                if not isinstance(cmd, dict):
                    continue
                v = validator._validate_command(cmd)
                if v:
                    validated.append(v)
            
            return validated
        except Exception as e:
            print(f"[Orchestrator] 降级绘图命令生成失败: {e}")
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
            # 先进行绘图分析（复杂图形场景）
            analysis = self._analyze_cad_drawing(user_text)

            if analysis.get("success"):
                analysis_data = analysis.get("analysis", {})
                drawing_commands = self._generate_structured_drawing_commands(analysis)

                # 执行前校验与回退环：复杂图形优先结构化命令，失败再降级
                from core.drawing_parser import DrawingCommandParser
                validator = DrawingCommandParser()
                validated_commands = []
                for cmd in drawing_commands:
                    v = validator._validate_command(cmd) if isinstance(cmd, dict) else None
                    if v:
                        validated_commands.append(v)

                # 若结构化命令为空，自动回退传统命令生成
                commands = []
                if not validated_commands:
                    commands = self._generate_cad_commands_from_analysis(analysis)

                context_pack = analysis_data.get("context_pack", {})
                refined_requirement = analysis_data.get("refined_requirement", {})
                hierarchical_plan = analysis_data.get("hierarchical_plan", {})

                response = f"已分析绘图需求：{analysis_data.get('drawing_type', '未知')}类型，复杂度{analysis_data.get('complexity', '未知')}，预计{analysis_data.get('estimated_commands', 0)}个步骤。"
                response += f"\n布局策略：{analysis_data.get('layout_strategy', '标准布局')}"
                response += f"\n规划策略：{hierarchical_plan.get('strategy', 'standard')}"
                response += f"\n上下文识别：领域={context_pack.get('domain', 'general')}，风格={context_pack.get('drawing_style', '2d_plan')}"
                if refined_requirement.get("assumptions"):
                    response += "\n需求完善：" + "；".join(refined_requirement.get("assumptions", [])[:3])

                return {
                    "intent": "command_proxy",
                    "route": "cad",
                    "response": response,
                    "commands": commands,
                    "drawing_commands": validated_commands,
                    "drawing_analysis": analysis_data
                }
            else:
                print(f"[Orchestrator] CAD分析失败，使用回退模式: {analysis.get('error', '未知错误')}")
                # 降级方案：直接使用 AI 模型生成绘图命令
                fallback_commands = self._generate_fallback_drawing_commands(user_text)
                if fallback_commands:
                    return {
                        "intent": "command_proxy",
                        "route": "cad",
                        "response": "已使用简化模式生成绘图命令。",
                        "commands": [],
                        "drawing_commands": fallback_commands,
                        "drawing_analysis": {}
                    }
                return {"intent": "command_proxy", "route": "cad", "response": "绘图分析失败，使用简化模式。", "commands": [], "drawing_commands": []}

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
