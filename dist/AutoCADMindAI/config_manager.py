"""
配置管理模块
处理应用程序配置的读取和保存
"""

import configparser
import os


class ConfigManager:
    """配置管理器"""
    
    def __init__(self, config_file: str = "config.ini"):
        self.config_file = config_file
        self.config = configparser.ConfigParser()
        self.load_config()
    
    def load_config(self) -> bool:
        """加载配置文件"""
        try:
            if os.path.exists(self.config_file):
                self.config.read(self.config_file, encoding='utf-8')
                return True
            else:
                self.create_default_config()
                return True
        except Exception as e:
            print(f"加载配置失败: {e}")
            return False
    
    def create_default_config(self):
        """创建默认配置"""
        self.config['Connection'] = {
            'timeout': '10',
            'auto_connect': 'true'
        }
        self.config['UI'] = {
            'window_width': '1000',
            'window_height': '700'
        }
        self.save_config()
    
    def save_config(self) -> bool:
        """保存配置到文件"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                self.config.write(f)
            return True
        except Exception as e:
            print(f"保存配置失败: {e}")
            return False
    
    def get(self, section: str, key: str, default: str = None) -> str:
        """获取配置值"""
        try:
            return self.config.get(section, key)
        except:
            return default
    
    def get_int(self, section: str, key: str, default: int = 0) -> int:
        """获取整型配置值"""
        try:
            return self.config.getint(section, key)
        except:
            return default
    
    def get_bool(self, section: str, key: str, default: bool = False) -> bool:
        """获取布尔型配置值"""
        try:
            return self.config.getboolean(section, key)
        except:
            return default
    
    def get_window_size(self) -> tuple:
        """获取窗口大小"""
        width = self.get_int('UI', 'window_width', 1000)
        height = self.get_int('UI', 'window_height', 700)
        return width, height
    
    def get_connection_timeout(self) -> int:
        """获取连接超时时间"""
        return self.get_int('Connection', 'timeout', 10)
