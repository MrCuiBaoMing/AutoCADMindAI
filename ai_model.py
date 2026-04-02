#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI模型接口
集成各种AI大模型的API调用
支持同步 process_command 与异步请求参数 get_request_params/parse_response
"""

import os
import json
import re
import requests
from typing import Dict, Any, Optional, Tuple, List

def _extract_command_json(text: str) -> Optional[Dict[str, Any]]:
    """从模型回复中稳健提取 JSON 对象（支持 response 内多行、引号、括号），只返回含 response/commands 的 dict。"""
    if not text or not text.strip():
        return None
    text = text.strip()
    # 1) 整段即为 JSON
    try:
        obj = json.loads(text)
        if isinstance(obj, dict) and ("response" in obj or "commands" in obj):
            return obj
    except json.JSONDecodeError:
        pass
    # 2) 查找第一个 { 并匹配闭合 }
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = None
    escape = False
    for i in range(start, len(text)):
        c = text[i]
        if escape:
            escape = False
            continue
        if c == "\\" and in_string:
            escape = True
            continue
        if in_string:
            if c == in_string:
                in_string = None
            continue
        if c in ('"', "'"):
            in_string = c
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                try:
                    obj = json.loads(text[start : i + 1])
                    if isinstance(obj, dict) and ("response" in obj or "commands" in obj):
                        return obj
                except json.JSONDecodeError:
                    pass
                return None
    return None


class AIModel:
    """AI模型基类"""

    def process_command(self, command: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """处理命令（同步，可能阻塞）"""
        raise NotImplementedError

    def generate_with_context(self, prompt: str, context: Optional[Dict[str, Any]] = None) -> str:
        """
        使用自定义 prompt 和上下文生成回答

        Args:
            prompt: 自定义提示词
            context: 上下文信息(如 web_search_results)

        Returns:
            生成的回答文本
        """
        # 默认实现: 拼接 prompt + context,复用 process_command
        full_prompt = self._compose_prompt(prompt, context)
        result = self.process_command(full_prompt, context)
        return result.get("response", "") if isinstance(result, dict) else str(result)

    def _compose_prompt(self, prompt: str, context: Optional[Dict[str, Any]] = None) -> str:
        """
        组合 prompt 和上下文

        Args:
            prompt: 基础 prompt
            context: 上下文信息

        Returns:
            组合后的完整 prompt
        """
        if not context:
            return prompt

        # 如果有 web_search_results,将其注入到 prompt 中
        web_results = context.get("web_search_results")
        if web_results:
            web_content = "\n".join([
                f"- {r.get('title', '')}: {r.get('content', '')[:300]}"
                for r in web_results[:3]
            ])
            return f"{prompt}\n\n参考信息:\n{web_content}"

        return prompt

    def get_request_params(self, command: str, context: Optional[Dict[str, Any]] = None, history: Optional[list] = None) -> Optional[Tuple[str, Dict[str, str], bytes]]:
        """返回 (url, headers, body) 用于异步请求；history 为多轮对话历史 [{"role":"user"|"assistant","content":"..."}]"""
        return None

    def parse_response(self, data: bytes) -> Dict[str, Any]:
        """将 HTTP 响应体解析为 {response, commands}；仅网络模型需要实现"""
        return {"response": "", "commands": []}

class OpenAIModel(AIModel):
    """OpenAI模型实现"""

    def __init__(self, api_key: str = None, model: str = "gpt-4"):
        """初始化OpenAI模型"""
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.model = model
        self.api_base = "https://api.openai.com/v1/chat/completions"

        if not self.api_key:
            print("警告: 未设置OpenAI API密钥")

    def _build_messages(self, command: str, context: Optional[Dict[str, Any]] = None, history: Optional[list] = None):
        # 使用自定义提示词（如果有）
        system_prompt = context.get("custom_prompt", "") if context else ""
        if not system_prompt:
            system_prompt = "你是一个专业的AutoCAD绘图助手，专注于按用户需求生成可直接执行的AutoCAD命令。"
            system_prompt += "\n- 如果用户要求绘制建筑类图纸（如楼房正立面、平面图、层高、门窗等），请明确生成结构化坐标和尺寸，并尽量避免图形重叠。"
            system_prompt += "\n- 规则：只输出一个JSON对象，包含`commands`数组；不要输出多余文本。"
            system_prompt += "\n- 坐标系：X向右，Y向上；基准原点(0,0)一般为建筑左下角或用户指定基点。"
            system_prompt += "\n- 如果可能，请包含尺寸标注命令（例如 DIMLINEAR, DIMANGULAR），并标注关键层高/总高度。"
            system_prompt += "\n- 复杂图形可以分步执行：先外围墙体，再门窗再内饰。"
            system_prompt += "\n请分析用户需求并返回命令列表。"
        user_prompt = f"用户请求: {command}\n"
        if context:
            user_prompt += f"上下文: {json.dumps(context)}\n"
        user_prompt += "请返回AutoCAD命令，格式为JSON: {\"commands\": [\"命令1\", \"命令2\"]}"
        messages = [{"role": "system", "content": system_prompt}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_prompt})
        return messages

    def get_request_params(self, command: str, context: Optional[Dict[str, Any]] = None, history: Optional[list] = None) -> Optional[Tuple[str, Dict[str, str], bytes]]:
        if not self.api_key:
            return None
        url = self.api_base
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        data = {
            "model": self.model,
            "messages": self._build_messages(command, context, history),
            "temperature": 0.1
        }
        return url, headers, json.dumps(data, ensure_ascii=False).encode("utf-8")

    def parse_response(self, data: bytes) -> Dict[str, Any]:
        try:
            result = json.loads(data.decode("utf-8"))
            assistant_message = result["choices"][0]["message"]["content"]
            try:
                command_data = json.loads(assistant_message)
                commands = command_data.get("commands", [])
                return {"response": f"已生成命令: {', '.join(commands)}", "commands": commands}
            except json.JSONDecodeError:
                return {"response": f"AI响应: {assistant_message}", "commands": []}
        except Exception as e:
            return {"response": f"解析失败: {str(e)}", "commands": []}

    def process_command(self, command: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """使用OpenAI处理命令"""
        print(f"[OpenAI] 开始处理命令: {command}")
        if not self.api_key:
            return {"response": "错误: 未设置OpenAI API密钥", "commands": []}
        try:
            url, headers, body = self.get_request_params(command, context)
            response = requests.post(url, headers=headers, data=body, timeout=120)
            response.raise_for_status()
            return self.parse_response(response.content)
        except Exception as e:
            error_msg = str(e).encode('utf-8', errors='ignore').decode('utf-8', errors='ignore')
            return {"response": f"处理失败: {error_msg}", "commands": []}

class LocalModel(AIModel):
    """本地模型实现"""
    
    def __init__(self):
        """初始化本地模型"""
        # 简单的命令映射
        self.command_map = {
            "绘制直线": "LINE",
            "画直线": "LINE",
            "直线": "LINE",
            "绘制圆形": "CIRCLE",
            "画圆": "CIRCLE",
            "圆形": "CIRCLE",
            "绘制矩形": "RECTANG",
            "画矩形": "RECTANG",
            "矩形": "RECTANG",
            "移动": "MOVE",
            "移动对象": "MOVE",
            "复制": "COPY",
            "复制对象": "COPY",
            "删除": "ERASE",
            "删除对象": "ERASE",
            "标注": "DIMLINEAR",
            "尺寸标注": "DIMLINEAR",
            "缩放": "SCALE",
            "旋转": "ROTATE",
            "镜像": "MIRROR",
            "偏移": "OFFSET",
            "修剪": "TRIM",
            "延伸": "EXTEND",
            "圆角": "FILLET",
            "倒角": "CHAMFER"
        }
    
    def process_command(self, command: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """使用本地模型处理命令"""
        print(f"[LocalModel] 开始处理命令: {command}")
        
        # 匹配命令
        for key, cmd in self.command_map.items():
            if key in command:
                return {
                    "response": f"执行命令: {key}",
                    "commands": [cmd]
                }
        
        # 检查是否包含数字（可能是坐标或尺寸）
        import re
        numbers = re.findall(r'\d+\.?\d*', command)
        
        if numbers:
            return {
                "response": f"识别到数字: {', '.join(numbers)}",
                "commands": []
            }
        
        # 默认响应
        return {
            "response": f"收到命令: {command}",
            "commands": []
        }

class AzureOpenAIModel(AIModel):
    """Azure OpenAI模型实现"""
    
    def __init__(self, api_key: str = None, endpoint: str = None, deployment: str = "gpt-4"):
        """初始化Azure OpenAI模型"""
        self.api_key = api_key or os.environ.get("AZURE_OPENAI_KEY")
        self.endpoint = endpoint or os.environ.get("AZURE_OPENAI_ENDPOINT")
        self.deployment = deployment
        
        if not self.api_key or not self.endpoint:
            print("警告: 未设置Azure OpenAI API密钥或端点")

    def get_request_params(self, command: str, context: Optional[Dict[str, Any]] = None, history: Optional[list] = None) -> Optional[Tuple[str, Dict[str, str], bytes]]:
        if not self.api_key or not self.endpoint:
            return None
        api_url = f"{self.endpoint}/openai/deployments/{self.deployment}/chat/completions?api-version=2024-02-15-preview"
        headers = {"Content-Type": "application/json", "api-key": self.api_key}
        system_prompt = "你是一个AutoCAD助手，能够将自然语言指令转换为AutoCAD命令。请分析用户的请求，返回相应的AutoCAD命令。"
        messages = [{"role": "system", "content": system_prompt}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": f"用户请求: {command}"})
        data = {
            "messages": messages,
            "temperature": 0.1
        }
        return api_url, headers, json.dumps(data, ensure_ascii=False).encode("utf-8")

    def parse_response(self, data: bytes) -> Dict[str, Any]:
        try:
            result = json.loads(data.decode("utf-8"))
            assistant_message = result["choices"][0]["message"]["content"]
            return {"response": f"AI响应: {assistant_message}", "commands": []}
        except Exception as e:
            return {"response": f"解析失败: {str(e)}", "commands": []}

    def process_command(self, command: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """使用Azure OpenAI处理命令"""
        if not self.api_key or not self.endpoint:
            return {"response": "错误: 未设置Azure OpenAI API密钥或端点", "commands": []}
        params = self.get_request_params(command, context)
        if not params:
            return {"response": "错误: 未设置Azure OpenAI API密钥或端点", "commands": []}
        url, headers, body = params
        try:
            response = requests.post(url, headers=headers, data=body, timeout=120)
            response.raise_for_status()
            return self.parse_response(response.content)
        except Exception as e:
            error_msg = str(e).encode('utf-8', errors='ignore').decode('utf-8', errors='ignore')
            return {"response": f"处理失败: {error_msg}", "commands": []}

class LMStudioModel(AIModel):
    """LM Studio本地模型实现"""

    def __init__(self, api_key: str = "", endpoint: str = "http://localhost:1234/v1", model_name: str = ""):
        """初始化LM Studio模型"""
        self.api_key = api_key
        self.endpoint = endpoint
        self.model_name = model_name
        self.tools = []  # 工具清单

        if not self.endpoint:
            self.endpoint = "http://localhost:1234/v1"

        # 创建可复用的 Session，减少连接建立时间
        self._session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=1,
            pool_maxsize=5,
            max_retries=0
        )
        self._session.mount('https://', adapter)
        self._session.mount('http://', adapter)

    def set_tools(self, tools: List[Dict]):
        """设置工具清单（用于 Function Calling）"""
        self.tools = tools

    def _build_tools_prompt(self) -> str:
        """构建工具描述文本（用于不支持 Function Calling 的模型）"""
        if not self.tools:
            return ""
        desc = "\n可用工具：\n"
        for tool in self.tools:
            name = tool.get("name", "")
            desc += f"- {name}: {tool.get('description', '')}\n"
            params = tool.get("parameters", {}).get("properties", {})
            if params:
                desc += "  参数: " + ", ".join(params.keys()) + "\n"
        return desc

    _SYSTEM_PROMPT = """你是AutoCAD智能绘图助手，能理解用户自然语言描述并自动生成绘图指令。

