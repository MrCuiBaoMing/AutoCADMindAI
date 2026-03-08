"""
AutoCAD控制核心模块
使用pywin32和COM接口与AutoCAD进行通信
"""

import win32com.client
import pythoncom
import time
from typing import Optional, List
import logging

try:
    import win32gui
    import win32api
    import win32con
except Exception:
    win32gui = None
    win32api = None
    win32con = None

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
    
    def _activate_acad_window(self) -> bool:
        """尝试激活 AutoCAD 窗口。仅在需要键盘兜底时使用。"""
        if not self.acad_app:
            return False
        if win32gui is None:
            return False
        try:
            hwnd = int(self.acad_app.HWND)
            if hwnd:
                try:
                    win32gui.ShowWindow(hwnd, 9)  # SW_RESTORE
                except Exception:
                    pass
                win32gui.SetForegroundWindow(hwnd)
                time.sleep(0.05)
                return True
        except Exception as e:
            logger.debug(f"激活AutoCAD窗口失败: {_format_com_error(e)}")
        return False

    def _send_keyboard_cancel_to_acad(self) -> bool:
        """键盘兜底：向 AutoCAD 窗口发送 Ctrl+C / ESC（不依赖本工具窗口焦点）。"""
        if win32api is None or win32con is None:
            return False
        if not self._activate_acad_window():
            return False

        try:
            # Ctrl down
            win32api.keybd_event(win32con.VK_CONTROL, 0, 0, 0)
            # C down/up
            win32api.keybd_event(ord('C'), 0, 0, 0)
            win32api.keybd_event(ord('C'), 0, win32con.KEYEVENTF_KEYUP, 0)
            # C 再一次
            win32api.keybd_event(ord('C'), 0, 0, 0)
            win32api.keybd_event(ord('C'), 0, win32con.KEYEVENTF_KEYUP, 0)
            # Ctrl up
            win32api.keybd_event(win32con.VK_CONTROL, 0, win32con.KEYEVENTF_KEYUP, 0)
            time.sleep(0.03)

            # ESC down/up
            win32api.keybd_event(win32con.VK_ESCAPE, 0, 0, 0)
            win32api.keybd_event(win32con.VK_ESCAPE, 0, win32con.KEYEVENTF_KEYUP, 0)
            time.sleep(0.03)

            logger.info("已发送键盘取消命令（Ctrl+C, Ctrl+C, ESC）")
            return True
        except Exception as e:
            logger.debug(f"发送键盘取消失败: {_format_com_error(e)}")
            return False

    def cancel_command(self) -> bool:
        """取消当前命令（COM 方式，不依赖窗口焦点）。返回是否发送成功。"""
        if not self.is_connected or not self.acad_app:
            return False

        try:
            doc = self.acad_app.ActiveDocument
        except Exception as e:
            logger.debug(f"取消命令时获取活动文档失败: {_format_com_error(e)}")
            return False

        cancel_sequences = [
            "\x03\x03\n",      # Ctrl+C Ctrl+C（硬取消）
            "\x03\n",           # 再补一次 Ctrl+C
            chr(27) + "\n",     # ESC
            "\n",               # 回车，清理残留提示
        ]

        sent_any = False
        for seq in cancel_sequences:
            try:
                doc.SendCommand(seq)
                sent_any = True
                time.sleep(0.06)
            except Exception as e:
                logger.debug(f"发送取消序列失败: {_format_com_error(e)}")

        if sent_any:
            logger.info("已发送取消命令（COM: ^C^C/ESC）")
        return sent_any

    def force_cancel_command(self, rounds: int = 8, interval: float = 0.08) -> bool:
        """强制取消：多轮 COM 取消；必要时使用键盘事件兜底。"""
        success = False

        # 第一阶段：COM 多轮取消
        for _ in range(max(1, rounds)):
            success = self.cancel_command() or success
            time.sleep(interval)

        # 第二阶段：激活 AutoCAD 并再次 COM 取消
        if self._activate_acad_window():
            for _ in range(3):
                success = self.cancel_command() or success
                time.sleep(interval)

        # 第三阶段：键盘级兜底（Ctrl+C/Ctrl+C/ESC），用于某些 COM 取消无效场景
        kb_success = False
        for _ in range(3):
            kb_success = self._send_keyboard_cancel_to_acad() or kb_success
            time.sleep(interval)

        return success or kb_success
