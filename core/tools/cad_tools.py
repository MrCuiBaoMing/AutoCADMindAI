#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CAD 工具定义"""

from typing import Dict, Any

# CAD 命令工具参数模式
CAD_COMMAND_PARAMS = {
    "type": "object",
    "properties": {
        "command": {
            "type": "string",
            "description": "AutoCAD 命令名称，如 CIRCLE, LINE, RECTANG"
        },
        "params": {
            "type": "object",
            "description": "命令参数"
        }
    },
    "required": ["command"]
}

def get_cad_tools():
    """获取 CAD 相关工具列表"""
    return [
        {
            "name": "execute_cad_command",
            "description": "在 AutoCAD 中执行绘图命令。用于用户要求画图、建模、执行 CAD 操作时。",
            "parameters": CAD_COMMAND_PARAMS
        },
        {
            "name": "query_cad_status",
            "description": "查询 AutoCAD 连接状态和当前文档信息",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    ]
