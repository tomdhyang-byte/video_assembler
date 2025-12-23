"""
影片處理器 - 統一入口
串接字幕生成和影片合成服務
"""

from pathlib import Path
from typing import Optional

from .subtitle_service import SubtitleService
from .assembly_service import AssemblyService


class VideoProcessor:
    """
    統一的影片處理服務
    
    這是 API 和 CLI 共用的入口點，提供完整的影片處理流程：
    1. 字幕生成（可選）
    2. 影片合成
    """
    
    def __init__(self):
        self.subtitle_service = SubtitleService()
        self.assembly_service = AssemblyService()
    
    def process(
        self,
        folder_path: Path,
        output_path: Path = None,
        skip_subtitle: bool = False,
        debug: bool = False
    ) -> Path:
        """
        完整處理流程：字幕生成 + 影片合成
        
        Args:
            folder_path: 素材資料夾路徑
            output_path: 輸出影片路徑（可選）
            skip_subtitle: 是否跳過字幕生成（如果已有 SRT 檔）
            debug: 是否儲存中間結果供除錯
            
        Returns:
            生成的影片檔案路徑
        """
        folder_path = Path(folder_path)
        
        print("\n" + "=" * 60)
        print("🎬 VideoProcessor - 完整影片處理流程")
        print("=" * 60)
        
        # 檢查是否需要生成字幕
        srt_path = folder_path / "full_subtitle.srt"
        script_path = folder_path / "full_script.txt"
        
        if not skip_subtitle and script_path.exists():
            if srt_path.exists():
                print(f"\n📝 發現現有字幕檔案：{srt_path}")
                print("   如需重新生成，請刪除現有檔案或使用 skip_subtitle=False")
            else:
                print("\n📝 開始生成字幕...")
                self.subtitle_service.generate(folder_path, debug=debug)
        elif skip_subtitle:
            print("\n⏭️  跳過字幕生成（skip_subtitle=True）")
        else:
            print("\n⏭️  未發現逐字稿，跳過字幕生成")
        
        # 合成影片
        print("\n🎬 開始合成影片...")
        video_path = self.assembly_service.assemble(folder_path, output_path)
        
        print("\n" + "=" * 60)
        print("✅ 完整流程處理完成！")
        print(f"   輸出影片：{video_path}")
        print("=" * 60)
        
        return video_path
    
    def generate_subtitle_only(
        self,
        folder_path: Path,
        debug: bool = False
    ) -> Path:
        """
        僅生成字幕（不合成影片）
        
        Args:
            folder_path: 素材資料夾路徑
            debug: 是否儲存中間結果
            
        Returns:
            生成的 SRT 檔案路徑
        """
        return self.subtitle_service.generate(folder_path, debug=debug)
    
    def assemble_video_only(
        self,
        folder_path: Path,
        output_path: Path = None
    ) -> Path:
        """
        僅合成影片（假設字幕已存在）
        
        Args:
            folder_path: 素材資料夾路徑
            output_path: 輸出影片路徑
            
        Returns:
            生成的影片檔案路徑
        """
        return self.assembly_service.assemble(folder_path, output_path)
    
    def validate(self, folder_path: Path) -> dict:
        """
        驗證素材資料夾
        
        Args:
            folder_path: 素材資料夾路徑
            
        Returns:
            驗證結果
        """
        return self.assembly_service.validate_materials(folder_path)
