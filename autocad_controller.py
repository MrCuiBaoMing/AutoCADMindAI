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


def _format_com_error(e: Exception) -> str:
    """格式化 COM 异常信息，避免 <unknown>"""
    msg = str(e).strip()
    if msg and msg != "<unknown>":
        return msg
    try:
        if hasattr(e, "args") and e.args:
            return repr(e.args)
        return repr(e)
    except Exception:
        return "COM调用异常"


class AutoCADController:
    """AutoCAD控制器类"""
    
    def __init__(self):
        self.acad_app = None
        self.acad_doc = None
        self.is_connected = False
        self.connection_timeout = 10

    def ensure_document(self) -> bool:
        """重新获取当前活动文档，避免引用失效（切换文档、停止后再次会话等）"""
        if not self.is_connected or not self.acad_app:
            return False
        try:
            self.acad_doc = self.acad_app.ActiveDocument
            return self.acad_doc is not None
        except Exception as e:
            logger.warning(f"重新获取活动文档失败: {_format_com_error(e)}")
            self.acad_doc = None
            return False

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
        """发送命令到AutoCAD。delay=0 时不等待，便于队列模式下主线程不阻塞、停止可点。"""
        if not self.is_connected or not self.acad_app:
            logger.error("未连接到AutoCAD")
            return False

        # 每次发送前刷新活动文档，避免“停止后再次会话”或切换文档后引用失效
        if not self.ensure_document():
            logger.error("无法获取活动文档，请确认 AutoCAD 已打开图纸")
            return False

        if not command.endswith('\n'):
            command = command + '\n'

        def do_send():
            try:
                self.acad_doc.SendCommand(command)
                return True
            except Exception as e1:
                logger.warning(f"SendCommand失败: {_format_com_error(e1)}，尝试 SendStringToExecute")
                try:
                    self.acad_doc.SendStringToExecute(command, True, False, False)
                    return True
                except Exception as e2:
                    logger.error(f"SendStringToExecute也失败: {_format_com_error(e2)}")
                    raise e2

        try:
            logger.info(f"发送命令: {command}")
            do_send()
            if delay > 0:
                time.sleep(delay)
            return True
        except Exception as e:
            logger.error(f"发送命令失败: {_format_com_error(e)}")
            # 失败时尝试刷新文档并重试一次
            try:
                if self.ensure_document():
                    logger.info("已刷新活动文档，正在重试发送命令...")
                    do_send()
                    if delay > 0:
                        time.sleep(delay)
                    return True
            except Exception as retry_e:
                logger.error(f"重试发送命令失败: {_format_com_error(retry_e)}")
            return False
    
    def send_commands(self, commands: List[str], delay: float = 0.5) -> bool:
        """批量发送命令"""
        success = True
        for cmd in commands:
            if not self.send_command(cmd, delay):
                success = False
        return success
    
    def cancel_command(self):
        """取消当前命令（通过 COM 发送 ESC）。
        使用与 SendCommand 相同的接口，若本机 AutoCAD 不支持该 COM 接口（如部分 LMS Tech 版本），
        取消失败属正常，仅记入 DEBUG 日志，不刷 WARNING。"""
        if not self.is_connected or not self.acad_app:
            return

        if not self.ensure_document():
            logger.debug("取消命令时无法获取活动文档，已跳过")
            return

        try:
            self.acad_doc.SendCommand(chr(27) + '\n')
            self.acad_doc.SendCommand('\n')
            logger.info("已发送取消命令 (ESC)")
        except Exception as e:
            # 与发送普通命令同一 COM 路径，若本机不支持则此处也会失败，仅记录 DEBUG 避免刷屏
            logger.debug(f"取消命令失败: {_format_com_error(e)}")
