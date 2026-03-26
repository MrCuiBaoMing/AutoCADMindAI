#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
绘图指令解析器
从 AI 响应中提取和验证绘图命令
"""

import re
import json
import math
import logging
from typing import Dict, List, Any, Optional, Tuple

logger = logging.getLogger(__name__)


class DrawingCommandParser:
    """解析 AI 返回的绘图指令，转换为标准格式"""
    
    # 支持的绘图类型
    SUPPORTED_TYPES = {
        "line", "circle", "rectangle", "rect", "arc", "text", 
        "polyline", "pline", "polygon", "point", "star"
    }
    
    # 默认参数
    DEFAULTS = {
        "line": {"layer": None},
        "circle": {"radius": 10, "layer": None},
        "rectangle": {"layer": None},
        "arc": {"radius": 10, "start_angle": 0, "end_angle": math.pi, "layer": None},
        "text": {"height": 2.5, "layer": None},
        "polyline": {"closed": False, "layer": None},
        "polygon": {"sides": 6, "layer": None},
        "star": {
            "center": (0, 0, 0),
            "outer_radius": 10,
            "inner_radius": 5,
            "points": 5,
            "start_angle": 0,
            "closed": True,
            "layer": None
        },
    }
    
    def __init__(self):
        self.validation_errors = []
    
    def parse_ai_response(self, ai_response: str) -> Dict[str, Any]:
        """
        解析 AI 响应，提取绘图指令
        
        Args:
            ai_response: AI 返回的文本或 JSON
        
        Returns:
            {
                "intent": "drawing" | "chat" | "command",
                "drawing_commands": [...],
                "response_text": str,
                "errors": list
            }
        """
        self.validation_errors = []
        
        result = {
            "intent": "chat",
            "drawing_commands": [],
            "response_text": ai_response,
            "errors": []
        }
        
        # 尝试解析为 JSON
        parsed_json = self._try_parse_json(ai_response)
        
        if parsed_json:
            # JSON 格式解析
            result["intent"] = parsed_json.get("intent", "chat")
            result["drawing_commands"] = self._extract_commands_from_json(parsed_json)
            
            # 保留 AI 的文字回复
            if "response" in parsed_json:
                result["response_text"] = parsed_json["response"]
            elif "message" in parsed_json:
                result["response_text"] = parsed_json["message"]
        
        else:
            # 尝试从文本中提取标记格式的指令
            commands = self._extract_commands_from_text(ai_response)
            if commands:
                result["intent"] = "drawing"
                result["drawing_commands"] = commands
        
        result["errors"] = self.validation_errors
        
        # 如果有绘图命令，确保 intent 为 drawing
        if result["drawing_commands"]:
            result["intent"] = "drawing"
        
        return result
    
    def _try_parse_json(self, text: str) -> Optional[Dict]:
        """尝试解析 JSON"""
        text = text.strip()
        
        # 直接解析
        if text.startswith("{") or text.startswith("["):
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                pass
        
        # 尝试提取 JSON 块
        json_patterns = [
            r'```json\s*([\s\S]*?)\s*```',  # ```json ... ```
            r'```\s*([\s\S]*?)\s*```',       # ``` ... ```
            r'\{[\s\S]*\}',                   # {...}
        ]
        
        for pattern in json_patterns:
            matches = re.findall(pattern, text)
            for match in matches:
                try:
                    return json.loads(match)
                except json.JSONDecodeError:
                    continue
        
        return None
    
    def _extract_commands_from_json(self, data: Dict) -> List[Dict]:
        """从 JSON 数据中提取绘图命令"""
        commands = []
        
        # 方式1: drawing_commands 字段
        if "drawing_commands" in data:
            raw_commands = data["drawing_commands"]
            if isinstance(raw_commands, list):
                for cmd in raw_commands:
                    validated = self._validate_command(cmd)
                    if validated:
                        commands.append(validated)
        
        # 方式2: commands 字段
        elif "commands" in data:
            raw_commands = data["commands"]
            if isinstance(raw_commands, list):
                for cmd in raw_commands:
                    # 可能是字符串命令，需要转换
                    if isinstance(cmd, str):
                        parsed = self._parse_string_command(cmd)
                        if parsed:
                            commands.append(parsed)
                    else:
                        validated = self._validate_command(cmd)
                        if validated:
                            commands.append(validated)
        
        # 方式3: 单个命令对象
        elif "type" in data and data["type"] in self.SUPPORTED_TYPES:
            validated = self._validate_command(data)
            if validated:
                commands.append(validated)
        
        return commands
    
    def _extract_commands_from_text(self, text: str) -> List[Dict]:
        """从文本中提取标记格式的指令"""
        commands = []
        
        # [DRAW_LINE] start=(0,0) end=(100,100)
        # [DRAW_CIRCLE] center=(50,50) radius=25
        patterns = {
            "line": r'\[DRAW_LINE\]\s*start=\(([\d.,\s]+)\)\s*end=\(([\d.,\s]+)\)',
            "circle": r'\[DRAW_CIRCLE\]\s*center=\(([\d.,\s]+)\)\s*radius=([\d.]+)',
            "rectangle": r'\[DRAW_RECT(?:ANGLE)?\]\s*corner1=\(([\d.,\s]+)\)\s*corner2=\(([\d.,\s]+)\)',
            "arc": r'\[DRAW_ARC\]\s*center=\(([\d.,\s]+)\)\s*radius=([\d.]+)\s*start=([\d.]+)\s*end=([\d.]+)',
        }
        
        # 解析直线
        for match in re.finditer(patterns["line"], text, re.IGNORECASE):
            try:
                start = self._parse_coords(match.group(1))
                end = self._parse_coords(match.group(2))
                commands.append({
                    "type": "line",
                    "start": start,
                    "end": end
                })
            except Exception as e:
                self.validation_errors.append(f"解析直线失败: {e}")
        
        # 解析圆
        for match in re.finditer(patterns["circle"], text, re.IGNORECASE):
            try:
                center = self._parse_coords(match.group(1))
                radius = float(match.group(2))
                commands.append({
                    "type": "circle",
                    "center": center,
                    "radius": radius
                })
            except Exception as e:
                self.validation_errors.append(f"解析圆失败: {e}")
        
        # 解析矩形
        for match in re.finditer(patterns["rectangle"], text, re.IGNORECASE):
            try:
                corner1 = self._parse_coords(match.group(1))
                corner2 = self._parse_coords(match.group(2))
                commands.append({
                    "type": "rectangle",
                    "corner1": corner1,
                    "corner2": corner2
                })
            except Exception as e:
                self.validation_errors.append(f"解析矩形失败: {e}")
        
        return commands
    
    def _parse_string_command(self, cmd_str: str) -> Optional[Dict]:
        """解析字符串命令（如 'LINE 0,0 100,100'）"""
        cmd_str = cmd_str.strip().upper()
        
        parts = cmd_str.split()
        if not parts:
            return None
        
        cmd_type = parts[0].lower()
        
        if cmd_type == "line" and len(parts) >= 3:
            try:
                start = self._parse_coords(parts[1])
                end = self._parse_coords(parts[2])
                return {"type": "line", "start": start, "end": end}
            except:
                pass
        
        elif cmd_type == "circle" and len(parts) >= 3:
            try:
                center = self._parse_coords(parts[1])
                radius = float(parts[2])
                return {"type": "circle", "center": center, "radius": radius}
            except:
                pass
        
        return None
    
    def _parse_coords(self, coord_str: str) -> Tuple[float, ...]:
        """解析坐标字符串"""
        # 移除括号和空格
        coord_str = coord_str.strip("()[]{}")
        # 分割数字
        parts = re.split(r'[,\s]+', coord_str)
        coords = [float(p) for p in parts if p]
        
        if len(coords) < 2:
            raise ValueError(f"坐标格式错误: {coord_str}")
        
        return tuple(coords)
    
    def _validate_command(self, cmd: Dict) -> Optional[Dict]:
        """验证和规范化绘图命令"""
        if not isinstance(cmd, dict):
            return None
        
        cmd_type = cmd.get("type", "").lower()
        
        if cmd_type not in self.SUPPORTED_TYPES:
            self.validation_errors.append(f"不支持的绘图类型: {cmd_type}")
            return None
        
        # 应用默认值
        defaults = self.DEFAULTS.get(cmd_type, {})
        validated = {**defaults, **cmd}
        validated["type"] = cmd_type
        
        # 类型特定验证
        if cmd_type == "line":
            if "start" not in validated or "end" not in validated:
                self.validation_errors.append("直线缺少起点或终点")
                return None
            validated["start"] = self._ensure_tuple(validated["start"])
            validated["end"] = self._ensure_tuple(validated["end"])
        
        elif cmd_type == "circle":
            if "center" not in validated:
                self.validation_errors.append("圆缺少圆心")
                return None
            if "radius" not in validated or validated["radius"] <= 0:
                self.validation_errors.append("圆缺少有效半径")
                return None
            validated["center"] = self._ensure_tuple(validated["center"])
        
        elif cmd_type in ("rectangle", "rect"):
            if "corner1" not in validated or "corner2" not in validated:
                self.validation_errors.append("矩形缺少角点")
                return None
            validated["corner1"] = self._ensure_tuple(validated["corner1"])
            validated["corner2"] = self._ensure_tuple(validated["corner2"])
            validated["type"] = "rectangle"  # 统一类型名
        
        elif cmd_type == "arc":
            if "center" not in validated or "radius" not in validated:
                self.validation_errors.append("圆弧缺少圆心或半径")
                return None
            validated["center"] = self._ensure_tuple(validated["center"])
            # 确保角度是弧度
            if "start_angle" not in validated:
                validated["start_angle"] = 0
            if "end_angle" not in validated:
                validated["end_angle"] = math.pi
        
        elif cmd_type == "text":
            if "content" not in validated and "text" in validated:
                validated["content"] = validated["text"]
            if "content" not in validated:
                self.validation_errors.append("文字缺少内容")
                return None
            if "position" not in validated:
                validated["position"] = (0, 0)
            validated["position"] = self._ensure_tuple(validated["position"])
        
        elif cmd_type in ("polyline", "pline"):
            if "points" not in validated or len(validated["points"]) < 2:
                self.validation_errors.append("多段线需要至少2个点")
                return None
            validated["points"] = [self._ensure_tuple(p) for p in validated["points"]]
            validated["type"] = "polyline"  # 统一类型名
        
        elif cmd_type == "polygon":
            if "sides" not in validated:
                validated["sides"] = 6
            if validated["sides"] < 3 or validated["sides"] > 1024:
                self.validation_errors.append("多边形边数必须在3-1024之间")
                return None
            if "center" not in validated:
                validated["center"] = (0, 0)
            if "radius" not in validated:
                validated["radius"] = 10
            validated["center"] = self._ensure_tuple(validated["center"])
        
        elif cmd_type == "star":
            if "center" not in validated:
                self.validation_errors.append("星形缺少中心点(center)")
                return None
            validated["center"] = self._ensure_tuple(validated["center"])
            if len(validated["center"]) < 2:
                self.validation_errors.append("星形中心点格式错误")
                return None
            
            outer_r = validated.get("outer_radius", None)
            inner_r = validated.get("inner_radius", None)
            if outer_r is None or float(outer_r) <= 0:
                self.validation_errors.append("星形缺少有效外半径(outer_radius)")
                return None
            if inner_r is None or float(inner_r) <= 0:
                self.validation_errors.append("星形缺少有效内半径(inner_radius)")
                return None
            validated["outer_radius"] = float(outer_r)
            validated["inner_radius"] = float(inner_r)
            
            pts = validated.get("points", None)
            if pts is None:
                pts = 5
            try:
                pts_i = int(pts)
            except Exception:
                pts_i = 5
            if pts_i < 3 or pts_i > 32:
                self.validation_errors.append("星形 points 必须在3-32之间")
                return None
            validated["points"] = pts_i
            
            validated["start_angle"] = float(validated.get("start_angle", 0))
            validated["closed"] = bool(validated.get("closed", True))
        
        return validated
    
    def _ensure_tuple(self, value) -> Tuple[float, ...]:
        """确保坐标是元组格式"""
        if isinstance(value, tuple):
            return value
        if isinstance(value, list):
            return tuple(float(v) for v in value)
        if isinstance(value, str):
            return self._parse_coords(value)
        return (0.0, 0.0, 0.0)


class DrawingIntentClassifier:
    """判断用户输入是否包含绘图意图"""
    
    # 绘图关键词
    DRAWING_KEYWORDS = [
        "画", "绘制", "创建", "新建", "生成", "添加", "插入",
        "圆", "圆弧", "直线", "线段", "矩形", "正方形", "多边形",
        "文字", "标注", "尺寸", "点",
        "半径", "直径", "圆心", "坐标"
    ]
    
    # 问题关键词（这些不是绘图意图）
    QUESTION_KEYWORDS = [
        "怎么", "如何", "为什么", "是什么", "什么是",
        "？", "?", "教程", "解释", "介绍", "能否", "可以吗", "请问"
    ]
    
    def is_drawing_intent(self, text: str) -> bool:
        """判断是否是绘图意图"""
        text_lower = text.lower()
        
        # 如果是问题句，很可能不是绘图意图
        if any(kw in text_lower for kw in self.QUESTION_KEYWORDS):
            return False
        
        # 检查是否包含绘图关键词
        return any(kw in text_lower for kw in self.DRAWING_KEYWORDS)
    
    def classify(self, text: str) -> str:
        """
        分类用户意图
        
        Returns:
            "drawing" | "command" | "chat"
        """
        text_lower = text.lower().strip()
        
        # 明确的绘图意图
        if self.is_drawing_intent(text_lower):
            return "drawing"
        
        # 命令执行意图（如 "执行 LINE 命令"）
        command_markers = ["执行", "运行", "输入命令"]
        if any(m in text_lower for m in command_markers):
            return "command"
        
        return "chat"


# 便捷函数
def parse_drawing_commands(ai_response: str) -> Dict[str, Any]:
    """解析 AI 响应中的绘图命令"""
    parser = DrawingCommandParser()
    return parser.parse_ai_response(ai_response)


def classify_user_intent(text: str) -> str:
    """分类用户意图"""
    classifier = DrawingIntentClassifier()
    return classifier.classify(text)
