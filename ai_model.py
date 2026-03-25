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
        system_prompt = "你是一个AutoCAD助手，能够将自然语言指令转换为AutoCAD命令。"
        system_prompt += "请分析用户的请求，返回相应的AutoCAD命令。"
        system_prompt += "如果需要执行多个命令，请按顺序列出。"
        system_prompt += "仅返回命令，不要包含其他解释。"
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
            return {"response": f"处理失败: {str(e)}", "commands": []}

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
            return {"response": f"处理失败: {str(e)}", "commands": []}

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

## 核心规则
1. 分析用户意图：是要绘图、问问题、还是其他操作
2. 绘图需求必须返回 intent="drawing" 和 drawing_commands
3. 只输出纯JSON，不要任何解释或额外内容

## 意图判断规则
- 包含"画、绘制、创建、生成、添加"等词 + 图形描述 → intent="drawing"
- 包含"怎么、如何、为什么、是什么"等疑问词 → intent="chat"
- 普通问候或对话 → intent="chat"

## 输出格式
{"intent":"drawing"|"chat","response":"给用户的回复","drawing_commands":[绘图指令数组]}

## 支持的绘图类型

### 矩形 rectangle
{"type":"rectangle","corner1":[左下x,左下y],"corner2":[右上x,右上y]}
- 用户说"矩形100*80"→ corner1:[0,0], corner2:[100,80]
- 用户说"矩形 长100宽50"→ corner1:[0,0], corner2:[100,50]

### 圆 circle
{"type":"circle","center":[x,y,0],"radius":半径}
- 用户说"半径50的圆"→ center:[0,0,0], radius:50
- 用户说"直径100的圆"→ center:[0,0,0], radius:50

### 直线 line
{"type":"line","start":[x1,y1,0],"end":[x2,y2,0]}

### 多边形 polygon
{"type":"polygon","center":[x,y],"radius":外接圆半径,"sides":边数}
- 用户说"正六边形"→ sides:6
- 用户说"正五边形"→ sides:5

### 圆弧 arc
{"type":"arc","center":[x,y,0],"radius":半径,"start_angle":起始弧度,"end_angle":结束弧度}

### 多段线 polyline
{"type":"polyline","points":[[x1,y1],[x2,y2],...],"closed":true|false}

### 文字 text
{"type":"text","content":"文字内容","position":[x,y,0],"height":字高}

## 示例对话

用户：画一个矩形100*80
输出：{"intent":"drawing","response":"已绘制矩形，尺寸100×80。","drawing_commands":[{"type":"rectangle","corner1":[0,0],"corner2":[100,80]}]}

用户：画一个半径50的圆
输出：{"intent":"drawing","response":"已绘制圆，半径50。","drawing_commands":[{"type":"circle","center":[0,0,0],"radius":50}]}

用户：画一个直径100的圆，圆心在(200,200)
输出：{"intent":"drawing","response":"已绘制圆，直径100，圆心(200,200)。","drawing_commands":[{"type":"circle","center":[200,200,0],"radius":50}]}

用户：画一个正六边形，半径30
输出：{"intent":"drawing","response":"已绘制正六边形，外接圆半径30。","drawing_commands":[{"type":"polygon","center":[0,0],"radius":30,"sides":6}]}

用户：画一个矩形 长200宽100 左下角在(50,50)
输出：{"intent":"drawing","response":"已绘制矩形。","drawing_commands":[{"type":"rectangle","corner1":[50,50],"corner2":[250,150]}]}

用户：画一条从(0,0)到(100,50)的直线
输出：{"intent":"drawing","response":"已绘制直线。","drawing_commands":[{"type":"line","start":[0,0,0],"end":[100,50,0]}]}

用户：你好
输出：{"intent":"chat","response":"你好！我是AutoCAD智能绘图助手，请告诉我你想绘制什么图形？","drawing_commands":[]}

用户：怎么画圆？
输出：{"intent":"chat","response":"你可以直接告诉我圆的参数，比如'画一个半径50的圆'，我会自动帮你绘制。","drawing_commands":[]}

## 重要提醒
- 用户描述不完整时，合理推断（如未指定位置默认原点）
- 直径要转半径：radius = 直径/2
- 坐标必须是数字，不能是字符串
- 必须严格遵守JSON格式，不要输出任何其他内容"""

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

        messages = [{"role": "system", "content": self._SYSTEM_PROMPT}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_prompt})

        data = {
            "model": self.model_name or "qwen2.5-0.5b-instruct",
            "messages": messages,
            "temperature": 0,  # 降低温度，减少随机性/推理过程
            "max_tokens": 500
        }

        # 如果有工具，尝试使用 tool_choice（部分模型支持）
        if tools_to_use:
            data["tools"] = tools_to_use

        # 调试日志
        print(f"[LMStudioModel] API URL: {api_url}")
        print(f"[LMStudioModel] 模型: {self.model_name}")
        print(f"[LMStudioModel] 消息数: {len(messages)}")
        print(f"[LMStudioModel] 请求数据: {json.dumps(data, ensure_ascii=False, indent=2)}")

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
                assistant_message = message.get("content", "")
            elif isinstance(message, str):
                assistant_message = message
            else:
                assistant_message = str(choice.get("content", ""))

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
                # 支持的意图类型: chat, command, drawing
                if intent not in ("chat", "command", "drawing"):
                    intent = "chat"
                commands = command_data.get("commands", [])
                if not isinstance(commands, list):
                    commands = []
                # 提取绘图命令
                drawing_commands = command_data.get("drawing_commands", [])
                if not isinstance(drawing_commands, list):
                    drawing_commands = []
                # 安全兜底：非 command 意图禁止下发命令
                if intent != "command":
                    commands = []
                return {
                    "intent": intent,
                    "response": command_data.get("response", assistant_message),
                    "commands": commands,
                    "drawing_commands": drawing_commands
                }

            # 若未返回JSON，直接按普通聊天文本返回，避免误拦截正常回答
            return {"intent": "chat", "response": assistant_message, "commands": []}
        except json.JSONDecodeError as e:
            return {"response": f"JSON解析失败: {str(e)}", "commands": []}
        except Exception as e:
            return {"response": f"处理失败: {str(e)}", "commands": []}

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
            "max_tokens": 200,  # 进一步减少到 200，加快生成速度
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
                content = message.get("content", "")
                return content.strip()
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
            return {"response": f"处理失败: {str(e)}", "commands": []}

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