## ⚠️ 重要：输出格式要求
- 必须只输出一个完整的JSON对象
- 不要在response字段中嵌套JSON字符串
- 不要添加任何解释、注释或额外文本
- JSON格式：{"intent":"drawing","response":"回复文本","drawing_commands":[...],"export_type":"..."}

## 核心规则
1. 分析用户意图：是要绘图、问问题、还是其他操作
2. 绘图需求必须返回 intent="drawing" 和 drawing_commands 数组
3. 只输出纯JSON，不要任何解释或额外内容
4. 一个请求可以返回多个绘图命令，按顺序执行
5. 对复杂图形先做“需求完善”：补充默认约束（尺寸、对齐、不重叠、分层）后再出命令
6. 对复杂建筑/复杂图案采用“分层分阶段”输出：主体轮廓 -> 结构分区 -> 细节构件 -> 标注
7. 优先输出可组合、可校验的小步骤命令，避免一次性巨型命令

## ⚠️ 坐标系统规则（非常重要）
- 原点(0,0)在左下角
- X轴向右为正，Y轴向上为正
- 尽量使用正数坐标，避免负数
- 图形从原点附近开始绘制
- 多个图形要有合理间距，避免重叠

## 意图判断规则
- 包含"画、绘制、创建、生成、添加、画个、帮我画"等词 + 图形描述 → intent="drawing"
- 包含"导出、导出Excel、导出表格、生成Excel、统计图纸、图纸信息"等词 → intent="export"
- 包含"怎么、如何、为什么、是什么"等疑问词 → intent="chat"
- 普通问候或对话 → intent="chat"

