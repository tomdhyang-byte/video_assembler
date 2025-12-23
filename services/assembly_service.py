"""
影片合成服務
封裝 ffmpeg_engine 的入口
"""

from pathlib import Path

from engines import ffmpeg_engine
from config import OutputConfig


class AssemblyService:
    """
    影片合成服務
    
    功能：
    - 將切片化的語音與圖片組裝成完整的 16:9 簡報影片
    - 自動疊加 Avatar 於右下角（圓形遮罩）
    - 自動燒錄字幕（如有 SRT 檔）
    """
    
    def __init__(self):
        pass
    
    def assemble(
        self, 
        folder_path: Path, 
        output_path: Path = None
    ) -> Path:
        """
        合成影片的主入口
        
        Args:
            folder_path: 素材資料夾路徑
            output_path: 輸出影片路徑（可選，預設使用資料夾名稱）
            
        Returns:
            生成的影片檔案路徑
        """
        folder_path = Path(folder_path)
        
        # 如果未指定輸出路徑，使用預設命名規則
        if output_path is None:
            output_name = folder_path.name
            output_path = OutputConfig.OUTPUT_DIR / f"{output_name}.mp4"
        else:
            output_path = Path(output_path)
        
        print("\n" + "=" * 60)
        print("🎬 影片合成服務")
        print("   引擎核心：FFmpeg (高效能版)")
        print("=" * 60 + "\n")
        
        print(f"📁 素材資料夾：{folder_path}")
        print(f"📝 輸出路徑：{output_path}")
        
        # 呼叫 FFmpeg 引擎
        ffmpeg_engine.run(folder_path, output_path)
        
        return output_path
    
    def validate_materials(self, folder_path: Path) -> dict:
        """
        驗證素材資料夾內容
        
        Args:
            folder_path: 素材資料夾路徑
            
        Returns:
            驗證結果字典，包含各類型檔案的清單
        """
        folder_path = Path(folder_path)
        
        result = {
            "valid": True,
            "avatar": None,
            "subtitle": None,
            "pairs": [],
            "errors": []
        }
        
        # 檢查 Avatar
        avatar_path = folder_path / "avatar_full.mp4"
        if avatar_path.exists():
            result["avatar"] = avatar_path
        else:
            result["valid"] = False
            result["errors"].append(f"找不到 Avatar 影片：{avatar_path}")
        
        # 檢查字幕
        subtitle_path = folder_path / "full_subtitle.srt"
        if subtitle_path.exists():
            result["subtitle"] = subtitle_path
        
        # 檢查圖片/MP3 配對
        image_files = {}
        mp3_files = {}
        
        for file in folder_path.iterdir():
            stem = file.stem
            suffix = file.suffix.lower()
            
            if suffix in (".png", ".jpg", ".jpeg"):
                image_files[stem] = file
            elif suffix == ".mp3":
                mp3_files[stem] = file
        
        common_keys = set(image_files.keys()) & set(mp3_files.keys())
        
        for key in sorted(common_keys, key=lambda x: (0, int(x)) if x.isdigit() else (1, x)):
            result["pairs"].append({
                "key": key,
                "image": image_files[key],
                "audio": mp3_files[key]
            })
        
        if not result["pairs"]:
            result["valid"] = False
            result["errors"].append("找不到任何圖片/MP3 配對")
        
        return result
