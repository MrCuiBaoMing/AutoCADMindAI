#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试新功能：性格系统和技能系统"""

import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.skill_manager import SkillManager
from core.prompt_manager import PromptManager


def test_skill_manager():
    """测试技能管理器"""
    print("=== 测试技能管理器 ===")
    skill_manager = SkillManager()
    
    # 列出所有技能
    skills = skill_manager.list_skills()
    print(f"可用技能: {skills}")
    
    # 获取技能信息
    for skill_name in skills:
        skill_info = skill_manager.get_skill_info(skill_name)
        print(f"\n技能: {skill_name}")
        print(f"描述: {skill_info.get('description')}")
        print(f"类型: {skill_info.get('type')}")
        print(f"参数: {skill_info.get('parameters')}")
        print(f"启用状态: {skill_info.get('enabled')}")
    
    # 测试执行技能
    test_params = {"drawing_type": "circle", "dimensions": {"radius": 50}, "position": {"x": 0, "y": 0}}
    result = skill_manager.execute_skill("cad_drawing", test_params)
    print(f"\n执行技能结果: {result}")


def test_prompt_manager():
    """测试提示词管理器"""
    print("\n=== 测试提示词管理器 ===")
    prompt_manager = PromptManager()
    
    # 列出所有性格
    personalities = prompt_manager.list_personalities()
    print(f"可用性格: {list(personalities.keys())}")
    
    # 获取性格信息
    for personality_id, personality_data in personalities.items():
        print(f"\n性格: {personality_data.get('name')}")
        print(f"描述: {personality_data.get('description')}")
        print(f"问候语: {personality_data.get('greeting')}")
    
    # 测试设置性格
    prompt_manager.set_personality("professional")
    current_personality = prompt_manager.get_current_personality()
    print(f"\n当前性格: {current_personality.get('name')}")
    
    # 测试生成提示词
    context = {
        "skill_prompt": "你是一个专业的AutoCAD绘图专家，能够根据用户需求生成精确的绘图命令。",
        "user_input": "画一个半径50的圆"
    }
    prompt = prompt_manager.get_prompt("cad_drawing", context)
    print(f"\n生成的提示词:\n{prompt}")


if __name__ == "__main__":
    test_skill_manager()
    test_prompt_manager()
    print("\n=== 测试完成 ===")
