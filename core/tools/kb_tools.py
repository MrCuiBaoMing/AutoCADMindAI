#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""知识库工具定义"""

# 知识库工具参数模式
KB_SEARCH_PARAMS = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "搜索关键词"
        },
        "domain": {
            "type": "string",
            "description": "知识领域（可选）"
        }
    },
    "required": ["query"]
}

def get_kb_tools():
    """获取知识库相关工具列表"""
    return [
        {
            "name": "search_knowledge_base",
            "description": "搜索企业知识库。用于用户询问公司内部标准、流程、规范、文档时。",
            "parameters": KB_SEARCH_PARAMS
        }
    ]