## 输出格式（严格遵守）
{"intent":"drawing"|"export"|"chat","response":"给用户的简短回复","drawing_commands":[绘图指令数组],"export_type":"all"|"layers"|"entities"}

### 绘图意图 drawing
返回绘图命令数组，不要在response中嵌套JSON

### 导出意图 export
返回 export_type 字段，可选值：
- "all": 导出全部信息（概览+图层+实体明细）
- "layers": 仅导出图层信息
- "entities": 仅导出实体明细
- "overview": 仅导出图纸概览

## 支持的绘图类型

### 矩形 rectangle
{"type":"rectangle","corner1":[左下x,左下y],"corner2":[右上x,右上y]}
示例：
- "矩形100*80" → corner1:[0,0], corner2:[100,80]
- "矩形 长200宽100 左下角(50,50)" → corner1:[50,50], corner2:[250,150]

### 圆 circle
{"type":"circle","center":[x,y,0],"radius":半径}
示例：
- "半径50的圆" → center:[0,0,0], radius:50
- "直径100的圆" → center:[0,0,0], radius:50（自动转换）
- "圆心在(200,150)直径80的圆" → center:[200,150,0], radius:40

### 直线 line
{"type":"line","start":[x1,y1,0],"end":[x2,y2,0]}
示例：
- "从(0,0)到(100,100)的直线" → start:[0,0,0], end:[100,100,0]
- "水平线长200从(50,50)开始" → start:[50,50,0], end:[250,50,0]

