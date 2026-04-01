#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""提示词管理器：管理性格文件和提示词生成"""

import os
import json
import sys
import inspect
import importlib.util
from typing import Dict, Any, Optional


class PromptManager:
    def __init__(self, personalities_dir=None):
        """初始化提示词管理器
        
        Args:
            personalities_dir: 性格文件目录路径（默认为程序所在目录的 personalities 文件夹）
        """
        if personalities_dir is None:
            # 使用多种方法尝试获取程序的实际路径
            personalities_dir = self._get_personalities_dir()
        
        self.personalities_dir = personalities_dir
        self.personalities = {}
        self.current_personality = None
        self.load_personalities()
    
    def _get_personalities_dir(self) -> str:
        """获取性格文件目录的绝对路径
        
        尝试多种方法来确定程序的实际位置，确保在 DLL 环境下也能正确找到路径
        """
        print(f"[DEBUG] 当前 Python 版本: {sys.version}")
        print(f"[DEBUG] 当前系统: {sys.platform}")
        print(f"[DEBUG] sys.executable: {sys.executable}")
        print(f"[DEBUG] sys.argv[0]: {sys.argv[0] if sys.argv else 'N/A'}")
        print(f"[DEBUG] os.getcwd(): {os.getcwd()}")
        
        # 方法 0: 检查是否在 frozen 环境（如 PyInstaller 打包）
        try:
            if getattr(sys, 'frozen', False):
                # 对于打包环境
                base_dir = os.path.dirname(sys.executable)
                personalities_dir = os.path.join(base_dir, "personalities")
                if os.path.exists(personalities_dir):
                    print(f"[DEBUG] 方法0 (frozen): 找到性格文件目录: {personalities_dir}")
                    return personalities_dir
        except Exception as e:
            print(f"[DEBUG] 方法0失败: {e}")
        
        # 方法 1: 使用 __file__ 获取当前模块路径
        try:
            current_file = os.path.abspath(__file__)
            print(f"[DEBUG] 当前模块文件: {current_file}")
            base_dir = os.path.dirname(os.path.dirname(current_file))
            personalities_dir = os.path.join(base_dir, "personalities")
            if os.path.exists(personalities_dir):
                print(f"[DEBUG] 方法1: 找到性格文件目录: {personalities_dir}")
                return personalities_dir
        except Exception as e:
            print(f"[DEBUG] 方法1失败: {e}")
        
        # 方法 2: 使用 inspect 模块获取调用者路径
        try:
            # 获取调用栈
            stack = inspect.stack()
            print(f"[DEBUG] 调用栈深度: {len(stack)}")
            if stack:
                # 找到主模块或第一个非本模块的调用者
                for i, frame in enumerate(stack):
                    frame_file = frame.filename
                    print(f"[DEBUG] 调用栈 {i}: {frame_file}")
                    if frame_file and not frame_file.endswith('prompt_manager.py'):
                        base_dir = os.path.dirname(os.path.abspath(frame_file))
                        print(f"[DEBUG] 找到调用者目录: {base_dir}")
                        # 向上查找项目根目录
                        while base_dir and not os.path.exists(os.path.join(base_dir, 'main_ai_cad.py')):
                            parent_dir = os.path.dirname(base_dir)
                            if parent_dir == base_dir:
                                break
                            base_dir = parent_dir
                        personalities_dir = os.path.join(base_dir, "personalities")
                        if os.path.exists(personalities_dir):
                            print(f"[DEBUG] 方法2: 找到性格文件目录: {personalities_dir}")
                            return personalities_dir
        except Exception as e:
            print(f"[DEBUG] 方法2失败: {e}")
        
        # 方法 3: 使用 sys.executable 所在目录
        try:
            exe_dir = os.path.dirname(os.path.abspath(sys.executable))
            print(f"[DEBUG] sys.executable 目录: {exe_dir}")
            # 尝试不同的相对路径
            possible_paths = [
                os.path.join(exe_dir, "personalities"),
                os.path.join(exe_dir, "..", "personalities"),
                os.path.join(exe_dir, "..", "..", "personalities"),
                os.path.join(exe_dir, "..", "AutoCADMindAI", "personalities"),
                os.path.join(exe_dir, "AutoCADMindAI", "personalities")
            ]
            for path in possible_paths:
                full_path = os.path.abspath(path)
                print(f"[DEBUG] 尝试路径: {full_path}")
                if os.path.exists(full_path):
                    print(f"[DEBUG] 方法3: 找到性格文件目录: {full_path}")
                    return full_path
        except Exception as e:
            print(f"[DEBUG] 方法3失败: {e}")
        
        # 方法 4: 使用当前工作目录
        try:
            cwd = os.getcwd()
            print(f"[DEBUG] 当前工作目录: {cwd}")
            # 尝试当前目录及其父目录
            possible_paths = [
                os.path.join(cwd, "personalities"),
                os.path.join(cwd, "..", "personalities"),
                os.path.join(cwd, "..", "..", "personalities")
            ]
            for path in possible_paths:
                full_path = os.path.abspath(path)
                print(f"[DEBUG] 尝试路径: {full_path}")
                if os.path.exists(full_path):
                    print(f"[DEBUG] 方法4: 找到性格文件目录: {full_path}")
                    return full_path
        except Exception as e:
            print(f"[DEBUG] 方法4失败: {e}")
        
        # 方法 5: 检查 Python 模块搜索路径
        try:
            print(f"[DEBUG] sys.path: {sys.path}")
            for path in sys.path:
                if path and os.path.isdir(path):
                    # 检查该路径及其父目录
                    possible_paths = [
                        os.path.join(path, "personalities"),
                        os.path.join(os.path.dirname(path), "personalities")
                    ]
                    for p in possible_paths:
                        full_path = os.path.abspath(p)
                        print(f"[DEBUG] 尝试 sys.path 路径: {full_path}")
                        if os.path.exists(full_path):
                            print(f"[DEBUG] 方法5: 找到性格文件目录: {full_path}")
                            return full_path
        except Exception as e:
            print(f"[DEBUG] 方法5失败: {e}")
        
        # 兜底: 返回相对路径
        print("[DEBUG] 所有方法都失败，使用相对路径 'personalities'")
        return "personalities"
    
    def load_personalities(self):
        """加载所有性格文件"""
        print(f"[DEBUG] 尝试加载性格文件目录: {self.personalities_dir}")
        print(f"[DEBUG] 目录是否存在: {os.path.exists(self.personalities_dir)}")
        
        if not os.path.exists(self.personalities_dir):
            print(f"[警告] 性格文件目录不存在: {self.personalities_dir}")
            # 尝试创建目录（如果不存在）
            try:
                os.makedirs(self.personalities_dir, exist_ok=True)
                print(f"[DEBUG] 已创建性格文件目录: {self.personalities_dir}")
            except Exception as e:
                print(f"[错误] 创建性格文件目录失败: {e}")
            return
        
        # 检查目录内容
        try:
            files = os.listdir(self.personalities_dir)
            print(f"[DEBUG] 目录内容: {files}")
        except Exception as e:
            print(f"[错误] 读取目录内容失败: {e}")
            return
        
        loaded_count = 0
        for filename in os.listdir(self.personalities_dir):
            if filename.endswith('.json'):
                personality_file = os.path.join(self.personalities_dir, filename)
                try:
                    with open(personality_file, 'r', encoding='utf-8') as f:
                        personality_data = json.load(f)
                    # 使用文件名（不含扩展名）作为性格ID
                    personality_id = os.path.splitext(filename)[0]
                    self.personalities[personality_id] = personality_data
                    loaded_count += 1
                    print(f"[DEBUG] 成功加载性格: {personality_id}")
                except Exception as e:
                    print(f"[错误] 加载性格文件 {filename} 失败: {e}")
        
        print(f"[DEBUG] 总共加载了 {loaded_count} 个性格文件")
        print(f"[DEBUG] 加载的性格: {list(self.personalities.keys())}")
    
    def set_personality(self, personality_id: str) -> bool:
        """设置当前性格
        
        Args:
            personality_id: 性格ID
            
        Returns:
            是否设置成功
        """
        if personality_id in self.personalities:
            self.current_personality = personality_id
            return True
        return False
    
    def get_prompt(self, skill_name: str, context: Dict[str, Any] = None) -> str:
        """生成特定技能的提示词
        
        Args:
            skill_name: 技能名称
            context: 上下文信息
            
        Returns:
            生成的提示词
        """
        # 获取当前性格
        personality_data = self.personalities.get(self.current_personality)
        if not personality_data:
            # 如果没有设置性格，使用默认值
            personality_data = {
                "personality": "你是一个专业的AutoCAD助手",
                "custom_rules": []
            }
        
        # 构建基础提示词
        base_prompt = personality_data.get("personality", "")
        
        # 添加自定义规则
        custom_rules = personality_data.get("custom_rules", [])
        if custom_rules:
            base_prompt += "\n\n规则：\n"
            for rule in custom_rules:
                base_prompt += f"- {rule}\n"
        
        # 添加技能特定的提示词
        if context and "skill_prompt" in context:
            base_prompt += "\n\n" + context["skill_prompt"]
        
        # 添加用户输入
        if context and "user_input" in context:
            base_prompt += f"\n\n用户输入: {context['user_input']}"
        
        return base_prompt
    
    def list_personalities(self) -> Dict[str, Dict[str, Any]]:
        """列出所有可用性格
        
        Returns:
            性格ID到性格数据的映射
        """
        return self.personalities
    
    def get_personality_info(self, personality_id: str) -> Optional[Dict[str, Any]]:
        """获取性格详细信息
        
        Args:
            personality_id: 性格ID
            
        Returns:
            性格详细信息
        """
        return self.personalities.get(personality_id)
    
    def get_current_personality(self) -> Optional[Dict[str, Any]]:
        """获取当前性格
        
        Returns:
            当前性格数据
        """
        if self.current_personality:
            return self.personalities.get(self.current_personality)
        return None
