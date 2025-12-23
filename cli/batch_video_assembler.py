#!/usr/bin/env python3
"""
自動化簡報影片合成工具 - CLI 入口
呼叫 VideoProcessor 執行完整影片處理流程
"""

import sys
import argparse
from pathlib import Path

# 將專案根目錄加入 Python 路徑
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from services.video_processor import VideoProcessor
from config import OutputConfig


def normalize_path(input_path: str) -> Path:
    """正規化並驗證輸入路徑"""
    input_path = input_path.strip().strip('"').strip("'")
    return Path(input_path).expanduser().resolve()


def print_header():
    """印出歡迎標題"""
    print("\n" + "=" * 60)
    print("🎬 自動化簡報影片合成工具 (CLI)")
    print("   引擎核心：FFmpeg (高效能版)")
    print("=" * 60 + "\n")


def main():
    print_header()
    
    # 設定參數解析
    parser = argparse.ArgumentParser(description="自動化簡報影片合成工具")
    parser.add_argument("folder_path", nargs="?", help="素材資料夾路徑")
    parser.add_argument("--skip-subtitle", action="store_true", help="跳過字幕生成")
    parser.add_argument("--subtitle-only", action="store_true", help="僅生成字幕")
    parser.add_argument("--video-only", action="store_true", help="僅合成影片")
    parser.add_argument("--no-debug", action="store_true", help="關閉除錯資訊（預設為開啟）")
    parser.add_argument("-o", "--output", help="指定輸出路徑")
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
    if args.output:
        output_path = normalize_path(args.output)
    else:
        output_name = folder_path.name
        output_path = OutputConfig.OUTPUT_DIR / f"{output_name}.mp4"
    
    print(f"📁 素材資料夾：{folder_path}")
    
    # 初始化處理器
    processor = VideoProcessor()
    
    # 決定 debug 模式（預設開啟，除非指定關閉）
    debug_mode = not args.no_debug
    
    try:
        if args.subtitle_only:
            # 僅生成字幕
            print("📝 模式：僅生成字幕")
            srt_path = processor.generate_subtitle_only(folder_path, debug=debug_mode)
            print(f"\n✅ 字幕生成完成：{srt_path}")
            
        elif args.video_only:
            # 僅合成影片
            print("🎬 模式：僅合成影片")
            print(f"📝 輸出路徑：{output_path}")
            video_path = processor.assemble_video_only(folder_path, output_path)
            print(f"\n✅ 影片合成完成：{video_path}")
            
        else:
            # 完整流程
            print("🎬 模式：完整流程（字幕 + 合成）")
            print(f"📝 輸出路徑：{output_path}")
            video_path = processor.process(
                folder_path, 
                output_path,
                skip_subtitle=args.skip_subtitle,
                debug=debug_mode
            )
            print(f"\n✅ 處理完成：{video_path}")
            
    except FileNotFoundError as e:
        print(f"\n❌ 錯誤：{e}")
        sys.exit(1)
    except ValueError as e:
        print(f"\n❌ 錯誤：{e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 發生錯誤：{e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
