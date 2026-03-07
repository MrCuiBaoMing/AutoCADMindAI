#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI模型接口
集成各种AI大模型的API调用
"""

import os
import json
import requests
from typing import Dict, Any, Optional

class AIModel:
    """AI模型基类"""
    
    def process_command(self, command: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """处理命令"""
        raise NotImplementedError

class OpenAIModel(AIModel):
    """OpenAI模型实现"""
    
    def __init__(self, api_key: str = None, model: str = "gpt-4"):
        """初始化OpenAI模型"""
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.model = model
        self.api_base = "https://api.openai.com/v1/chat/completions"
        
        if not self.api_key:
            print("警告: 未设置OpenAI API密钥")
    
    def process_command(self, command: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """使用OpenAI处理命令"""
        print(f"[OpenAI] 开始处理命令: {command}")
        
        if not self.api_key:
            return {
                "response": "错误: 未设置OpenAI API密钥",
                "commands": []
            }
        
        try:
            # 构建系统提示
            system_prompt = "你是一个AutoCAD助手，能够将自然语言指令转换为AutoCAD命令。"
            system_prompt += "请分析用户的请求，返回相应的AutoCAD命令。"
            system_prompt += "如果需要执行多个命令，请按顺序列出。"
            system_prompt += "仅返回命令，不要包含其他解释。"
            
            # 构建用户提示
            user_prompt = f"用户请求: {command}\n"
            if context:
                user_prompt += f"上下文: {json.dumps(context)}\n"
            user_prompt += "请返回AutoCAD命令，格式为JSON: {\"commands\": [\"命令1\", \"命令2\"]}"
            
            # 发送请求
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}"
            }
            
            data = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "temperature": 0.1
            }
            
            response = requests.post(self.api_base, headers=headers, json=data, timeout=30)
            response.raise_for_status()
            
            # 解析响应
            result = response.json()
            print(f"[LM Studio] 响应内容: {json.dumps(result, indent=2, ensure_ascii=False)[:500]}")
            assistant_message = result['choices'][0]['message']['content']
            
            # 尝试解析JSON
            try:
                command_data = json.loads(assistant_message)
                commands = command_data.get('commands', [])
                return {
                    "response": f"已生成命令: {', '.join(commands)}",
                    "commands": commands
                }
            except json.JSONDecodeError:
                return {
                    "response": f"AI响应: {assistant_message}",
                    "commands": []
                }
                
        except Exception as e:
            return {
                "response": f"处理失败: {str(e)}",
                "commands": []
            }

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
    
    def process_command(self, command: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """使用Azure OpenAI处理命令"""
        if not self.api_key or not self.endpoint:
            return {
                "response": "错误: 未设置Azure OpenAI API密钥或端点",
                "commands": []
            }
        
        try:
            # 构建系统提示
            system_prompt = "你是一个AutoCAD助手，能够将自然语言指令转换为AutoCAD命令。"
            system_prompt += "请分析用户的请求，返回相应的AutoCAD命令。"
            
            # 构建用户提示
            user_prompt = f"用户请求: {command}"
            
            # 发送请求
            headers = {
                "Content-Type": "application/json",
                "api-key": self.api_key
            }
            
            data = {
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "temperature": 0.1
            }
            
            api_url = f"{self.endpoint}/openai/deployments/{self.deployment}/chat/completions?api-version=2024-02-15-preview"
            response = requests.post(api_url, headers=headers, json=data, timeout=30)
            response.raise_for_status()
            
            # 解析响应
            result = response.json()
            assistant_message = result['choices'][0]['message']['content']
            
            return {
                "response": f"AI响应: {assistant_message}",
                "commands": []
            }
            
        except Exception as e:
            return {
                "response": f"处理失败: {str(e)}",
                "commands": []
            }

class LMStudioModel(AIModel):
    """LM Studio本地模型实现"""
    
    def __init__(self, api_key: str = "", endpoint: str = "http://localhost:1234/v1", model_name: str = ""):
        """初始化LM Studio模型"""
        self.api_key = api_key
        self.endpoint = endpoint
        self.model_name = model_name
        
        if not self.endpoint:
            self.endpoint = "http://localhost:1234/v1"
    
    def process_command(self, command: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """使用LM Studio处理命令"""
        print(f"[LM Studio] 开始处理命令: {command}")
        print(f"[LM Studio] 端点: {self.endpoint}")
        print(f"[LM Studio] 模型: {self.model_name}")
        
        if not self.endpoint:
            return {
                "response": "错误: 未设置LM Studio端点",
                "commands": []
            }
        
        try:
            # 构建系统提示
            system_prompt = """你是一个AutoCAD智能助手。请根据用户的请求进行回复：

1. 如果用户只是问候或闲聊，请自然回复
2. 如果用户询问AutoCAD相关问题，请详细解答
3. 如果用户要求执行CAD操作（如"画一个圆形"），请返回JSON格式：{"commands": ["命令"], "response": "说明"}
4. 如果用户没有明确要求执行操作，请只返回自然语言回复

示例：
- 用户："你好" -> 回复："你好！我是AutoCAD助手，有什么可以帮助您的吗？"
- 用户："如何画圆？" -> 回复："画圆可以使用CIRCLE命令，需要指定圆心和半径"
- 用户："画一个圆形" -> 回复：{"commands": ["CIRCLE"], "response": "好的，我将为您绘制圆形"}"""
            
            # 构建用户提示
            user_prompt = f"用户请求: {command}\n"
            if context:
                user_prompt += f"上下文: {json.dumps(context)}\n"
            
            # 发送请求到LM Studio
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}"
            }
            
            data = {
                "model": self.model_name or "qwen2.5-0.5b-instruct",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "temperature": 0.1,
                "max_tokens": 500
            }
            
            api_url = f"{self.endpoint.rstrip('/')}/chat/completions"
            print(f"[LM Studio] 发送请求到: {api_url}")
            
            response = requests.post(
                api_url,
                headers=headers,
                json=data,
                timeout=120
            )
            print(f"[LM Studio] 收到响应，状态码: {response.status_code}")
            response.raise_for_status()
            
            result = response.json()
            print(f"[LM Studio] 响应内容: {json.dumps(result, ensure_ascii=False)[:500]}")
            
            if isinstance(result, str):
                return {"response": result, "commands": []}
            
            if not isinstance(result, dict):
                return {"response": f"响应格式错误: {type(result)}", "commands": []}
            
            if 'choices' not in result or not result['choices']:
                error_info = result.get('error', {})
                if isinstance(error_info, str):
                    error_msg = error_info
                else:
                    error_msg = error_info.get('message', '未知错误') if isinstance(error_info, dict) else '未知错误'
                return {"response": f"API错误: {error_msg}", "commands": []}
            
            choice = result['choices'][0]
            if isinstance(choice, dict) and 'message' in choice:
                assistant_message = choice['message'].get('content', '')
            elif isinstance(choice, str):
                assistant_message = choice
            else:
                return {"response": f"响应格式异常: {choice}", "commands": []}
            
            try:
                import re
                json_match = re.search(r'\{[^{}]*\}', assistant_message)
                if json_match:
                    command_data = json.loads(json_match.group())
                    return {
                        "response": command_data.get('response', assistant_message),
                        "commands": command_data.get('commands', [])
                    }
                return {"response": assistant_message, "commands": []}
            except json.JSONDecodeError:
                return {"response": assistant_message, "commands": []}
                
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
