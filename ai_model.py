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
            response = requests.post(url, headers=headers, data=body, timeout=30)
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
            response = requests.post(url, headers=headers, data=body, timeout=30)
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

    _SYSTEM_PROMPT = """你是一个AutoCAD智能助手。

你只能输出纯JSON，不能输出任何其他内容、解释、推理过程。

禁止输出：
- "首先"、"根据"、"因为"、"所以"等推理词
- 任何解释你为什么这样回答的文字
- JSON以外的任何内容

输出格式（必须是这个格式）：
{"intent":"chat","response":"你的回复","commands":[]}

示例：
用户：你好
输出：{"intent":"chat","response":"你好！有什么可以帮你的吗？","commands":[]}

用户：画一个圆
输出：{"intent":"command","response":"好的，我来画圆","commands":["CIRCLE"]}"""

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
                if intent not in ("chat", "command"):
                    intent = "chat"
                commands = command_data.get("commands", [])
                if not isinstance(commands, list):
                    commands = []
                # 安全兜底：非 command 意图禁止下发命令
                if intent != "command":
                    commands = []
                return {
                    "intent": intent,
                    "response": command_data.get("response", assistant_message),
                    "commands": commands
                }

            # 若未返回JSON，直接按普通聊天文本返回，避免误拦截正常回答
            return {"intent": "chat", "response": assistant_message, "commands": []}
        except json.JSONDecodeError as e:
            return {"response": f"JSON解析失败: {str(e)}", "commands": []}
        except Exception as e:
            return {"response": f"处理失败: {str(e)}", "commands": []}

    def process_command(self, command: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """使用LM Studio处理命令（同步）"""
        print(f"[LM Studio] 开始处理命令: {command}")
        if not self.endpoint:
            return {"response": "错误: 未设置LM Studio端点", "commands": []}
        params = self.get_request_params(command, context)
        if not params:
            return {"response": "错误: 未设置LM Studio端点", "commands": []}
        url, headers, body = params
        try:
            response = requests.post(url, headers=headers, data=body, timeout=120)
            response.raise_for_status()
            return self.parse_response(response.content)
        except requests.exceptions.Timeout:
            return {"response": "请求超时，请检查LM Studio是否正常运行", "commands": []}
        except requests.exceptions.ConnectionError:
            return {"response": "无法连接到LM Studio，请确认服务已启动", "commands": []}
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