### 多边形 polygon
{"type":"polygon","center":[x,y],"radius":外接圆半径,"sides":边数}
示例：
- "正六边形" → sides:6（默认半径50）
- "正五边形半径30" → center:[0,0], radius:30, sides:5

### 圆弧 arc
{"type":"arc","center":[x,y,0],"radius":半径,"start_angle":起始弧度,"end_angle":结束弧度}
注意：角度使用弧度，半圆=π≈3.14159，四分之一圆≈1.5708

### 多段线 polyline
{"type":"polyline","points":[[x1,y1],[x2,y2],...],"closed":true|false}
用于绘制不规则多边形或连续折线

### 五角星 star
五角星需要使用polyline绘制，计算五个顶点坐标：
- 外圆半径R，内圆半径r（通常r = R * 0.382）
- 顶点角度：72度间隔，交替使用R和r
示例：
- "五角星半径50" → 使用polyline连接10个点（5个外点+5个内点）
坐标计算（以中心(50,50)为例）：
外点：[50+0,50+50],[50+47.55,50+15.45],[50+29.39,50-40.45],[50-29.39,50-40.45],[50-47.55,50+15.45]
内点：[50+0,50+19],[50+18.48,50-14.69],[50+45.0,50+0],[50+18.48,50+14.69],[50-18.48,50-14.69]

### 文字 text
{"type":"text","content":"文字内容","position":[x,y,0],"height":字高}

## 复杂图形处理规则

### 建筑/楼房绘图规范（重点）
- 当用户描述“楼房”“层高”“正立面”“平面图”等时，必须严谨输出多段命令：先外框墙体，再门窗，再层高标注。
- 四层楼建筑：按默认层高 3m 计算，总高度 12m；如果用户指定“楼房四层高度”，必须输出“每层3米，总高度12米”的尺寸描述或标注命令。
- 正立面视图：X 轴为水平距离，Y 轴为高度；应按层高依次绘制每层水平线。
- 平面图：应使用平面坐标，标出房间、门窗、墙厚、尺度等结构。

### 图形分解策略
对于复杂图形，按以下步骤分解：
1. **分析结构**：识别主体、组件、细节
2. **确定基准点**：选择一个合适的起点（通常是左下角或中心）
3. **计算坐标**：基于基准点计算各部分的相对位置
4. **避免重叠**：各组件之间保持合理间距

### 组合图形布局原则
- 第一个图形从(0,0)或(50,50)开始
- 后续图形在右侧或上方，保持50-100的间距
- 多个相同图形横向排列，间距=图形尺寸+20

### 常见复杂图形示例

#### 房子（侧面视图）
主体矩形 + 三角形屋顶：
1. 主体：rectangle corner1:[0,0], corner2:[100,80]
2. 屋顶：polyline points:[[0,80],[50,130],[100,80]], closed:true

#### 桌子（俯视图）
桌面 + 4条腿：
1. 桌面：rectangle corner1:[0,0], corner2:[200,100]
2. 左下腿：rectangle corner1:[10,10], corner2:[30,30]
3. 右下腿：rectangle corner1:[170,10], corner2:[190,30]
4. 左上腿：rectangle corner1:[10,70], corner2:[30,90]
5. 右上腿：rectangle corner1:[170,70], corner2:[190,90]

#### 板凳（侧面视图）
座面 + 4条腿：
1. 座面：rectangle corner1:[0,40], corner2:[120,50]
2. 左侧腿：rectangle corner1:[10,0], corner2:[20,40]
3. 右侧腿：rectangle corner1:[100,0], corner2:[110,40]

