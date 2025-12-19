#!/usr/bin/env python3
"""
MoviePy 引擎 - 使用 MoviePy 庫進行影片合成
穩定但較慢，作為 FFmpeg 引擎的備用方案
"""

import os
import subprocess
import tempfile
import re
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from moviepy import (
    ImageClip,
    AudioFileClip,
    VideoFileClip,
    TextClip,
    concatenate_videoclips,
    CompositeVideoClip
)

from config import (
    VideoConfig,
    SubtitleConfig,
    AvatarConfig,
    FileNames,
    OutputConfig,
    IGNORE_FILES
)


# ============================================================
# 工具函數
# ============================================================
def normalize_path(input_path: str) -> Path:
    """正規化並驗證輸入路徑"""
    input_path = input_path.strip().strip('"').strip("'")
    path = Path(input_path).expanduser().resolve()
    return path


def extract_folder_name(path: Path) -> str:
    """提取資料夾名稱作為輸出檔名"""
    return path.name


def find_matching_pairs(folder: Path) -> list:
    """
    掃描資料夾，找出 PNG/JPG 與 MP3 的配對
    回傳: [(序號, 圖片路徑, mp3路徑), ...]
    """
    image_files = {}
    mp3_files = {}
    
    for file in folder.iterdir():
        if file.name in IGNORE_FILES:
            continue
        
        stem = file.stem
        suffix = file.suffix.lower()
        
        if suffix in (".png", ".jpg", ".jpeg"):
            image_files[stem] = file
        elif suffix == ".mp3":
            mp3_files[stem] = file
    
    common_keys = set(image_files.keys()) & set(mp3_files.keys())
    
    if not common_keys:
        return []
    
    pairs = []
    # 數字排序：1, 2, 3, ..., 9, 10, 11 而非字母排序 1, 10, 11, 2, 3
    def numeric_sort_key(x):
        try:
            return (0, int(x))  # 純數字排在前面
        except ValueError:
            return (1, x)  # 非數字按字母排序
    
    for key in sorted(common_keys, key=numeric_sort_key):
        pairs.append((key, image_files[key], mp3_files[key]))
    
    unmatched_images = set(image_files.keys()) - common_keys
    unmatched_mp3 = set(mp3_files.keys()) - common_keys
    
    if unmatched_images:
        print(f"⚠️  警告：以下圖片檔案沒有對應的 MP3：{sorted(unmatched_images)}")
    if unmatched_mp3:
        print(f"⚠️  警告：以下 MP3 檔案沒有對應的圖片：{sorted(unmatched_mp3)}")
    
    return pairs


def concat_audio_with_ffmpeg(pairs: list, output_path: Path) -> Path:
    """使用 FFmpeg 直接拼接 MP3 檔案"""
    print("\n🔊 使用 FFmpeg 拼接音檔...")
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        for seq, _, mp3_path in pairs:
            f.write(f"file '{mp3_path}'\n")
        filelist_path = f.name
    
    try:
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
        os.unlink(filelist_path)


def resize_image_cover(image_path: Path, target_width: int, target_height: int) -> np.ndarray:
    """將圖片以 cover 模式縮放"""
    img = Image.open(str(image_path))
    orig_width, orig_height = img.size
    
    scale_w = target_width / orig_width
    scale_h = target_height / orig_height
    scale = max(scale_w, scale_h)
    
    new_width = int(orig_width * scale)
    new_height = int(orig_height * scale)
    img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
    
    left = (new_width - target_width) // 2
    top = (new_height - target_height) // 2
    right = left + target_width
    bottom = top + target_height
    
    img = img.crop((left, top, right, bottom))
    
    if img.mode != 'RGB':
        img = img.convert('RGB')
    
    return np.array(img)


