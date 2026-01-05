"""
Unit tests for platform_utils.py
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

# 加入專案根目錄到 path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from utils.platform_utils import escape_ffmpeg_filter_path, get_default_font_path

class TestPlatformUtils(unittest.TestCase):
    
    @patch('utils.platform_utils.get_platform')
    def test_escape_path_windows(self, mock_platform):
        """測試 Windows 路徑轉義"""
        mock_platform.return_value = 'windows'
        
        # 測試一般路徑
        input_path = Path("C:/Users/Test/file.ass")
        expected = "C\\:/Users/Test/file.ass"
        self.assertEqual(escape_ffmpeg_filter_path(input_path), expected)
        
        # 測試含空格
        input_path = Path("C:/Program Files/Movie/subtitle.ass")
        expected = "C\\:/Program\\ Files/Movie/subtitle.ass"
        self.assertEqual(escape_ffmpeg_filter_path(input_path), expected)
        
        # 測試反斜線 (Python Path 物件會標準化，但我們模擬字串處理)
        # 由於我們沒有在 Windows 環境，只能確保我們對一般路徑的轉義逻辑正確
        # escape_ffmpeg_filter_path 內部的 replace("\\", "/") 邏輯
        # 這裡我們信任上述測試已覆蓋基本邏輯
        return

    @patch('utils.platform_utils.get_platform')
    def test_escape_path_macos(self, mock_platform):
        """測試 macOS 路徑轉義"""
        mock_platform.return_value = 'macos'
        
        input_path = Path("/Users/admin/Movies/subtitle.ass")
        # macOS 只需轉義冒號（雖然路徑中罕見冒號）
        expected = "/Users/admin/Movies/subtitle.ass"
        self.assertEqual(escape_ffmpeg_filter_path(input_path), expected)
    
    @patch('utils.platform_utils.get_platform')
    @patch('pathlib.Path.exists')
    def test_font_detection_macos(self, mock_exists, mock_platform):
        """測試 macOS 字體偵測"""
        mock_platform.return_value = 'macos'
        mock_exists.return_value = True
        
        font = get_default_font_path()
        self.assertEqual(font, "/System/Library/Fonts/PingFang.ttc")
        
    @patch('utils.platform_utils.get_platform')
    @patch('pathlib.Path.exists')
    def test_font_detection_windows(self, mock_exists, mock_platform):
        """測試 Windows 字體偵測"""
        mock_platform.return_value = 'windows'
        # 模擬第一個字體 (msjh.ttc) 存在
        mock_exists.side_effect = [True, False, False]
        
        font = get_default_font_path()
        self.assertIn("msjh.ttc", font)

if __name__ == '__main__':
    unittest.main()
