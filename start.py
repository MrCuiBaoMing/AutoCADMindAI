#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI CAD 智能启动脚本
自动检测依赖，使用国内镜像源安装，然后启动程序
"""

import sys
import os
import subprocess
import importlib.util
import time

# 解决 Windows 控制台默认 GBK 导致的 UnicodeEncodeError
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

def check_module(module_name):
    """检查模块是否已安装"""
    return importlib.util.find_spec(module_name) is not None

def install_package(package_name, mirror=True):
    """使用国内镜像源安装包"""
    mirrors = [
        "https://pypi.tuna.tsinghua.edu.cn/simple",
        "https://pypi.douban.com/simple",
        "https://pypi.mirrors.ustc.edu.cn/simple",
        "https://pypi.huaweicloud.com/simple"
    ]
    
    for mirror_url in mirrors:
        try:
            print(f"尝试使用镜像源安装: {mirror_url}")
            cmd = [
                sys.executable, "-m", "pip", "install",
                "-i", mirror_url,
                package_name
            ]
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
            print(f"[OK] {package_name} 安装成功!")
            return True
        except subprocess.CalledProcessError as e:
            print(f"[ERR] 安装失败: {e.stderr[:200]}")
            continue
    
    print(f"尝试使用官方源安装...")
    try:
        cmd = [sys.executable, "-m", "pip", "install", package_name]
        subprocess.run(cmd, check=True)
        print(f"[OK] {package_name} 安装成功!")
        return True
    except subprocess.CalledProcessError as e:
        print(f"[ERR] 所有源都失败了: {e}")
        return False

def main():
    print("=" * 50)
    print("  AI CAD - AutoCAD智能助手 启动程序")
    print("=" * 50)
    print()
    
    # 需要检查的模块列表
    required_modules = [
        ("PyQt6", "PyQt6>=6.4.0"),
        ("win32com", "pywin32>=305"),
        ("requests", "requests>=2.28.0"),
        ("pyodbc", "pyodbc>=5.1.0")
    ]
    
    need_install = []
    
    print("正在检查依赖...")
    for module_name, package_name in required_modules:
        if check_module(module_name):
            print(f"[OK] {module_name} 已安装")
        else:
            print(f"[MISS] {module_name} 未安装")
            need_install.append(package_name)
    
    if need_install:
        print()
        print("需要安装以下依赖:")
        for pkg in need_install:
            print(f"  - {pkg}")
        print()
        print("开始安装...")
        print()
        
        for pkg in need_install:
            success = install_package(pkg)
            if not success:
                print(f"无法安装 {pkg}，程序将退出")
                sys.exit(2)
            print()
    else:
        print("[OK] 所有依赖已就绪!")
        print()
    
    # Windows 平台额外检查：ODBC Driver 是否可用（pyodbc 仅是 Python 包）
    if os.name == "nt":
        try:
            import pyodbc  # noqa
            drivers = [d.lower() for d in pyodbc.drivers()]
            has_sql_driver = any("sql server" in d for d in drivers)
            if has_sql_driver:
                print("[OK] 已检测到 SQL Server ODBC Driver")
            else:
                print("[WARN] 未检测到 SQL Server ODBC Driver，数据库功能可能不可用")
                print("      建议安装: ODBC Driver 17/18 for SQL Server")
        except Exception as e:
            print(f"[WARN] 无法检测 ODBC Driver: {e}")

    print("正在启动 AI CAD...")
    print("=" * 50)
    print()
    
    time.sleep(1)
    
    # 启动主程序
    try:
        subprocess.run([sys.executable, "main_ai_cad.py"])
    except KeyboardInterrupt:
        print()
        print("程序已退出")
    except Exception as e:
        print(f"启动失败: {e}")
        sys.exit(3)

if __name__ == "__main__":
    main()