#### 房子平面图
外墙 + 门 + 窗户：
1. 外墙：rectangle corner1:[0,0], corner2:[200,150]
2. 门：rectangle corner1:[80,0], corner2:[120,20]
3. 左窗：rectangle corner1:[30,130], corner2:[60,145]
4. 右窗：rectangle corner1:[140,130], corner2:[170,145]

### 默认值处理
用户未指定参数时，使用合理默认值：
- 圆：默认半径50，圆心(0,0)
- 矩形：默认100×80，左下角(0,0)
- 正多边形：默认边数6，半径50
- 直线：需要起点终点，无法推断则询问

### 尺寸单位
用户可能说"100的圆"，根据语境判断：
- 通常指直径100（半径50）
- 或直接当半径100（需确认时按半径处理）

## 示例对话

### 基础示例
用户：画一个矩形100*80
输出：{"intent":"drawing","response":"已绘制矩形100×80。","drawing_commands":[{"type":"rectangle","corner1":[0,0],"corner2":[100,80]}]}

用户：画一个直径100的圆
输出：{"intent":"drawing","response":"已绘制圆，直径100。","drawing_commands":[{"type":"circle","center":[50,50,0],"radius":50}]}

用户：画一个正六边形
输出：{"intent":"drawing","response":"已绘制正六边形。","drawing_commands":[{"type":"polygon","center":[50,50],"radius":50,"sides":6}]}

### 五角星示例
用户：画一个五角星
输出：{"intent":"drawing","response":"已绘制五角星。","drawing_commands":[{"type":"polyline","points":[[50.0,100.0],[38.77,65.45],[2.45,65.45],[31.84,44.1],[20.61,9.55],[50.0,30.9],[79.39,9.55],[68.16,44.1],[97.55,65.45],[61.23,65.45]],"closed":true}]}

### 组合示例
用户：画一个圆和一个矩形
输出：{"intent":"drawing","response":"已绘制圆和矩形。","drawing_commands":[{"type":"circle","center":[50,50,0],"radius":50},{"type":"rectangle","corner1":[120,0],"corner2":[220,100]}]}

用户：画三个圆排成一行
输出：{"intent":"drawing","response":"已绘制三个圆排成一行。","drawing_commands":[{"type":"circle","center":[30,30,0],"radius":30},{"type":"circle","center":[90,30,0],"radius":30},{"type":"circle","center":[150,30,0],"radius":30}]}

### 复杂图形示例
用户：画一个房子（矩形主体+三角形屋顶）
输出：{"intent":"drawing","response":"已绘制房子图形。","drawing_commands":[{"type":"rectangle","corner1":[0,0],"corner2":[100,80]},{"type":"polyline","points":[[0,80],[50,130],[100,80]],"closed":true}]}

用户：绘制一个桌子
输出：{"intent":"drawing","response":"已绘制桌子。","drawing_commands":[{"type":"rectangle","corner1":[0,0],"corner2":[200,100]},{"type":"rectangle","corner1":[10,10],"corner2":[30,30]},{"type":"rectangle","corner1":[170,10],"corner2":[190,30]},{"type":"rectangle","corner1":[10,70],"corner2":[30,90]},{"type":"rectangle","corner1":[170,70],"corner2":[190,90]}]}

用户：绘制一个板凳
输出：{"intent":"drawing","response":"已绘制板凳。","drawing_commands":[{"type":"rectangle","corner1":[0,40],"corner2":[120,50]},{"type":"rectangle","corner1":[10,0],"corner2":[20,40]},{"type":"rectangle","corner1":[100,0],"corner2":[110,40]}]}

用户：画一个房子平面图，有门有窗户
输出：{"intent":"drawing","response":"已绘制房子平面图。","drawing_commands":[{"type":"rectangle","corner1":[0,0],"corner2":[200,150]},{"type":"rectangle","corner1":[80,0],"corner2":[120,20]},{"type":"rectangle","corner1":[30,135],"corner2":[60,150]},{"type":"rectangle","corner1":[140,135],"corner2":[170,150]}]}

### 对话示例
用户：你好
输出：{"intent":"chat","response":"你好！我是AutoCAD智能绘图助手，请告诉我你想绘制什么图形？","drawing_commands":[]}

用户：怎么画圆？
输出：{"intent":"chat","response":"你可以直接告诉我参数，比如'画一个半径50的圆'或'画一个直径100的圆'，我会自动帮你绘制。","drawing_commands":[]}

### 导出示例
用户：导出当前图纸信息到Excel
输出：{"intent":"export","response":"正在导出图纸信息到Excel...","export_type":"all"}

用户：导出图层信息
输出：{"intent":"export","response":"正在导出图层信息...","export_type":"layers"}

用户：统计图纸中的图形并导出
输出：{"intent":"export","response":"正在统计并导出图形信息...","export_type":"entities"}

用户：查看图纸概览并导出
输出：{"intent":"export","response":"正在生成图纸概览并导出...","export_type":"overview"}

