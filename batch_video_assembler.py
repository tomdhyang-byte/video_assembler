#!/usr/bin/env python3
"""
自動化簡報影片合成工具 (Batch Video Assembler)
根據 PRD V3.0 規格開發

功能：
- 將切片化的語音與圖片組裝成完整的 16:9 簡報影片
- 自動疊加無聲的人頭解說影片於右下角（圓形遮罩）
- 自動以資料夾名稱作為輸出檔名
"""

import os
import sys
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

# moviepy imports
from moviepy.editor import (
    ImageClip,
    AudioFileClip,
    VideoFileClip,
    concatenate_videoclips,
    CompositeVideoClip
)


# ============================================================
# 設定常數
# ============================================================
TARGET_WIDTH = 1920
TARGET_HEIGHT = 1080
AVATAR_SCALE_RATIO = 0.12  # Avatar 寬度為畫面的 12%
AVATAR_MARGIN_X = 30  # 右邊距
AVATAR_MARGIN_Y = 30  # 下邊距
OUTPUT_FPS = 24
VIDEO_CODEC = "libx264"
AUDIO_CODEC = "aac"

# Avatar 裁切設定（針對 1080x1920 直式影片）
# 裁切出剛好包住人頭的正方形，讓圓形遮罩完美框住人頭
# 原始影片：1080（寬）x 1920（高）
AVATAR_CROP_X = 200       # 水平位置（讓人頭居中）
AVATAR_CROP_Y = 550       # 垂直位置（從頭頂開始）
AVATAR_CROP_SIZE = 650    # 正方形大小（剛好包住人頭）

# 測試模式：設為 True 時不縮放，方便驗證遮罩效果
AVATAR_TEST_MODE = False  # 正常模式：縮放到 12% 並定位到右下角

# 要忽略的系統檔案
IGNORE_FILES = {".DS_Store", "Thumbs.db", ".gitkeep", "desktop.ini"}


# ============================================================
# 工具函數
# ============================================================
def print_header():
    """印出歡迎標題"""
    print("\n" + "=" * 60)
    print("🎬 自動化簡報影片合成工具 (Batch Video Assembler)")
    print("=" * 60 + "\n")


def normalize_path(input_path: str) -> Path:
    """
    正規化並驗證輸入路徑
    支援絕對路徑與相對路徑
    """
    # 處理使用者可能輸入的引號
    input_path = input_path.strip().strip('"').strip("'")
    
    # 展開 ~ 為 home 目錄
    path = Path(input_path).expanduser().resolve()
    
    return path


def extract_folder_name(path: Path) -> str:
    """
    提取資料夾名稱作為輸出檔名
    處理路徑末端可能帶有斜線的情況
    """
    return path.name


def find_matching_pairs(folder: Path) -> list:
    """
    掃描資料夾，找出 PNG/JPG 與 MP3 的配對
    回傳: [(序號, 圖片路徑, mp3路徑), ...]
    """
    # 找出所有圖片和 MP3 檔案
    image_files = {}
    mp3_files = {}
    
    for file in folder.iterdir():
        if file.name in IGNORE_FILES:
            continue
        
        stem = file.stem  # 不含副檔名的檔名 (例如 "01")
        suffix = file.suffix.lower()
        
        if suffix in (".png", ".jpg", ".jpeg"):
            image_files[stem] = file
        elif suffix == ".mp3":
            mp3_files[stem] = file
    
    # 找出共同的序號
    common_keys = set(image_files.keys()) & set(mp3_files.keys())
    
    if not common_keys:
        return []
    
    # 排序並建立配對列表
    pairs = []
    for key in sorted(common_keys):
        pairs.append((key, image_files[key], mp3_files[key]))
    
    # 警告未配對的檔案
    unmatched_images = set(image_files.keys()) - common_keys
    unmatched_mp3 = set(mp3_files.keys()) - common_keys
    
    if unmatched_images:
        print(f"⚠️  警告：以下圖片檔案沒有對應的 MP3：{sorted(unmatched_images)}")
    if unmatched_mp3:
        print(f"⚠️  警告：以下 MP3 檔案沒有對應的圖片：{sorted(unmatched_mp3)}")
    
    return pairs


def concat_audio_with_ffmpeg(pairs: list, output_path: Path) -> Path:
    """
    使用 FFmpeg 直接拼接 MP3 檔案（繞過 MoviePy 的音訊拼接 bug）
    回傳拼接後的音檔路徑
    """
    print("\n🔊 使用 FFmpeg 拼接音檔...")
    
    # 建立暫存的檔案清單
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        for seq, _, mp3_path in pairs:
            # FFmpeg concat 需要特殊格式的路徑
            f.write(f"file '{mp3_path}'\n")
        filelist_path = f.name
    
    try:
        # 使用 FFmpeg 直接拼接（-c copy 保持原始格式）
        result = subprocess.run([
            'ffmpeg', '-y', '-f', 'concat', '-safe', '0',
            '-i', filelist_path,
            '-c', 'copy',
            str(output_path)
        ], capture_output=True, text=True)
        
        if result.returncode != 0:
            print(f"⚠️  FFmpeg 警告：{result.stderr[-500:] if result.stderr else 'unknown'}")
        
        print(f"   ✅ 音檔拼接完成：{output_path}")
        return output_path
        
    finally:
        # 清理暫存檔
        os.unlink(filelist_path)


