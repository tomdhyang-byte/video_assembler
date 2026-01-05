"""
平台相關工具函數
統一管理跨平台差異（Windows/macOS）
"""

import os
import platform
import shutil
from pathlib import Path


def get_platform() -> str:
    """
    取得當前作業系統名稱
    Returns: 'windows', 'macos', 'linux', or 'unknown'
    """
    system = platform.system().lower()
    if system == "darwin":
        return "macos"
    elif system == "windows":
        return "windows"
    elif system == "linux":
        return "linux"
    return "unknown"


def escape_ffmpeg_filter_path(path: Path) -> str:
    r"""
    轉義 FFmpeg 濾鏡使用的檔案路徑
    
    不同平台的轉義規則：
    Windows: 
        - 反斜線 \ 需要替換為正斜線 /
        - 冒號 : 需要轉義為 \\:
        - 空格 需要轉義為 \\ 
        
    macOS/Linux:
        - 使用 POSIX 路徑
        - 冒號 : 需要轉義為 \\:
    """
    os_name = get_platform()
    
    if os_name == "windows":
        # Windows 處理邏輯
        # 1. 將反斜線轉換為正斜線 (因為 FFmpeg 濾鏡內部偏好正斜線)
        path_str = str(path).replace("\\", "/")
        
        # 2. 轉義特殊字元：冒號、空格
        # "C:/Path/To File.ass" -> "C\:/Path/To\ File.ass"
        escaped = path_str.replace(":", "\\:").replace(" ", "\\ ")
        return escaped
    else:
        # macOS/Linux 處理邏輯
        # Posix 路徑本來就是正斜線，只需轉義冒號
        # "/Path/To/File.ass" -> "/Path/To/File.ass" (如果含冒號則轉義)
        return path.as_posix().replace(":", "\\:")


def get_default_font_path() -> str:
    """
    取得平台預設的中文字體路徑
    
    優先順序：
    1. macOS: PingFang TC (蘋方)
    2. Windows: Microsoft JhengHei (微軟正黑體)
    3. Linux: Noto Sans CJK
    """
    os_name = get_platform()
    
    if os_name == "macos":
        font = Path("/System/Library/Fonts/PingFang.ttc")
        if font.exists():
            return str(font)
            
    elif os_name == "windows":
        # 常見 Windows 字體路徑
        fonts = [
            Path("C:/Windows/Fonts/msjh.ttc"),      # 微軟正黑體
            Path("C:/Windows/Fonts/msjh.ttf"),
            Path("C:/Windows/Fonts/simhei.ttf"),    # 黑體
        ]
        for f in fonts:
            if f.exists():
                return str(f)
                
    elif os_name == "linux":
        # 常見 Linux 字體
        fonts = [
            Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
            Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
            Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
        ]
        for f in fonts:
            if f.exists():
                return str(f)
    
    # 如果找不到任何預設字體，回傳 None (讓 Config 層決定是否報錯或使用 fallback)
    return None


def validate_ffmpeg_installed() -> bool:
    """驗證 FFmpeg 是否已安裝且在 PATH 中"""
    return shutil.which("ffmpeg") is not None
