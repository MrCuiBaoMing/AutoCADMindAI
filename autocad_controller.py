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
        if not self.acad_app:
            logger.warning("ensure_document: acad_app 为空")
            return False
        try:
            # 每次都重新获取活动文档，确保引用有效
            self.acad_doc = self.acad_app.ActiveDocument
            if self.acad_doc is None:
                logger.warning("ensure_document: ActiveDocument 返回 None，请先打开 DWG 图纸")
                return False
            # 额外验证：尝试访问文档属性
            _ = self.acad_doc.Name
            return True
        except Exception as e:
            logger.warning(f"ensure_document 失败: {_format_com_error(e)}")
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

    # ==================== COM API 直接绘图方法 ====================
    # 绕过命令行，直接使用 AutoCAD COM API 创建图形对象
    # 优势：完全自动化、无需用户干预、执行速度快、支持撤销

    def _make_point(self, coords: tuple) -> win32com.client.VARIANT:
        """创建 AutoCAD 3D 点坐标（COM VARIANT 数组）"""
        if len(coords) >= 3:
            x, y, z = float(coords[0]), float(coords[1]), float(coords[2])
        elif len(coords) == 2:
            x, y, z = float(coords[0]), float(coords[1]), 0.0
        else:
            x, y, z = 0.0, 0.0, 0.0
        return win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, [x, y, z])

    def _make_point_2d(self, coords: list) -> win32com.client.VARIANT:
        """创建 2D 点坐标数组（用于多段线等）"""
        flat = []
        for pt in coords:
            flat.append(float(pt[0]))
            flat.append(float(pt[1]))
        return win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, flat)

    def draw_line(self, start: tuple, end: tuple, layer: str = None) -> dict:
        """
        绘制直线
        
        Args:
            start: 起点 (x, y) 或 (x, y, z)
            end: 终点 (x, y) 或 (x, y, z)
            layer: 图层名（可选）
        
        Returns:
            {"success": bool, "message": str, "entity": object}
        """
        if not self.ensure_document():
            return {"success": False, "message": "未连接到AutoCAD或无活动文档"}
        
        try:
            start_point = self._make_point(start)
            end_point = self._make_point(end)
            
            line = self.acad_doc.ModelSpace.AddLine(start_point, end_point)
            
            if layer:
                try:
                    line.Layer = layer
                except Exception:
                    pass  # 图层不存在时忽略
            
            logger.info(f"已绘制直线: {start} -> {end}")
            return {"success": True, "message": f"直线已绘制", "entity": line}
            
        except Exception as e:
            err = _format_com_error(e)
            logger.error(f"绘制直线失败: {err}")
            return {"success": False, "message": f"绘制直线失败: {err}"}

    def draw_circle(self, center: tuple, radius: float, layer: str = None) -> dict:
        """
        绘制圆
        
        Args:
            center: 圆心 (x, y) 或 (x, y, z)
            radius: 半径
            layer: 图层名（可选）
        
        Returns:
            {"success": bool, "message": str, "entity": object}
        """
        if not self.ensure_document():
            return {"success": False, "message": "未连接到AutoCAD或无活动文档"}
        
        try:
            center_point = self._make_point(center)
            circle = self.acad_doc.ModelSpace.AddCircle(center_point, float(radius))
            
            if layer:
                try:
                    circle.Layer = layer
                except Exception:
                    pass
            
            logger.info(f"已绘制圆: 圆心{center}, 半径{radius}")
            return {"success": True, "message": f"圆已绘制（半径={radius}）", "entity": circle}
            
        except Exception as e:
            err = _format_com_error(e)
            logger.error(f"绘制圆失败: {err}")
            return {"success": False, "message": f"绘制圆失败: {err}"}

    def draw_rectangle(self, corner1: tuple, corner2: tuple, layer: str = None) -> dict:
        """
        绘制矩形（闭合多段线）
        
        Args:
            corner1: 角点1 (x, y)
            corner2: 对角点2 (x, y)
            layer: 图层名（可选）
        
        Returns:
            {"success": bool, "message": str, "entity": object}
        """
        if not self.ensure_document():
            return {"success": False, "message": "未连接到AutoCAD或无活动文档"}
        
        try:
            x1, y1 = float(corner1[0]), float(corner1[1])
            x2, y2 = float(corner2[0]), float(corner2[1])
            
            # 四个顶点（闭合）
            points = self._make_point_2d([
                (x1, y1), (x2, y1), (x2, y2), (x1, y2)
            ])
            
            pline = self.acad_doc.ModelSpace.AddLightweightPolyline(points)
            pline.Closed = True
            
            if layer:
                try:
                    pline.Layer = layer
                except Exception:
                    pass
            
            logger.info(f"已绘制矩形: ({x1},{y1}) - ({x2},{y2})")
            return {"success": True, "message": f"矩形已绘制", "entity": pline}
            
        except Exception as e:
            err = _format_com_error(e)
            logger.error(f"绘制矩形失败: {err}")
            return {"success": False, "message": f"绘制矩形失败: {err}"}

    def draw_arc(self, center: tuple, radius: float, start_angle: float, end_angle: float, layer: str = None) -> dict:
        """
        绘制圆弧
        
        Args:
            center: 圆心 (x, y) 或 (x, y, z)
            radius: 半径
            start_angle: 起始角度（弧度）
            end_angle: 结束角度（弧度）
            layer: 图层名（可选）
        
        Returns:
            {"success": bool, "message": str, "entity": object}
        """
        if not self.ensure_document():
            return {"success": False, "message": "未连接到AutoCAD或无活动文档"}
        
        try:
            center_point = self._make_point(center)
            arc = self.acad_doc.ModelSpace.AddArc(
                center_point, 
                float(radius), 
                float(start_angle), 
                float(end_angle)
            )
            
            if layer:
                try:
                    arc.Layer = layer
                except Exception:
                    pass
            
            logger.info(f"已绘制圆弧: 圆心{center}, 半径{radius}")
            return {"success": True, "message": "圆弧已绘制", "entity": arc}
            
        except Exception as e:
            err = _format_com_error(e)
            logger.error(f"绘制圆弧失败: {err}")
            return {"success": False, "message": f"绘制圆弧失败: {err}"}

    def draw_text(self, text: str, position: tuple, height: float = 2.5, layer: str = None) -> dict:
        """
        添加单行文字
        
        Args:
            text: 文字内容
            position: 插入点 (x, y) 或 (x, y, z)
            height: 字高
            layer: 图层名（可选）
        
        Returns:
            {"success": bool, "message": str, "entity": object}
        """
        if not self.ensure_document():
            return {"success": False, "message": "未连接到AutoCAD或无活动文档"}
        
        try:
            insert_point = self._make_point(position)
            text_obj = self.acad_doc.ModelSpace.AddText(text, insert_point, float(height))
            
            if layer:
                try:
                    text_obj.Layer = layer
                except Exception:
                    pass
            
            logger.info(f"已添加文字: '{text}'")
            return {"success": True, "message": f"文字已添加", "entity": text_obj}
            
        except Exception as e:
            err = _format_com_error(e)
            logger.error(f"添加文字失败: {err}")
            return {"success": False, "message": f"添加文字失败: {err}"}

    def draw_polyline(self, points: list, closed: bool = False, layer: str = None) -> dict:
        """
        绘制多段线
        
        Args:
            points: 点列表 [(x1,y1), (x2,y2), ...]
            closed: 是否闭合
            layer: 图层名（可选）
        
        Returns:
            {"success": bool, "message": str, "entity": object}
        """
        if not self.ensure_document():
            return {"success": False, "message": "未连接到AutoCAD或无活动文档"}
        
        if len(points) < 2:
            return {"success": False, "message": "多段线至少需要2个点"}
        
        try:
            point_array = self._make_point_2d(points)
            pline = self.acad_doc.ModelSpace.AddLightweightPolyline(point_array)
            pline.Closed = closed
            
            if layer:
                try:
                    pline.Layer = layer
                except Exception:
                    pass
            
            logger.info(f"已绘制多段线: {len(points)}个点")
            return {"success": True, "message": f"多段线已绘制（{len(points)}个点）", "entity": pline}
            
        except Exception as e:
            err = _format_com_error(e)
            logger.error(f"绘制多段线失败: {err}")
            return {"success": False, "message": f"绘制多段线失败: {err}"}

    def draw_polygon(self, center: tuple, radius: float, sides: int, layer: str = None) -> dict:
        """
        绘制正多边形（通过命令行，因为 COM API 没有直接方法）
        
        Args:
            center: 中心点 (x, y)
            radius: 外接圆半径
            sides: 边数（3-1024）
            layer: 图层名（可选）
        
        Returns:
            {"success": bool, "message": str}
        """
        if not self.ensure_document():
            return {"success": False, "message": "未连接到AutoCAD或无活动文档"}
        
        if sides < 3 or sides > 1024:
            return {"success": False, "message": "边数必须在3-1024之间"}
        
        try:
            x, y = float(center[0]), float(center[1])
            # 使用 POLYGON 命令
            cmd = f"_POLYGON {sides} {x},{y} I {radius}\n"
            self.acad_doc.SendCommand(cmd)
            
            logger.info(f"已绘制正{sides}边形")
            return {"success": True, "message": f"正{sides}边形已绘制"}
            
        except Exception as e:
            err = _format_com_error(e)
            logger.error(f"绘制多边形失败: {err}")
            return {"success": False, "message": f"绘制多边形失败: {err}"}

    def set_layer(self, layer_name: str, create_if_not_exists: bool = True) -> dict:
        """
        设置当前图层
        
        Args:
            layer_name: 图层名
            create_if_not_exists: 不存在时是否创建
        
        Returns:
            {"success": bool, "message": str}
        """
        if not self.ensure_document():
            return {"success": False, "message": "未连接到AutoCAD或无活动文档"}
        
        try:
            layers = self.acad_doc.Layers
            
            # 检查图层是否存在
            layer = None
            try:
                layer = layers.Item(layer_name)
            except Exception:
                # 图层不存在
                if create_if_not_exists:
                    layer = layers.Add(layer_name)
                    logger.info(f"已创建图层: {layer_name}")
                else:
                    return {"success": False, "message": f"图层 '{layer_name}' 不存在"}
            
            if layer:
                self.acad_doc.ActiveLayer = layer
                logger.info(f"已设置当前图层: {layer_name}")
                return {"success": True, "message": f"当前图层已设置为 '{layer_name}'"}
            
        except Exception as e:
            err = _format_com_error(e)
            logger.error(f"设置图层失败: {err}")
            return {"success": False, "message": f"设置图层失败: {err}"}

    def zoom_extents(self) -> bool:
        """缩放到全部图形"""
        if not self.acad_app:
            return False
        try:
            self.acad_app.ZoomExtents()
            logger.info("已缩放到全部图形")
            return True
        except Exception as e:
            logger.warning(f"缩放失败: {_format_com_error(e)}")
            return False

    def zoom_center(self, center: tuple, magnification: float = 1.0) -> bool:
        """缩放到指定中心点"""
        if not self.acad_app:
            return False
        try:
            center_point = self._make_point(center)
            self.acad_app.ZoomCenter(center_point, float(magnification))
            return True
        except Exception as e:
            logger.warning(f"缩放失败: {_format_com_error(e)}")
            return False

    def get_entity_count(self) -> int:
        """获取模型空间中的实体数量"""
        if not self.ensure_document():
            return 0
        try:
            return self.acad_doc.ModelSpace.Count
        except Exception:
            return 0

    def delete_last_entity(self) -> dict:
        """删除最后一个绘制的实体"""
        if not self.ensure_document():
            return {"success": False, "message": "未连接到AutoCAD或无活动文档"}
        
        try:
            count = self.acad_doc.ModelSpace.Count
            if count > 0:
                last_entity = self.acad_doc.ModelSpace.Item(count - 1)
                last_entity.Delete()
                logger.info("已删除最后一个实体")
                return {"success": True, "message": "已删除最后一个实体"}
            else:
                return {"success": False, "message": "模型空间中没有实体"}
                
        except Exception as e:
            err = _format_com_error(e)
            logger.error(f"删除实体失败: {err}")
            return {"success": False, "message": f"删除失败: {err}"}

    def execute_drawing_commands(self, commands: list) -> dict:
        """
        批量执行绘图命令
        
        Args:
            commands: 绘图命令列表，格式如:
                [
                    {"type": "line", "start": [0, 0], "end": [100, 100]},
                    {"type": "circle", "center": [50, 50], "radius": 25},
                    {"type": "rectangle", "corner1": [0, 0], "corner2": [100, 50]}
                ]
        
        Returns:
            {"success": bool, "message": str, "results": list, "failed_count": int}
        """
        if not commands:
            return {"success": False, "message": "没有绘图命令", "results": [], "failed_count": 0}
        
        results = []
        failed_count = 0
        
        for cmd in commands:
            cmd_type = cmd.get("type", "").lower()
            result = {"type": cmd_type, "success": False}
            
            try:
                if cmd_type == "line":
                    result = self.draw_line(
                        cmd.get("start", (0, 0)),
                        cmd.get("end", (0, 0)),
                        cmd.get("layer")
                    )
                    result["type"] = "line"
                    
                elif cmd_type == "circle":
                    # 支持直径和半径两种参数
                    center = cmd.get("center", (0, 0))
                    radius = cmd.get("radius")
                    if radius is None:
                        diameter = cmd.get("diameter")
                        if diameter is not None:
                            radius = float(diameter) / 2
                        else:
                            radius = 10  # 默认半径
                    result = self.draw_circle(
                        center,
                        float(radius),
                        cmd.get("layer")
                    )
                    result["type"] = "circle"
                    
                elif cmd_type == "rectangle" or cmd_type == "rect":
                    result = self.draw_rectangle(
                        cmd.get("corner1", (0, 0)),
                        cmd.get("corner2", (100, 100)),
                        cmd.get("layer")
                    )
                    result["type"] = "rectangle"
                    
                elif cmd_type == "arc":
                    result = self.draw_arc(
                        cmd.get("center", (0, 0)),
                        cmd.get("radius", 10),
                        cmd.get("start_angle", 0),
                        cmd.get("end_angle", 3.14159),
                        cmd.get("layer")
                    )
                    result["type"] = "arc"
                    
                elif cmd_type == "text":
                    result = self.draw_text(
                        cmd.get("content", ""),
                        cmd.get("position", (0, 0)),
                        cmd.get("height", 2.5),
                        cmd.get("layer")
                    )
                    result["type"] = "text"
                    
                elif cmd_type == "polyline" or cmd_type == "pline":
                    result = self.draw_polyline(
                        cmd.get("points", []),
                        cmd.get("closed", False),
                        cmd.get("layer")
                    )
                    result["type"] = "polyline"
                    
                elif cmd_type == "polygon":
                    result = self.draw_polygon(
                        cmd.get("center", (0, 0)),
                        cmd.get("radius", 10),
                        cmd.get("sides", 6),
                        cmd.get("layer")
                    )
                    result["type"] = "polygon"
                    
                else:
                    result = {"success": False, "message": f"未知的绘图类型: {cmd_type}", "type": cmd_type}
                
            except Exception as e:
                result = {"success": False, "message": f"执行异常: {str(e)}", "type": cmd_type}
            
            if not result.get("success"):
                failed_count += 1
            results.append(result)
        
        success = failed_count == 0
        message = f"完成 {len(commands)} 个绘图命令，失败 {failed_count} 个"
        logger.info(message)
        
        return {
            "success": success,
            "message": message,
            "results": results,
            "failed_count": failed_count
        }
