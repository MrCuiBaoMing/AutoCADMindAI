#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""提示词管理器：管理性格文件和提示词生成"""

import os
import json
from typing import Dict, Any, Optional


class PromptManager:
    def __init__(self, personalities_dir="personalities"):
        """初始化提示词管理器
        
        Args:
            personalities_dir: 性格文件目录路径
        """
        self.personalities_dir = personalities_dir
        self.personalities = {}
        self.current_personality = None
        self.load_personalities()
    
    def load_personalities(self):
        """加载所有性格文件"""
        if not os.path.exists(self.personalities_dir):
            return
        
        for filename in os.listdir(self.personalities_dir):
            if filename.endswith('.json'):
                personality_file = os.path.join(self.personalities_dir, filename)
                try:
                    with open(personality_file, 'r', encoding='utf-8') as f:
                        personality_data = json.load(f)
                    # 使用文件名（不含扩展名）作为性格ID
                    personality_id = os.path.splitext(filename)[0]
                    self.personalities[personality_id] = personality_data
                except Exception as e:
                    print(f"加载性格文件 {filename} 失败: {e}")
    
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
