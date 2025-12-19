#!/usr/bin/env python3
"""
自動化簡報影片合成工具 (Batch Video Assembler) V10
引擎架構：FFmpeg（高效能）

功能：
- 將切片化的語音與圖片組裝成完整的 16:9 簡報影片
- 自動疊加無聲的人頭解說影片於右下角（圓形遮罩）
- 自動燒錄字幕（如有 SRT 檔）
- 自動以資料夾名稱作為輸出檔名
"""

import sys
import argparse
from pathlib import Path
from config import OutputConfig
from engines import ffmpeg_engine


def print_header():
    """印出歡迎標題"""
    print("\n" + "=" * 60)
    print("🎬 自動化簡報影片合成工具 V10")
    print("   引擎核心：FFmpeg (高效能版)")
    print("=" * 60 + "\n")


def normalize_path(input_path: str) -> Path:
    """正規化並驗證輸入路徑"""
    input_path = input_path.strip().strip('"').strip("'")
    path = Path(input_path).expanduser().resolve()
    return path


def main():
    print_header()
    
    # 設定參數解析
    parser = argparse.ArgumentParser(description="自動化簡報影片合成工具")
    parser.add_argument("folder_path", nargs="?", help="素材資料夾路徑")
    # engine 參數已移除，固定使用 ffmpeg
    args = parser.parse_args()
    
    # 輸入素材路徑
    if args.folder_path:
        input_path = args.folder_path
        print(f"🚀 CLI 模式啟動")
    else:
        try:
            input_path = input("\n📂 請輸入素材資料夾路徑：").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n\n❌ 操作已取消")
            sys.exit(0)

    if not input_path:
        print("❌ 錯誤：請提供資料夾路徑")
        sys.exit(1)
    
    folder_path = normalize_path(input_path)
    
    if not folder_path.exists():
        print(f"❌ 錯誤：資料夾不存在：{folder_path}")
        sys.exit(1)
    
    if not folder_path.is_dir():
        print(f"❌ 錯誤：路徑不是資料夾：{folder_path}")
        sys.exit(1)
    
    # 設定輸出路徑
    output_name = folder_path.name
    output_path = OutputConfig.OUTPUT_DIR / f"{output_name}.mp4"
    
    print(f"\n📁 素材資料夾：{folder_path}")
    print(f"📝 輸出路徑：{output_path}")
    
    # 執行 FFmpeg 引擎
    try:
        ffmpeg_engine.run(folder_path, output_path)
            
    except FileNotFoundError as e:
        print(f"\n❌ 錯誤：{e}")
        sys.exit(1)
    except ValueError as e:
        print(f"\n❌ 錯誤：{e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 發生錯誤：{e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