def create_circle_mask(size: int) -> np.ndarray:
    """建立圓形遮罩"""
    mask = Image.new('L', (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((0, 0, size - 1, size - 1), fill=255)
    return np.array(mask) / 255.0


# ============================================================
# 字幕處理函數
# ============================================================
def parse_srt(srt_path: Path) -> list:
    """
    解析 SRT 字幕檔案
    回傳: [{"start": float, "end": float, "text": str}, ...]
    """
    with open(srt_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    pattern = r"(\d+)\n(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})\n(.+?)(?=\n\n|\n*$)"
    matches = re.findall(pattern, content, re.DOTALL)
    
    subtitles = []
    for match in matches:
        idx, start_str, end_str, text = match
        
        def parse_timestamp(ts: str) -> float:
            h, m, rest = ts.split(":")
            s, ms = rest.split(",")
            return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000
        
        subtitles.append({
            "start": parse_timestamp(start_str),
            "end": parse_timestamp(end_str),
            "text": text.strip().replace("\n", " ")
        })
    
    return subtitles


def create_subtitle_clips(subtitles: list, video_duration: float) -> list:
    """根據字幕列表建立 TextClip 物件"""
    clips = []
    
    for sub in subtitles:
        if sub["start"] >= video_duration:
            continue
        
        end_time = min(sub["end"], video_duration)
        duration = end_time - sub["start"]
        
        if duration <= 0:
            continue
        
        try:
            txt_clip = TextClip(
                text=sub["text"] + "\n ",  # HACK: 防止描邊被切斷
                font_size=SubtitleConfig.FONT_SIZE,
                color=SubtitleConfig.COLOR,
                stroke_color=SubtitleConfig.STROKE_COLOR,
                stroke_width=SubtitleConfig.STROKE_WIDTH,
                font=SubtitleConfig.FONT_PATH,
                method="caption",
                size=(VideoConfig.WIDTH - 100, None),
                text_align="center"
            )
            
            # 中心對齊
            visible_height = txt_clip.h / 2
            position_y = SubtitleConfig.CENTER_Y - (visible_height / 2)
            txt_clip = txt_clip.with_position(("center", position_y))
            
            txt_clip = txt_clip.with_start(sub["start"]).with_duration(duration)
            clips.append(txt_clip)
            
        except Exception as e:
            print(f"⚠️  字幕建立失敗：{sub['text'][:20]}... ({e})")
    
    return clips


# ============================================================
# 主要處理邏輯
# ============================================================
def build_base_track(pairs: list, merged_audio_path: Path):
    """建立 16:9 基礎軌"""
    clips = []
    
    for idx, (seq, image_path, mp3_path) in enumerate(pairs, 1):
        suffix = image_path.suffix.lower()
        print(f"   📄 處理中 [{idx}/{len(pairs)}]: {seq}{suffix} + {seq}.mp3")
        
        audio = AudioFileClip(str(mp3_path))
        duration = audio.duration
        audio.close()
        
        img_array = resize_image_cover(image_path, VideoConfig.WIDTH, VideoConfig.HEIGHT)
        image = ImageClip(img_array).with_duration(duration)
        
        clips.append(image)
    
    print("\n   🔗 正在串接所有片段...")
    base_track = concatenate_videoclips(clips, method="compose")
    
    print("   🔊 綁定合併音檔...")
    merged_audio = AudioFileClip(str(merged_audio_path))
    base_track = base_track.with_audio(merged_audio)
    
    return base_track


def create_avatar_overlay(avatar_path: Path, base_duration: float):
    """建立人頭疊加層"""
    print(f"\n👤 處理 Avatar 影片...")
    
    avatar = VideoFileClip(str(avatar_path)).with_audio(None)
    orig_w, orig_h = avatar.w, avatar.h
    print(f"   📐 原始尺寸：{orig_w}x{orig_h}")
    
    crop_x = AvatarConfig.CROP_X
    crop_y = AvatarConfig.CROP_Y
    crop_size = min(AvatarConfig.CROP_SIZE, orig_w - crop_x, orig_h - crop_y)
    
    print(f"   ✂️  裁切區域：({crop_x}, {crop_y}) 大小 {crop_size}x{crop_size}")
    avatar = avatar.cropped(x1=crop_x, y1=crop_y, x2=crop_x + crop_size, y2=crop_y + crop_size)
    
    target_avatar_size = int(VideoConfig.WIDTH * AvatarConfig.SCALE_RATIO)
    print(f"   📏 縮放至：{target_avatar_size}x{target_avatar_size}")
    avatar = avatar.resized((target_avatar_size, target_avatar_size))
    
    circle_mask = create_circle_mask(target_avatar_size)
    mask_clip = ImageClip(circle_mask, is_mask=True).with_duration(avatar.duration)
    mask_clip = mask_clip.with_fps(avatar.fps)
    avatar = avatar.with_mask(mask_clip)
    
    pos_x = VideoConfig.WIDTH - target_avatar_size - AvatarConfig.MARGIN_X
    pos_y = VideoConfig.HEIGHT - target_avatar_size - AvatarConfig.MARGIN_Y
    print(f"   📍 定位：({pos_x}, {pos_y})")
    
    avatar = avatar.with_position((pos_x, pos_y))
    
    if avatar.duration > base_duration:
        print(f"   ✂️  裁切 Avatar：{avatar.duration:.2f}s → {base_duration:.2f}s")
        avatar = avatar.subclipped(0, base_duration)
    elif avatar.duration < base_duration:
        print(f"   ℹ️  Avatar 較短（{avatar.duration:.2f}s），將在 {avatar.duration:.2f}s 後消失")
    
    return avatar


def render_final_video(base_track, avatar_overlay, subtitle_clips: list, output_path: Path):
    """最終合成與渲染"""
    print(f"\n🎬 開始最終渲染...")
    print(f"   📊 影片長度：{base_track.duration:.2f} 秒")
    print(f"   📝 字幕數量：{len(subtitle_clips)} 條")
    print(f"   📁 輸出位置：{output_path}")
    
    all_clips = [base_track, avatar_overlay] + subtitle_clips
    
    final = CompositeVideoClip(
        all_clips,
        size=(VideoConfig.WIDTH, VideoConfig.HEIGHT)
    )
    
    final.write_videofile(
        str(output_path),
        fps=VideoConfig.FPS,
        codec=VideoConfig.CODEC,
        audio_codec=VideoConfig.AUDIO_CODEC,
        threads=4,
        preset=VideoConfig.PRESET
    )
    
    final.close()
    base_track.close()
    avatar_overlay.close()
    for clip in subtitle_clips:
        clip.close()
    
    print(f"\n✅ 完成！影片已儲存至：{output_path}")


# ============================================================
# 引擎入口
# ============================================================
def run(folder_path: Path, output_path: Path):
    """
    MoviePy 引擎主入口
    
    Args:
        folder_path: 素材資料夾路徑
        output_path: 輸出影片路徑
    """
    print("\n🎬 使用 MoviePy 引擎")
    print("=" * 50)
    
    # 檢查 avatar 影片
    avatar_path = folder_path / FileNames.AVATAR_FILE
    if not avatar_path.exists():
        raise FileNotFoundError(f"找不到 Avatar 影片：{avatar_path}")
    
    # 檢查字幕檔案
    subtitle_path = folder_path / FileNames.SUBTITLE_FILE
    subtitles = []
    if subtitle_path.exists():
        print(f"📝 發現字幕檔案：{subtitle_path}")
        subtitles = parse_srt(subtitle_path)
        print(f"   ✅ 載入 {len(subtitles)} 條字幕")
    else:
        print(f"ℹ️  未發現字幕檔案，將不燒錄字幕")
    
    # 掃描素材
    print("\n🔍 掃描素材...")
    pairs = find_matching_pairs(folder_path)
    
    if not pairs:
        raise ValueError("找不到任何圖片/MP3 配對")
    
    print(f"   ✅ 找到 {len(pairs)} 組配對\n")
    
    # 拼接音檔
    merged_audio_path = folder_path / FileNames.MERGED_AUDIO
    concat_audio_with_ffmpeg(pairs, merged_audio_path)
    
    # 建立基礎軌
    print("\n🎞️  建立基礎軌...")
    base_track = build_base_track(pairs, merged_audio_path)
    
    # 建立 avatar 疊加層
    avatar_overlay = create_avatar_overlay(avatar_path, base_track.duration)
    
    # 建立字幕 clips
    subtitle_clips = []
    if subtitles:
        print("\n📝 建立字幕圖層...")
        subtitle_clips = create_subtitle_clips(subtitles, base_track.duration)
        print(f"   ✅ 成功建立 {len(subtitle_clips)} 個字幕片段")
    
    # 最終渲染
    render_final_video(base_track, avatar_overlay, subtitle_clips, output_path)
    
    # 清理暫存
    if merged_audio_path.exists():
        merged_audio_path.unlink()
        print(f"🧹 已清理暫存音檔")
