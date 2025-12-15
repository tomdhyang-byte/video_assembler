#!/usr/bin/env python3
"""
FFmpeg 引擎 - 使用純 FFmpeg 命令進行影片合成
高效能版本，適合長影片處理
"""

import os
import subprocess
import tempfile
import re
from pathlib import Path
from typing import List, Tuple

from config import (
    VideoConfig,
    SubtitleConfig,
    AvatarConfig,
    FileNames,
    IGNORE_FILES
)


# ============================================================
# 工具函數
# ============================================================
def find_matching_pairs(folder: Path) -> List[Tuple[str, Path, Path]]:
    """掃描資料夾，找出 PNG/JPG 與 MP3 的配對"""
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
    for key in sorted(common_keys):
        pairs.append((key, image_files[key], mp3_files[key]))
    
    unmatched_images = set(image_files.keys()) - common_keys
    unmatched_mp3 = set(mp3_files.keys()) - common_keys
    
    if unmatched_images:
        print(f"⚠️  警告：以下圖片檔案沒有對應的 MP3：{sorted(unmatched_images)}")
    if unmatched_mp3:
        print(f"⚠️  警告：以下 MP3 檔案沒有對應的圖片：{sorted(unmatched_mp3)}")
    
    return pairs


def get_audio_duration(audio_path: Path) -> float:
    """使用 ffprobe 取得音訊長度"""
    result = subprocess.run([
        'ffprobe', '-v', 'error',
        '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1',
        str(audio_path)
    ], capture_output=True, text=True)
    return float(result.stdout.strip())


def get_video_duration(video_path: Path) -> float:
    """使用 ffprobe 取得影片長度"""
    result = subprocess.run([
        'ffprobe', '-v', 'error',
        '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1',
        str(video_path)
    ], capture_output=True, text=True)
    return float(result.stdout.strip())


