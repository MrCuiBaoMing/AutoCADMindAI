"""
AutoCAD控制核心模块
使用pywin32和COM接口与AutoCAD进行通信
"""

import win32com.client
import pythoncom
import time
from typing import Optional, List
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class AutoCADController:
    """AutoCAD控制器类"""
    
    def __init__(self):
        self.acad_app = None
        self.acad_doc = None
        self.is_connected = False
        self.connection_timeout = 10
        
    def connect(self, timeout: int = 10) -> bool:
        """连接到AutoCAD实例"""
        try:
            logger.info("正在尝试连接到AutoCAD...")
            
            pythoncom.CoInitialize()
            
            try:
                self.acad_app = win32com.client.GetActiveObject("AutoCAD.Application")
                logger.info("成功连接到现有的AutoCAD实例")
            except Exception as e:
                logger.warning(f"未找到运行中的AutoCAD实例: {e}")
                logger.info("请先启动AutoCAD，然后点击'连接AutoCAD'按钮")
                pythoncom.CoUninitialize()
                return False
            
            try:
                self.acad_doc = self.acad_app.ActiveDocument
            except Exception as e:
                logger.warning(f"无法获取活动文档: {e}")
                self.acad_doc = None
            
            self.is_connected = True
            
            try:
                version = self.acad_app.Version
                logger.info(f"已连接到AutoCAD {version}")
            except Exception as e:
                logger.warning(f"无法获取版本信息: {e}")
            
            return True
            
        except Exception as e:
            logger.error(f"连接AutoCAD失败: {e}")
            self.is_connected = False
            return False
    
    def disconnect(self):
        """断开与AutoCAD的连接"""
        try:
            self.acad_doc = None
            self.acad_app = None
            self.is_connected = False
            logger.info("已断开与AutoCAD的连接")
            pythoncom.CoUninitialize()
        except Exception as e:
            logger.error(f"断开连接时出错: {e}")
    
    def send_command(self, command: str, delay: float = 0.5) -> bool:
        """发送命令到AutoCAD"""
        if not self.is_connected or not self.acad_doc:
            logger.error("未连接到AutoCAD")
            return False
        
        try:
            logger.info(f"发送命令: {command}")
            
            if not command.endswith('\n'):
                command = command + '\n'
            
            try:
                self.acad_doc.SendCommand(command)
            except Exception as e1:
                logger.warning(f"SendCommand失败，尝试SendStringToExecute: {e1}")
                try:
                    self.acad_doc.SendStringToExecute(command, True, False, False)
                except Exception as e2:
                    logger.error(f"SendStringToExecute也失败: {e2}")
                    raise e2
            
            time.sleep(delay)
            
            return True
            
        except Exception as e:
            logger.error(f"发送命令失败: {e}")
            return False
    
    def send_commands(self, commands: List[str], delay: float = 0.5) -> bool:
        """批量发送命令"""
        success = True
        for cmd in commands:
            if not self.send_command(cmd, delay):
                success = False
        return success