def resize_image_cover(image_path: Path, target_width: int, target_height: int) -> np.ndarray:
    """
    將圖片以 cover 模式縮放（填滿目標尺寸，超出部分裁切）
    這確保圖片完整覆蓋畫面，不會有黑邊
    """
    img = Image.open(str(image_path))
    orig_width, orig_height = img.size
    
    # 計算縮放比例（取較大者以確保填滿）
    scale_w = target_width / orig_width
    scale_h = target_height / orig_height
    scale = max(scale_w, scale_h)
    
    # 縮放
    new_width = int(orig_width * scale)
    new_height = int(orig_height * scale)
    img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
    
    # 計算裁切區域（置中裁切）
    left = (new_width - target_width) // 2
    top = (new_height - target_height) // 2
    right = left + target_width
    bottom = top + target_height
    
    img = img.crop((left, top, right, bottom))
    
    # 轉換為 RGB（確保沒有 alpha 通道問題）
    if img.mode != 'RGB':
        img = img.convert('RGB')
    
    return np.array(img)


def create_circle_mask(size: int) -> np.ndarray:
    """
    建立圓形遮罩（用於 Avatar）
    回傳一個 (size, size) 的 float 陣列，值介於 0-1
    """
    mask = Image.new('L', (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((0, 0, size - 1, size - 1), fill=255)
    return np.array(mask) / 255.0


# ============================================================
# 主要處理邏輯
# ============================================================
def build_base_track(pairs: list, merged_audio_path: Path) -> VideoFileClip:
    """
    步驟二：建立 16:9 基礎軌
    將圖片依照各自音訊長度串接，最後綁定預先拼接好的完整音檔
    圖片使用 cover 模式縮放以填滿畫面
    """
    clips = []
    
    for idx, (seq, image_path, mp3_path) in enumerate(pairs, 1):
        suffix = image_path.suffix.lower()
        print(f"   📄 處理中 [{idx}/{len(pairs)}]: {seq}{suffix} + {seq}.mp3")
        
        # 讀取音訊以取得長度（僅用於計算時長）
        audio = AudioFileClip(str(mp3_path))
        duration = audio.duration
        audio.close()  # 立即關閉，不使用 MoviePy 處理音訊
        
        # 將圖片以 cover 模式縮放到 1920x1080
        img_array = resize_image_cover(image_path, TARGET_WIDTH, TARGET_HEIGHT)
        
        # 建立圖片 clip 並設定長度（不綁定音訊）
        image = ImageClip(img_array).set_duration(duration)
        
        clips.append(image)
    
    # 串接所有片段（無音訊）
    print("\n   🔗 正在串接所有片段...")
    base_track = concatenate_videoclips(clips, method="compose")
    
    # 綁定預先用 FFmpeg 拼接好的完整音檔
    print("   🔊 綁定合併音檔...")
    merged_audio = AudioFileClip(str(merged_audio_path))
    base_track = base_track.set_audio(merged_audio)
    
    return base_track


def create_avatar_overlay(avatar_path: Path, base_duration: float) -> VideoFileClip:
    """
    步驟三：建立人頭疊加層
    1. 裁切出人頭區域（正方形）
    2. 套用圓形遮罩
    3. 縮放並定位到右下角
    """
    print(f"\n👤 處理 Avatar 影片...")
    
    # 讀取 avatar 並移除音軌
    avatar = VideoFileClip(str(avatar_path)).set_audio(None)
    orig_w, orig_h = avatar.w, avatar.h
    print(f"   📐 原始尺寸：{orig_w}x{orig_h}")
    
    # 步驟 1：裁切成正方形（只保留人頭區域）
    crop_x = AVATAR_CROP_X
    crop_y = AVATAR_CROP_Y
    crop_size = min(AVATAR_CROP_SIZE, orig_w - crop_x, orig_h - crop_y)  # 確保不超出邊界
    
    print(f"   ✂️  裁切區域：({crop_x}, {crop_y}) 大小 {crop_size}x{crop_size}")
    avatar = avatar.crop(x1=crop_x, y1=crop_y, x2=crop_x + crop_size, y2=crop_y + crop_size)
    
    # 步驟 2：計算最終尺寸
    if AVATAR_TEST_MODE:
        # 測試模式：不縮放，使用裁切後的原始大小
        target_avatar_size = crop_size
        print(f"   🧪 測試模式：保持原始大小 {target_avatar_size}x{target_avatar_size}")
    else:
        # 正常模式：縮放到畫面的指定比例
        target_avatar_size = int(TARGET_WIDTH * AVATAR_SCALE_RATIO)
        print(f"   📏 縮放至：{target_avatar_size}x{target_avatar_size}")
        avatar = avatar.resize((target_avatar_size, target_avatar_size))
    
    # 步驟 3：建立圓形遮罩並套用
    circle_mask = create_circle_mask(target_avatar_size)
    
    # 建立一個 mask clip（值為 0-1，1 表示完全不透明，0 表示完全透明）
    def make_mask_frame(t):
        return circle_mask
    
    from moviepy.video.VideoClip import VideoClip
    mask_clip = VideoClip(make_mask_frame, ismask=True, duration=avatar.duration)
    mask_clip = mask_clip.set_fps(avatar.fps)
    
    # 套用遮罩
    avatar = avatar.set_mask(mask_clip)
    
    # 步驟 4：計算定位座標（右下角）
    pos_x = TARGET_WIDTH - target_avatar_size - AVATAR_MARGIN_X
    pos_y = TARGET_HEIGHT - target_avatar_size - AVATAR_MARGIN_Y
    print(f"   📍 定位：({pos_x}, {pos_y})")
    
    avatar = avatar.set_position((pos_x, pos_y))
    
    # 同步長度
    if avatar.duration > base_duration:
        print(f"   ✂️  裁切 Avatar：{avatar.duration:.2f}s → {base_duration:.2f}s")
        avatar = avatar.subclip(0, base_duration)
    elif avatar.duration < base_duration:
        print(f"   ℹ️  Avatar 較短（{avatar.duration:.2f}s），將在 {avatar.duration:.2f}s 後消失")
    
    return avatar


def render_final_video(base_track, avatar_overlay, output_path: Path):
    """
    步驟四：最終合成與渲染
    """
    print(f"\n🎬 開始最終渲染...")
    print(f"   📊 影片長度：{base_track.duration:.2f} 秒")
    print(f"   📁 輸出位置：{output_path}")
    
    # 合成最終影片
    final = CompositeVideoClip(
        [base_track, avatar_overlay],
        size=(TARGET_WIDTH, TARGET_HEIGHT)
    )
    
    # 渲染輸出
    final.write_videofile(
        str(output_path),
        fps=OUTPUT_FPS,
        codec=VIDEO_CODEC,
        audio_codec=AUDIO_CODEC,
        threads=4,  # 使用多執行緒加速
        preset="medium"  # 平衡速度與品質
    )
    
    # 清理資源
    final.close()
    base_track.close()
    avatar_overlay.close()
    
    print(f"\n✅ 完成！影片已儲存至：{output_path}")


# ============================================================
# 主程式入口
# ============================================================
def main():
    print_header()
    
    # 步驟一：接收並解析路徑
    try:
        input_path = input("📂 請輸入素材資料夾路徑：").strip()
    except (KeyboardInterrupt, EOFError):
        print("\n\n❌ 操作已取消")
        sys.exit(0)
    
    if not input_path:
        print("❌ 錯誤：請提供資料夾路徑")
        sys.exit(1)
    
    # 正規化路徑
    folder_path = normalize_path(input_path)
    
    # 驗證資料夾存在
    if not folder_path.exists():
        print(f"❌ 錯誤：資料夾不存在：{folder_path}")
        sys.exit(1)
    
    if not folder_path.is_dir():
        print(f"❌ 錯誤：路徑不是資料夾：{folder_path}")
        sys.exit(1)
    
    # 提取資料夾名稱作為輸出檔名
    output_name = extract_folder_name(folder_path)
    output_path = Path.cwd() / f"{output_name}.mp4"
    
    print(f"📁 素材資料夾：{folder_path}")
    print(f"📝 輸出檔名：{output_name}.mp4\n")
    
    # 檢查 avatar 影片
    avatar_path = folder_path / "avatar_full_silent.mp4"
    if not avatar_path.exists():
        print(f"❌ 錯誤：找不到 Avatar 影片：{avatar_path}")
        sys.exit(1)
    
    # 步驟二：尋找並配對素材
    print("🔍 掃描素材...")
    pairs = find_matching_pairs(folder_path)
    
    if not pairs:
        print("❌ 錯誤：找不到任何圖片/MP3 配對")
        sys.exit(1)
    
    print(f"   ✅ 找到 {len(pairs)} 組配對\n")
    
    # 使用 FFmpeg 預先拼接所有音檔
    merged_audio_path = folder_path / "_merged_audio.mp3"
    concat_audio_with_ffmpeg(pairs, merged_audio_path)
    
    # 建立基礎軌（使用拼接好的音檔）
    print("\n🎞️  建立基礎軌（圖片以 cover 模式填滿畫面）...")
    base_track = build_base_track(pairs, merged_audio_path)
    
    # 步驟三：建立 avatar 疊加層（圓形遮罩）
    avatar_overlay = create_avatar_overlay(avatar_path, base_track.duration)
    
    # 步驟四：最終渲染
    render_final_video(base_track, avatar_overlay, output_path)
    
    # 清理暫存的合併音檔
    if merged_audio_path.exists():
        merged_audio_path.unlink()
        print(f"🧹 已清理暫存音檔")


if __name__ == "__main__":
    main()
