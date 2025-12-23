#!/usr/bin/env python3
"""
AI 自動字幕生成器 - CLI 入口
呼叫 SubtitleService 執行字幕生成
"""

import sys
from pathlib import Path

# 將專案根目錄加入 Python 路徑
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from services.subtitle_service import SubtitleService


def normalize_path(input_path: str) -> Path:
    """正規化並驗證輸入路徑"""
    input_path = input_path.strip().strip('"').strip("'")
    return Path(input_path).expanduser().resolve()


def main():
    print("============================================================")
    print("🎙️  AI 自動字幕生成器 (CLI)")
    print("   Avatar 音軌提取 -> Whisper -> Force Align -> GPT -> SRT")
    print("============================================================")
    
    # 預設路徑 (方便測試)
    default_path = "/Users/a01-0218-0512/Downloads/nvdia_jay"
    
    try:
        user_input = input(f"📂 請輸入素材資料夾路徑 (預設: {default_path})：").strip()
    except (KeyboardInterrupt, EOFError):
        print("\n\n❌ 操作已取消")
        sys.exit(0)
    
    if not user_input:
        folder_path = default_path
    else:
        folder_path = user_input
    
    work_dir = normalize_path(folder_path)
    
    if not work_dir.exists():
        print(f"❌ 找不到路徑：{work_dir}")
        sys.exit(1)
    
    if not work_dir.is_dir():
        print(f"❌ 路徑不是資料夾：{work_dir}")
        sys.exit(1)
    
    # 呼叫字幕服務
    try:
        service = SubtitleService()
        srt_path = service.generate(work_dir, debug=True)
        print(f"\n✅ 字幕生成完成：{srt_path}")
    except FileNotFoundError as e:
        print(f"\n❌ 錯誤：{e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 發生錯誤：{e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