# ============================================================
# SRT → ASS 轉換
# ============================================================
def parse_srt(srt_path: Path) -> list:
    """解析 SRT 字幕檔案"""
    with open(srt_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    pattern = r"(\d+)\n(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})\n(.+?)(?=\n\n|\n*$)"
    matches = re.findall(pattern, content, re.DOTALL)
    
    subtitles = []
    for match in matches:
        idx, start_str, end_str, text = match
        subtitles.append({
            "start": start_str.replace(",", "."),  # ASS 用點號
            "end": end_str.replace(",", "."),
            "text": text.strip().replace("\n", "\\N")  # ASS 換行符
        })
    
    return subtitles


def generate_ass_file(srt_path: Path, ass_path: Path):
    """
    將 SRT 轉換為 ASS 格式
    ASS 可以精確控制字體、顏色、位置
    """
    subtitles = parse_srt(srt_path)
    
    # 計算 MarginV（垂直邊距）
    # ASS 的 alignment=2 是底部置中
    # MarginV 是從底部算起的距離
    margin_v = VideoConfig.HEIGHT - SubtitleConfig.CENTER_Y - (SubtitleConfig.FONT_SIZE // 2)
    
    # ASS 顏色格式：&HBBGGRR（BGR 順序，不是 RGB）
    def color_to_ass(color_name: str) -> str:
        colors = {
            "yellow": "&H00FFFF",
            "white": "&HFFFFFF",
            "black": "&H000000",
            "red": "&H0000FF",
        }
        return colors.get(color_name.lower(), "&HFFFFFF")
    
    primary_color = color_to_ass(SubtitleConfig.COLOR)
    outline_color = color_to_ass(SubtitleConfig.STROKE_COLOR)
    
    # ASS 檔案頭
    ass_content = f"""[Script Info]
Title: Auto Generated Subtitles
ScriptType: v4.00+
PlayResX: {VideoConfig.WIDTH}
PlayResY: {VideoConfig.HEIGHT}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,PingFang TC,{SubtitleConfig.FONT_SIZE},{primary_color},&H000000FF,{outline_color},&H00000000,-1,0,0,0,100,100,0,0,1,{SubtitleConfig.STROKE_WIDTH},0,2,10,10,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    
    # 添加字幕事件
    for sub in subtitles:
        # 時間格式轉換：00:00:01.500 → 0:00:01.50
        def convert_time(t: str) -> str:
            parts = t.split(":")
            h = int(parts[0])
            m = parts[1]
            s = parts[2][:5]  # 只取到小數點後兩位
            return f"{h}:{m}:{s}"
        
        start = convert_time(sub["start"])
        end = convert_time(sub["end"])
        text = sub["text"]
        
        ass_content += f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}\n"
    
    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(ass_content)
    
    print(f"   ✅ ASS 字幕生成完成：{ass_path}")
    return ass_path


# ============================================================
# FFmpeg 影片處理
# ============================================================
def create_segment_videos(pairs: list, temp_dir: Path) -> List[Path]:
    """
    為每個圖片+音訊配對創建影片片段
    """
    segments = []
    
    for idx, (seq, image_path, mp3_path) in enumerate(pairs, 1):
        print(f"   📄 處理中 [{idx}/{len(pairs)}]: {seq}{image_path.suffix} + {seq}.mp3")
        
        duration = get_audio_duration(mp3_path)
        output_segment = temp_dir / f"segment_{seq}.mp4"
        
        # FFmpeg: 圖片 → 影片（帶音訊）
        cmd = [
            'ffmpeg', '-y',
            '-loop', '1',
            '-i', str(image_path),
            '-i', str(mp3_path),
            '-c:v', VideoConfig.CODEC,
            '-tune', 'stillimage',
            '-c:a', VideoConfig.AUDIO_CODEC,
            '-b:a', '192k',
            '-vf', f'scale={VideoConfig.WIDTH}:{VideoConfig.HEIGHT}:force_original_aspect_ratio=increase,crop={VideoConfig.WIDTH}:{VideoConfig.HEIGHT}',
            '-pix_fmt', 'yuv420p',
            '-shortest',
            '-t', str(duration),
            str(output_segment)
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"⚠️  FFmpeg 警告：{result.stderr[-300:] if result.stderr else 'unknown'}")
        
        segments.append(output_segment)
    
    return segments


def concat_segments(segments: List[Path], output_path: Path):
    """使用 FFmpeg concat demuxer 串接影片片段"""
    print("\n   🔗 正在串接所有片段...")
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        for seg in segments:
            f.write(f"file '{seg}'\n")
        filelist_path = f.name
    
    try:
        cmd = [
            'ffmpeg', '-y',
            '-f', 'concat', '-safe', '0',
            '-i', filelist_path,
            '-c', 'copy',
            str(output_path)
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"⚠️  FFmpeg 串接警告：{result.stderr[-300:] if result.stderr else 'unknown'}")
        
        print(f"   ✅ 片段串接完成")
        
    finally:
        os.unlink(filelist_path)


def create_avatar_overlay_video(avatar_path: Path, duration: float, temp_dir: Path) -> Path:
    """
    處理 Avatar 影片：裁切 → 縮放 → 圓形遮罩
    使用 geq 濾鏡創建圓形遮罩
    """
    print(f"\n👤 處理 Avatar 影片...")
    
    crop_x = AvatarConfig.CROP_X
    crop_y = AvatarConfig.CROP_Y
    crop_size = AvatarConfig.CROP_SIZE
    target_size = int(VideoConfig.WIDTH * AvatarConfig.SCALE_RATIO)
    
    pos_x = VideoConfig.WIDTH - target_size - AvatarConfig.MARGIN_X
    pos_y = VideoConfig.HEIGHT - target_size - AvatarConfig.MARGIN_Y
    
    print(f"   ✂️  裁切區域：({crop_x}, {crop_y}) 大小 {crop_size}x{crop_size}")
    print(f"   📏 縮放至：{target_size}x{target_size}")
    print(f"   📍 定位：({pos_x}, {pos_y})")
    
    output_avatar = temp_dir / "avatar_processed.mov"
    
    avatar_duration = get_video_duration(avatar_path)
    actual_duration = min(avatar_duration, duration)
    
    if avatar_duration < duration:
        print(f"   ℹ️  Avatar 較短（{avatar_duration:.2f}s），將在 {avatar_duration:.2f}s 後消失")
    
    # FFmpeg 複雜濾鏡：裁切 → 縮放 → 圓形遮罩（使用 geq 濾鏡）
    # geq 濾鏡計算每個像素到中心的距離，超出半徑則透明
    radius = target_size // 2
    center = target_size // 2
    
    # 使用 format=rgba 和 geq 來創建圓形遮罩
    filter_complex = (
        f"crop={crop_size}:{crop_size}:{crop_x}:{crop_y},"
        f"scale={target_size}:{target_size},"
        f"format=rgba,"
        f"geq=lum='p(X,Y)':a='if(gt(sqrt(pow(X-{center},2)+pow(Y-{center},2)),{radius}),0,255)'"
    )
    
    cmd = [
        'ffmpeg', '-y',
        '-i', str(avatar_path),
        '-vf', filter_complex,
        '-c:v', 'qtrle',  # QuickTime Animation codec 支援 RGBA
        '-t', str(actual_duration),
        '-an',  # 無音訊
        str(output_avatar)
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"⚠️  Avatar 處理警告：{result.stderr[-300:] if result.stderr else 'unknown'}")
        # 如果 geq 失敗，嘗試不使用圓形遮罩的備用方案
        print("   ⚠️  嘗試備用方案（無圓形遮罩）...")
        fallback_filter = (
            f"crop={crop_size}:{crop_size}:{crop_x}:{crop_y},"
            f"scale={target_size}:{target_size}"
        )
        fallback_cmd = [
            'ffmpeg', '-y',
            '-i', str(avatar_path),
            '-vf', fallback_filter,
            '-c:v', VideoConfig.CODEC,
            '-t', str(actual_duration),
            '-an',
            str(output_avatar)
        ]
        result = subprocess.run(fallback_cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"Avatar 處理失敗：{result.stderr[-300:]}")
    
    print(f"   ✅ Avatar 處理完成")
    return output_avatar


def composite_final_video(
    base_video: Path,
    avatar_video: Path,
    ass_path: Path,
    output_path: Path
):
    """
    最終合成：基礎軌 + Avatar 疊加 + 字幕燒錄
    """
    print(f"\n🎬 開始最終合成...")
    
    target_size = int(VideoConfig.WIDTH * AvatarConfig.SCALE_RATIO)
    pos_x = VideoConfig.WIDTH - target_size - AvatarConfig.MARGIN_X
    pos_y = VideoConfig.HEIGHT - target_size - AvatarConfig.MARGIN_Y
    
    # 構建濾鏡
    if ass_path and ass_path.exists():
        # 有字幕：疊加 Avatar + 燒錄字幕
        # 注意：ass 路徑需要轉義冒號和反斜線
        ass_escaped = str(ass_path).replace(":", "\\:").replace("\\", "/")
        filter_complex = (
            f"[0:v][1:v]overlay={pos_x}:{pos_y}:shortest=1[composited];"
            f"[composited]ass='{ass_escaped}'[out]"
        )
    else:
        # 無字幕：只疊加 Avatar
        filter_complex = f"[0:v][1:v]overlay={pos_x}:{pos_y}:shortest=1[out]"
    
    cmd = [
        'ffmpeg', '-y',
        '-i', str(base_video),
        '-i', str(avatar_video),
        '-filter_complex', filter_complex,
        '-map', '[out]',
        '-map', '0:a',
        '-c:v', VideoConfig.CODEC,
        '-preset', VideoConfig.PRESET,
        '-c:a', VideoConfig.AUDIO_CODEC,
        '-b:a', '192k',
        str(output_path)
    ]
    
    print(f"   📁 輸出位置：{output_path}")
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"⚠️  最終合成警告：{result.stderr[-500:] if result.stderr else 'unknown'}")
        raise RuntimeError(f"FFmpeg 合成失敗：{result.stderr[-500:]}")
    
    print(f"\n✅ 完成！影片已儲存至：{output_path}")


# ============================================================
# 引擎入口
# ============================================================
def run(folder_path: Path, output_path: Path):
    """
    FFmpeg 引擎主入口
    
    Args:
        folder_path: 素材資料夾路徑
        output_path: 輸出影片路徑
    """
    print("\n🚀 使用 FFmpeg 引擎（高效能模式）")
    print("=" * 50)
    
    # 檢查 avatar 影片
    avatar_path = folder_path / FileNames.AVATAR_FILE
    if not avatar_path.exists():
        raise FileNotFoundError(f"找不到 Avatar 影片：{avatar_path}")
    
    # 檢查字幕檔案
    subtitle_path = folder_path / FileNames.SUBTITLE_FILE
    ass_path = None
    if subtitle_path.exists():
        print(f"📝 發現字幕檔案：{subtitle_path}")
    else:
        print(f"ℹ️  未發現字幕檔案，將不燒錄字幕")
    
    # 掃描素材
    print("\n🔍 掃描素材...")
    pairs = find_matching_pairs(folder_path)
    
    if not pairs:
        raise ValueError("找不到任何圖片/MP3 配對")
    
    print(f"   ✅ 找到 {len(pairs)} 組配對")
    
    # 創建暫存目錄
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        
        # Step 1: 創建影片片段
        print("\n🎞️  建立影片片段...")
        segments = create_segment_videos(pairs, temp_path)
        
        # Step 2: 串接片段
        base_video = temp_path / "base_track.mp4"
        concat_segments(segments, base_video)
        
        base_duration = get_video_duration(base_video)
        print(f"   📊 基礎軌長度：{base_duration:.2f} 秒")
        
        # Step 3: 處理 Avatar
        avatar_processed = create_avatar_overlay_video(avatar_path, base_duration, temp_path)
        
        # Step 4: 生成 ASS 字幕
        if subtitle_path.exists():
            print("\n📝 轉換字幕格式...")
            ass_path = temp_path / FileNames.ASS_SUBTITLE
            generate_ass_file(subtitle_path, ass_path)
        
        # Step 5: 最終合成
        composite_final_video(base_video, avatar_processed, ass_path, output_path)
