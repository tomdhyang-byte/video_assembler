"""
共用設定檔 - 雙引擎架構（MoviePy / FFmpeg）共用參數
"""

from pathlib import Path


# ============================================================
# 影片規格
# ============================================================
class VideoConfig:
    WIDTH = 1920
    HEIGHT = 1080
    FPS = 24
    CODEC = "libx264"
    AUDIO_CODEC = "aac"
    PRESET = "medium"


# ============================================================
# 系統與效能設定
# ============================================================
class ProcessingConfig:
    # 平行處理最大執行緒數
    # 建議值: CPU 核心數 + 4 (IO bound)
    MAX_WORKERS = 8


# ============================================================
# 字幕設定
# ============================================================
class SubtitleConfig:
    FONT_SIZE = 96  # 調整 (64 → 128 → 96)
    STROKE_WIDTH = 6
    CENTER_Y = 1000  # 字幕視覺中心的 Y 座標
    FONT_PATH = "/System/Library/Fonts/PingFang.ttc"
    COLOR = "yellow"
    STROKE_COLOR = "black"
    # ASS 格式專用（FFmpeg 引擎）
    ASS_ALIGNMENT = 2  # 底部置中
    ASS_MARGIN_V = 80  # 垂直邊距（會被 CENTER_Y 覆蓋計算）


# ============================================================
# Avatar 設定
# ============================================================
class AvatarConfig:
    CROP_X = 200
    CROP_Y = 550
    CROP_SIZE = 650
    SCALE_RATIO = 0.12
    MARGIN_X = 30
    MARGIN_Y = 30


# ============================================================
# 檔案命名
# ============================================================
class FileNames:
    SUBTITLE_FILE = "full_subtitle.srt"
    AVATAR_FILE = "avatar_full.mp4"
    MERGED_AUDIO = "_merged_audio.mp3"
    ASS_SUBTITLE = "_subtitle.ass"  # FFmpeg 引擎產生的中間檔


# ============================================================
# 輸出設定
# ============================================================
class OutputConfig:
    # 輸出到桌面
    OUTPUT_DIR = Path.home() / "Desktop"


# ============================================================
# 忽略檔案
# ============================================================
IGNORE_FILES = {".DS_Store", "Thumbs.db", ".gitkeep", "desktop.ini"}
