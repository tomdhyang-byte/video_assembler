#!/usr/bin/env python3
"""
自動化簡報影片合成工具 (Batch Video Assembler) V3
雙引擎架構：MoviePy（穩定）/ FFmpeg（高效能）

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


def print_header():
    """印出歡迎標題"""
    print("\n" + "=" * 60)
    print("🎬 自動化簡報影片合成工具 V3")
    print("   雙引擎架構：MoviePy / FFmpeg")
    print("=" * 60 + "\n")


def normalize_path(input_path: str) -> Path:
    """正規化並驗證輸入路徑"""
    input_path = input_path.strip().strip('"').strip("'")
    path = Path(input_path).expanduser().resolve()
    return path


def select_engine():
    """選擇渲染引擎"""
    print("請選擇渲染引擎：")
    print("  [1] FFmpeg（推薦，高效能）")
    print("  [2] MoviePy（穩定，較慢）")
    print()
    
    try:
        choice = input("請輸入選項 (1/2，預設 1)：").strip()
    except (KeyboardInterrupt, EOFError):
        print("\n\n❌ 操作已取消")
        sys.exit(0)
    
    if choice == "2":
        return "moviepy"
    return "ffmpeg"  # 預設使用 FFmpeg


def main():
    print_header()
    
    # 設定參數解析
    parser = argparse.ArgumentParser(description="自動化簡報影片合成工具")
    parser.add_argument("folder_path", nargs="?", help="素材資料夾路徑")
    parser.add_argument("--engine", choices=["ffmpeg", "moviepy"], default="ffmpeg", help="渲染引擎 (預設: ffmpeg)")
    args = parser.parse_args()
    
    # 1. 決定渲染引擎
    if args.folder_path:
        # 如果有指定路徑，直接使用參數指定的引擎 (預設 ffmpeg)
        engine_name = args.engine
        input_path = args.folder_path
        print(f"🚀 CLI 模式啟動 - 引擎: {engine_name}")
    else:
        # 互動模式
        engine_name = select_engine()
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
    
    # 載入並執行引擎
    try:
        if engine_name == "ffmpeg":
            from engines import ffmpeg_engine
            ffmpeg_engine.run(folder_path, output_path)
        else:
            from engines import moviepy_engine
            moviepy_engine.run(folder_path, output_path)
            
    except FileNotFoundError as e:
        print(f"\n❌ 錯誤：{e}")
        sys.exit(1)
    except ValueError as e:
        print(f"\n❌ 錯誤：{e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 發生錯誤：{e}")
        if engine_name == "ffmpeg":
            print("\n💡 提示：如果 FFmpeg 引擎失敗，可嘗試使用 MoviePy 引擎")
        sys.exit(1)


if __name__ == "__main__":
    main()
