#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""技能管理器：加载、管理和执行各种技能"""

import os
import json
import fnmatch
from typing import Dict, Any, Optional

# 尝试导入知识库检索器
try:
    from connectors.kb_sqlserver.retriever import KBRetriever
except ImportError:
    KBRetriever = None


class SkillManager:
    def __init__(self, skills_dir="skills"):
        """初始化技能管理器
        
        Args:
            skills_dir: 技能目录路径
        """
        self.skills_dir = skills_dir
        self.skills = {}
        self.load_skills()
        
        # 初始化知识库检索器
        self.kb_retriever = None
        try:
            if KBRetriever:
                # 这里可以从配置文件读取连接字符串
                # 暂时使用默认连接字符串
                connection_string = "Data Source=127.0.0.1;Initial Catalog=AutoCADKB;User ID=sa;Password=your_password;"
                self.kb_retriever = KBRetriever(connection_string)
        except Exception as e:
            print(f"初始化知识库检索器失败: {e}")
    
    def load_skills(self):
        """加载所有技能"""
        if not os.path.exists(self.skills_dir):
            return
        
        for skill_name in os.listdir(self.skills_dir):
            skill_path = os.path.join(self.skills_dir, skill_name)
            if os.path.isdir(skill_path):
                skill_file = os.path.join(skill_path, "skill.json")
                if os.path.exists(skill_file):
                    try:
                        with open(skill_file, 'r', encoding='utf-8') as f:
                            skill_data = json.load(f)
                        # 加载提示词文件
                        prompt_file = os.path.join(skill_path, skill_data.get("prompt_file", "prompt.txt"))
                        if os.path.exists(prompt_file):
                            with open(prompt_file, 'r', encoding='utf-8') as f:
                                skill_data["prompt"] = f.read()
                        self.skills[skill_name] = skill_data
                    except Exception as e:
                        print(f"加载技能 {skill_name} 失败: {e}")
    
    def get_skill(self, skill_name: str) -> Optional[Dict[str, Any]]:
        """获取技能实例
        
        Args:
            skill_name: 技能名称
            
        Returns:
            技能数据字典，如果技能不存在则返回 None
        """
        return self.skills.get(skill_name)
    
    def execute_skill(self, skill_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """执行技能
        
        Args:
            skill_name: 技能名称
            params: 技能参数
            
        Returns:
            技能执行结果
        """
        skill = self.get_skill(skill_name)
        if not skill:
            return {"success": False, "message": f"技能 {skill_name} 不存在"}
        
        if not skill.get("enabled", True):
            return {"success": False, "message": f"技能 {skill_name} 已禁用"}
        
        # 具体技能执行逻辑
        try:
            if skill_name == "cad_drawing":
                return self._execute_cad_drawing(params)
            elif skill_name == "kb_query":
                return self._execute_kb_query(params)
            elif skill_name == "file_search":
                return self._execute_file_search(params)
            elif skill_name == "erp_query":
                return self._execute_erp_query(params)
            else:
                # 默认返回技能信息
                return {
                    "success": True,
                    "skill": skill_name,
                    "params": params,
                    "prompt": skill.get("prompt", "")
                }
        except Exception as e:
            return {"success": False, "message": f"执行技能 {skill_name} 失败: {str(e)}"}
    
    def _execute_cad_drawing(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """执行CAD绘图技能
        
        Args:
            params: 绘图参数
            
        Returns:
            执行结果
        """
        drawing_type = params.get("drawing_type", "")
        dimensions = params.get("dimensions", {})
        position = params.get("position", {})
        
        # 生成CAD命令
        commands = []
        if drawing_type == "circle":
            radius = dimensions.get("radius", 10)
            x = position.get("x", 0)
            y = position.get("y", 0)
            commands.append(f"CIRCLE {x},{y} {radius}")
        elif drawing_type == "line":
            start_x = position.get("start_x", 0)
            start_y = position.get("start_y", 0)
            end_x = position.get("end_x", 100)
            end_y = position.get("end_y", 100)
            commands.append(f"LINE {start_x},{start_y} {end_x},{end_y}")
        elif drawing_type == "rectangle":
            width = dimensions.get("width", 100)
            height = dimensions.get("height", 100)
            x = position.get("x", 0)
            y = position.get("y", 0)
            commands.append(f"RECTANG {x},{y} {x + width},{y + height}")
        
        return {
            "success": True,
            "skill": "cad_drawing",
            "drawing_type": drawing_type,
            "commands": commands,
            "message": f"生成了 {len(commands)} 个CAD命令"
        }
    
    def _execute_kb_query(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """执行知识库查询技能
        
        Args:
            params: 查询参数
            
        Returns:
            执行结果
        """
        query = params.get("query", "")
        
        # 使用实际的知识库检索器
        if self.kb_retriever:
            try:
                results = self.kb_retriever.retrieve(query, top_k=5)
                # 格式化结果
                formatted_results = []
                for result in results:
                    formatted_results.append({
                        "title": result.get("doc_title", "未知文档"),
                        "content": result.get("chunk_content", ""),
                        "score": result.get("score", 0)
                    })
                return {
                    "success": True,
                    "skill": "kb_query",
                    "query": query,
                    "results": formatted_results,
                    "message": f"知识库查询完成，找到 {len(formatted_results)} 条结果"
                }
            except Exception as e:
                # 如果知识库查询失败，返回模拟结果
                return {
                    "success": False,
                    "skill": "kb_query",
                    "query": query,
                    "message": f"知识库查询失败: {str(e)}",
                    "results": [
                        {"title": "AutoCAD基本命令", "content": "LINE - 绘制直线, CIRCLE - 绘制圆, RECTANG - 绘制矩形"},
                        {"title": "AutoCAD快捷键", "content": "Ctrl+C - 复制, Ctrl+V - 粘贴, Ctrl+Z - 撤销"}
                    ]
                }
        else:
            # 如果没有知识库检索器，返回模拟结果
            return {
                "success": True,
                "skill": "kb_query",
                "query": query,
                "results": [
                    {"title": "AutoCAD基本命令", "content": "LINE - 绘制直线, CIRCLE - 绘制圆, RECTANG - 绘制矩形"},
                    {"title": "AutoCAD快捷键", "content": "Ctrl+C - 复制, Ctrl+V - 粘贴, Ctrl+Z - 撤销"}
                ],
                "message": "使用模拟知识库结果"
            }
    
    def _execute_file_search(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """执行文件搜索技能
        
        Args:
            params: 搜索参数
            
        Returns:
            执行结果
        """
        search_term = params.get("search_term", "")
        search_path = params.get("search_path", ".")
        
        # 实现实际的文件搜索功能
        try:
            results = []
            # 确保搜索路径存在
            if os.path.exists(search_path):
                # 遍历目录
                for root, dirs, files in os.walk(search_path):
                    # 过滤文件
                    for file in files:
                        if fnmatch.fnmatch(file, f"*{search_term}*"):
                            file_path = os.path.join(root, file)
                            try:
                                # 获取文件大小
                                file_size = os.path.getsize(file_path)
                                # 格式化文件大小
                                if file_size < 1024:
                                    size_str = f"{file_size} B"
                                elif file_size < 1024 * 1024:
                                    size_str = f"{file_size / 1024:.2f} KB"
                                else:
                                    size_str = f"{file_size / (1024 * 1024):.2f} MB"
                                results.append({
                                    "path": os.path.relpath(file_path, search_path),
                                    "size": size_str
                                })
                            except Exception:
                                # 忽略无法访问的文件
                                pass
                
                return {
                    "success": True,
                    "skill": "file_search",
                    "search_term": search_term,
                    "search_path": search_path,
                    "results": results[:20],  # 限制返回结果数量
                    "message": f"文件搜索完成，找到 {len(results)} 个文件"
                }
            else:
                return {
                    "success": False,
                    "skill": "file_search",
                    "search_term": search_term,
                    "search_path": search_path,
                    "message": "搜索路径不存在"
                }
        except Exception as e:
            return {
                "success": False,
                "skill": "file_search",
                "search_term": search_term,
                "search_path": search_path,
                "message": f"文件搜索失败: {str(e)}"
            }
    
    def _execute_erp_query(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """执行ERP查询技能
        
        Args:
            params: 查询参数
            
        Returns:
            执行结果
        """
        query_type = params.get("query_type", "")
        query_params = params.get("query_params", {})
        
        # 模拟ERP查询功能
        try:
            # 根据查询类型返回不同的模拟结果
            if query_type == "inventory":
                category = query_params.get("category", "")
                if category == "software":
                    results = [
                        {"item": "A-123", "description": "AutoCAD许可证", "quantity": 5},
                        {"item": "A-124", "description": "Revit许可证", "quantity": 3},
                        {"item": "A-125", "description": "Civil 3D许可证", "quantity": 2}
                    ]
                elif category == "hardware":
                    results = [
                        {"item": "B-456", "description": "绘图板", "quantity": 10},
                        {"item": "B-457", "description": "鼠标", "quantity": 20},
                        {"item": "B-458", "description": "键盘", "quantity": 15}
                    ]
                else:
                    results = [
                        {"item": "A-123", "description": "AutoCAD许可证", "quantity": 5},
                        {"item": "B-456", "description": "绘图板", "quantity": 10}
                    ]
            elif query_type == "order":
                order_id = query_params.get("order_id", "")
                results = [
                    {"order_id": order_id, "status": "已完成", "items": 3, "total": 15000.00},
                    {"order_id": order_id + "-1", "status": "处理中", "items": 2, "total": 8000.00}
                ]
            else:
                results = [
                    {"item": "A-123", "description": "AutoCAD许可证", "quantity": 5},
                    {"item": "B-456", "description": "绘图板", "quantity": 10}
                ]
            
            return {
                "success": True,
                "skill": "erp_query",
                "query_type": query_type,
                "results": results,
                "message": "ERP查询完成"
            }
        except Exception as e:
            return {
                "success": False,
                "skill": "erp_query",
                "query_type": query_type,
                "message": f"ERP查询失败: {str(e)}"
            }
    
    def list_skills(self) -> list:
        """列出所有可用技能
        
        Returns:
            技能名称列表
        """
        return list(self.skills.keys())
    
    def get_skill_info(self, skill_name: str) -> Optional[Dict[str, Any]]:
        """获取技能详细信息
        
        Args:
            skill_name: 技能名称
            
        Returns:
            技能详细信息
        """
        skill = self.get_skill(skill_name)
        if not skill:
            return None
        
        return {
            "name": skill.get("name"),
            "description": skill.get("description"),
            "type": skill.get("type"),
            "parameters": skill.get("parameters"),
            "enabled": skill.get("enabled", True)
        }