## 重要提醒
1. 直径要转半径：radius = 直径/2
2. 坐标必须是数字，不能是字符串
3. 尽量使用正数坐标，从(0,0)或小正数开始
4. 复杂图形分解为多个基本图形命令，注意坐标计算
5. 必须严格遵守JSON格式
6. 不确定的参数使用合理默认值，不要询问
7. 导出意图必须包含 export_type 字段"""

    def _extract_tool_call(self, text: str) -> Optional[Dict[str, Any]]:
        """从模型输出中提取工具调用"""
        text = text.strip()

        # 尝试直接解析为 JSON
        try:
            obj = json.loads(text)
            if isinstance(obj, dict):
                # 检查是否是工具调用格式
                if "tool_calls" in obj:
                    return obj["tool_calls"]
                if "tool" in obj and "arguments" in obj:
                    return [obj]
        except:
            pass

        # 尝试从文本中提取工具调用（兼容格式）
        # 格式: {"tool":"execute_cad_command","arguments":{"command":"CIRCLE"}}
        import re
        patterns = [
            r'"tool"\s*:\s*"([^"]+)"',
            r'"function"\s*:\s*"([^"]+)"',
            r'"name"\s*:\s*"([^"]+)"'
        ]
        for pattern in patterns:
            matches = re.findall(pattern, text)
            if matches:
                # 尝试提取 arguments
                args_match = re.search(r'"arguments"\s*:\s*(\{[^}]+\})', text)
                if args_match:
                    try:
                        args = json.loads(args_match.group(1))
                        return [{"function": {"name": matches[0], "arguments": args}}]
                    except:
                        pass

        return None

    def get_request_params(self, command: str, context: Optional[Dict[str, Any]] = None, history: Optional[list] = None, tools: Optional[List[Dict]] = None) -> Optional[Tuple[str, Dict[str, str], bytes]]:
        if not self.endpoint:
            return None
        api_url = f"{self.endpoint.rstrip('/')}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

        # 【优化】只提取关键路由信息，忽略冗长的文档内容
        route_hint = ""
        if context:
            route = context.get("route", "")
            analysis = context.get("analysis", {})
            if route == "kb":
                route_hint = "[知识库模式] 用户在询问公司内部标准/文档。"
            elif route == "cad":
                route_hint = "[CAD模式] 用户在请求执行AutoCAD操作。"

        # 构建用户提示：只包含当前输入和必要的路由提示
        user_prompt = command
        if route_hint:
            user_prompt = f"{route_hint}\n\n用户请求: {command}"

        # 【工具调用】添加工具描述
        tools_to_use = tools or self.tools
        tools_prompt = self._build_tools_prompt()
        if tools_prompt:
            user_prompt = f"{tools_prompt}\n\n{user_prompt}"

        # 使用自定义提示词（如果有）
        system_prompt = context.get("custom_prompt", "") if context else ""
        if not system_prompt:
            system_prompt = self._SYSTEM_PROMPT
        messages = [{"role": "system", "content": system_prompt}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_prompt})

        data = {
            "model": self.model_name or "qwen2.5-0.5b-instruct",
            "messages": messages,
            "temperature": 0,
            "top_p": 0.9,
            "max_tokens": 1600
        }

        # 如果有工具，尝试使用 tool_choice（部分模型支持）
        if tools_to_use:
            data["tools"] = tools_to_use

        # 调试日志
        print(f"[LMStudioModel] API URL: {api_url}")
        print(f"[LMStudioModel] 模型: {self.model_name}")
        print(f"[LMStudioModel] 消息数: {len(messages)}")
        print(f"[LMStudioModel] 请求数据: {json.dumps(data, ensure_ascii=True, indent=2)}")

        return api_url, headers, json.dumps(data, ensure_ascii=False).encode("utf-8")

    def parse_response(self, data: bytes) -> Dict[str, Any]:
        try:
            result = json.loads(data.decode("utf-8"))
            if isinstance(result, str):
                return {"response": result, "commands": []}
            if not isinstance(result, dict):
                return {"response": f"响应格式错误: {type(result)}", "commands": []}
            if "choices" not in result or not result["choices"]:
                err = result.get("error", {})
                msg = err.get("message", "未知错误") if isinstance(err, dict) else (err if isinstance(err, str) else "未知错误")
                return {"response": f"API错误: {msg}", "commands": []}
            choice = result["choices"][0]

            # 【工具调用】检测模型是否返回了工具调用
            message = choice.get("message", {})
            tool_calls = message.get("tool_calls", [])

            # 1. 检查 OpenAI 格式的工具调用
            if tool_calls:
                parsed_calls = []
                for tc in tool_calls:
                    func = tc.get("function", {})
                    parsed_calls.append({
                        "name": func.get("name", ""),
                        "arguments": func.get("arguments", {})
                    })
                return {
                    "intent": "tool_call",
                    "tool_calls": parsed_calls,
                    "response": "需要执行工具",
                    "commands": []
                }

            # 2. 普通消息处理
            if isinstance(message, dict):
                assistant_message = message.get("content")
            elif isinstance(message, str):
                assistant_message = message
            else:
                assistant_message = choice.get("content")

            # 兼容：content 为 None 或空时，尝试拼接多段/工具输出
            if assistant_message is None:
                assistant_message = ""

            if isinstance(assistant_message, list):
                # 兼容部分模型返回分片列表
                joined = []
                for item in assistant_message:
                    if isinstance(item, dict):
                        seg = item.get("text") or item.get("content") or ""
                        joined.append(str(seg))
                    else:
                        joined.append(str(item))
                assistant_message = "".join(joined).strip()
            else:
                assistant_message = str(assistant_message).strip()

            # 兜底：若仍为空，尝试从 choice 里找文本字段
            if not assistant_message:
                assistant_message = str(choice.get("text") or "").strip()

            # 2.1 尝试解析自定义格式的工具调用（部分模型可能输出 JSON 格式的工具调用）
            if assistant_message:
                custom_tool_call = self._extract_tool_call(assistant_message)
                if custom_tool_call:
                    return {
                        "intent": "tool_call",
                        "tool_calls": custom_tool_call,
                        "response": "需要执行工具",
                        "commands": []
                    }

            # 稳健解析：先尝试整段为 JSON，再尝试提取首段完整 JSON 对象（支持 response 内多字符、引号、括号）
            command_data = _extract_command_json(assistant_message)
            if command_data is not None:
                intent = command_data.get("intent", "chat")
                # 支持的意图类型: chat, command, drawing, export
                if intent not in ("chat", "command", "drawing", "export"):
                    intent = "chat"
                commands = command_data.get("commands", [])
                if not isinstance(commands, list):
                    commands = []
                # 提取绘图命令
                drawing_commands = command_data.get("drawing_commands", [])
                if not isinstance(drawing_commands, list):
                    drawing_commands = []
                # 提取导出类型
                export_type = command_data.get("export_type", "all")
                
                # 【关键修复】如果 intent 是 chat 但 response 内容是嵌套的 JSON，再次解析
                if intent == "chat" and (drawing_commands == [] or not drawing_commands):
                    response_text = command_data.get("response", "")
                    if response_text and response_text.strip().startswith("{"):
                        # 尝试解析嵌套JSON，即使不完整也尝试提取有用信息
                        nested_data = _extract_command_json(response_text)
                        if nested_data is not None:
                            nested_intent = nested_data.get("intent", "chat")
                            if nested_intent in ("chat", "command", "drawing", "export"):
                                intent = nested_intent
                                commands = nested_data.get("commands", [])
                                if not isinstance(commands, list):
                                    commands = []
                                drawing_commands = nested_data.get("drawing_commands", [])
                                if not isinstance(drawing_commands, list):
                                    drawing_commands = []
                                export_type = nested_data.get("export_type", "all")
                                command_data["response"] = nested_data.get("response", response_text)
                                command_data["intent"] = intent
                        else:
                            # 如果标准JSON解析失败，尝试手动解析不完整的JSON
                            try:
                                # 查找intent字段
                                intent_match = re.search(r'"intent"\s*:\s*"([^"]+)"', response_text)
                                if intent_match and intent_match.group(1) in ("drawing", "export"):
                                    intent = intent_match.group(1)
                                    command_data["intent"] = intent

                                    # 查找drawing_commands字段
                                    dc_match = re.search(r'"drawing_commands"\s*:\s*(\[[^\]]*\])', response_text)
                                    if dc_match:
                                        try:
                                            drawing_commands = json.loads(dc_match.group(1))
                                            if isinstance(drawing_commands, list):
                                                command_data["drawing_commands"] = drawing_commands
                                        except:
                                            pass

                                    # 查找response字段
                                    resp_match = re.search(r'"response"\s*:\s*"([^"]*)"', response_text)
                                    if resp_match:
                                        command_data["response"] = resp_match.group(1)

                                    # 查找export_type字段
                                    et_match = re.search(r'"export_type"\s*:\s*"([^"]*)"', response_text)
                                    if et_match:
                                        export_type = et_match.group(1)
                                        command_data["export_type"] = export_type

                            except Exception as e:
                                print(f"[AI Model] 手动解析嵌套JSON失败: {e}")
                                pass
                
                # 安全兜底：仅 command 允许通用 commands，下发绘图走 drawing_commands
                if intent != "command":
                    commands = []
                if intent == "drawing" and (not drawing_commands) and isinstance(command_data.get("commands"), list):
                    # 兼容某些模型把结构化绘图命令误放在 commands 字段
                    drawing_commands = command_data.get("commands", [])
                    commands = []
                return {
                    "intent": intent,
                    "response": command_data.get("response", assistant_message),
                    "commands": commands,
                    "drawing_commands": drawing_commands,
                    "export_type": export_type
                }

            # 若未返回JSON，直接按普通聊天文本返回，避免误拦截正常回答
            return {"intent": "chat", "response": assistant_message, "commands": []}
        except json.JSONDecodeError as e:
            error_msg = str(e).encode('utf-8', errors='ignore').decode('utf-8', errors='ignore')
            return {"response": f"JSON解析失败: {error_msg}", "commands": []}
        except Exception as e:
            error_msg = str(e).encode('utf-8', errors='ignore').decode('utf-8', errors='ignore')
            return {"response": f"处理失败: {error_msg}", "commands": []}

    def _get_timeout(self) -> int:
        """根据端点类型返回适当的超时时间（秒）"""
        if not self.endpoint:
            return 120
        # NVIDIA API 首次加载模型需要较长时间（60-120秒）
        if "nvidia.com" in self.endpoint:
            return 180
        # 其他云端模型也可能需要较长时间
        if "api." in self.endpoint or "cloud" in self.endpoint:
            return 120
        # 本地模型响应较快
        return 60

    def generate_with_context(self, prompt: str, context: Optional[Dict[str, Any]] = None) -> str:
        """
        使用自定义 prompt 和上下文生成回答（用于 Web 搜索等场景）
        注意：此方法不使用 JSON 格式的系统 prompt，而是直接发送文本 prompt
        
        优化：使用类级别 Session 复用连接，减少网络延迟
        """
        if not self.endpoint:
            return "错误: 未设置模型端点"

        api_url = f"{self.endpoint.rstrip('/')}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "Connection": "keep-alive"
        }

        # 使用简单的系统 prompt，不要求 JSON 格式
        system_prompt = "你是一个 helpful 的助手。请根据提供的信息回答用户问题。"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ]

        # 优化：减少 max_tokens 以加快响应速度
        data = {
            "model": self.model_name or "qwen2.5-0.5b-instruct",
            "messages": messages,
            "temperature": 0.3,
            "max_tokens": 400,  # 增加到400，确保分析和命令生成有足够空间
            "top_p": 0.9,
            "frequency_penalty": 0,
            "presence_penalty": 0
        }

        try:
            timeout = self._get_timeout()
            
            print(f"[LMStudioModel] 开始生成回答，timeout={timeout}s...")
            start_time = __import__('time').time()
            
            # 使用类级别的 Session 复用连接
            response = self._session.post(api_url, headers=headers, json=data, timeout=timeout)
            response.raise_for_status()
            result = response.json()
            
            elapsed = __import__('time').time() - start_time
            print(f"[LMStudioModel] 生成完成，耗时: {elapsed:.2f}s")

            # 直接提取文本内容
            if "choices" in result and result["choices"]:
                message = result["choices"][0].get("message", {})
                content = message.get("content", "") or ""
                return content.strip() if content else ""
            return "无法获取模型响应"
        except Exception as e:
            print(f"[LMStudioModel] generate_with_context 失败: {e}")
            return f"生成回答失败: {str(e)}"

    def process_command(self, command: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """使用LM Studio处理命令（同步）"""
        print(f"[LM Studio] 开始处理命令: {command}")
        if not self.endpoint:
            return {"response": "错误: 未设置LM Studio端点", "commands": []}
        params = self.get_request_params(command, context)
        if not params:
            return {"response": "错误: 未设置LM Studio端点", "commands": []}
        url, headers, body = params
        timeout = self._get_timeout()
        try:
            # 使用类级别的 Session 复用连接
            response = self._session.post(url, headers=headers, data=body, timeout=timeout)
            response.raise_for_status()
            return self.parse_response(response.content)
        except requests.exceptions.Timeout:
            return {"response": f"请求超时（{timeout}秒），请检查网络或模型状态", "commands": []}
        except requests.exceptions.ConnectionError:
            return {"response": "无法连接到模型服务，请确认服务已启动", "commands": []}
        except Exception as e:
            error_msg = str(e).encode('utf-8', errors='ignore').decode('utf-8', errors='ignore')
            return {"response": f"处理失败: {error_msg}", "commands": []}

def get_ai_model(model_type: str = "local", **kwargs) -> AIModel:
    """获取AI模型实例"""
    if model_type == "openai":
        return OpenAIModel(**kwargs)
    elif model_type == "azure":
        return AzureOpenAIModel(**kwargs)
    elif model_type == "lmstudio":
        # 将 deployment 参数映射为 model_name
        if 'deployment' in kwargs:
            kwargs['model_name'] = kwargs.pop('deployment')
        return LMStudioModel(**kwargs)
    else:
        return LocalModel()
