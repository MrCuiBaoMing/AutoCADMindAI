#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工具注册与执行框架"""

from typing import Dict, Any, Callable, List, Optional
import json
import inspect

class Tool:
    """工具定义"""

    def __init__(self, name: str, description: str, parameters: Dict, handler: Callable):
        self.name = name
        self.description = description
        self.parameters = parameters
        self.handler = handler  # 实际执行函数

    def execute(self, arguments: Dict[str, Any]) -> Any:
        """执行工具"""
        return self.handler(arguments)

    def to_openai_schema(self) -> Dict:
        """转换为 OpenAI Function Calling 格式"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters
            }
        }


class ToolRegistry:
    """工具注册表"""

    def __init__(self):
        self.tools: Dict[str, Tool] = {}

    def register(self, tool: Tool):
        """注册工具"""
        self.tools[tool.name] = tool

    def get(self, name: str) -> Optional[Tool]:
        """获取工具"""
        return self.tools.get(name)

    def list_tools(self) -> List[Dict]:
        """列出所有工具（用于给 AI 的描述）"""
        return [tool.to_openai_schema() for tool in self.tools.values()]

    def execute_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """执行工具并返回结果"""
        tool = self.get(tool_name)
        if not tool:
            return {"success": False, "error": f"未知工具: {tool_name}"}
        try:
            result = tool.execute(arguments)
            return {"success": True, "result": result}
        except Exception as e:
            return {"success": False, "error": str(e)}


# 全局工具注册表
_registry = ToolRegistry()

def get_registry() -> ToolRegistry:
    """获取全局工具注册表"""
    return _registry

def register_tool(name: str, description: str, parameters: Dict, handler: Callable):
    """快捷注册工具"""
    tool = Tool(name, description, parameters, handler)
    _registry.register(tool)
    return tool
