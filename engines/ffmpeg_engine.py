#!/usr/bin/env python3
"""
FFmpeg 引擎 - 使用純 FFmpeg 命令進行影片合成
高效能版本，適合長影片處理
"""

import os
import subprocess
import tempfile
import re
import concurrent.futures
import threading
import time
from pathlib import Path
import wave  # 標準庫，用於讀取 WAV
import numpy as np
from typing import List, Tuple, Dict  # 更新 Type Hints

from config import (
    VideoConfig,
    ProcessingConfig,
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


def read_audio_data(audio_path: Path, target_sr: int = 8000) -> np.ndarray:
    """
    使用 ffmpeg 將音訊轉換為 raw wav 數據並讀取為 numpy array
    使用較低的採樣率 (8000Hz) 以加快計算速度，對於對齊來說已經足夠精確
    """
    # 使用 temp file 儲存轉換後的 wav
    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tf:
        temp_wav = str(tf.name)
    
    try:
        # 轉換為單聲道、16bit PCM、指定採樣率
        cmd = [
            'ffmpeg', '-y', '-v', 'error',
            '-i', str(audio_path),
            '-ac', '1',  # 單聲道
            '-ar', str(target_sr),  # 採樣率
            '-c:a', 'pcm_s16le',  # 16-bit PCM
            temp_wav
        ]
        subprocess.run(cmd, check=True)
        
        # 讀取 wav
        with wave.open(temp_wav, 'rb') as wf:
            n_frames = wf.getnframes()
            frames = wf.readframes(n_frames)
            # 轉換為 numpy array (int16)
            audio_data = np.frombuffer(frames, dtype=np.int16)
            # 正規化到 -1.0 ~ 1.0 (float32) 以便進行 FFT
            return audio_data.astype(np.float32) / 32768.0
            
    finally:
        if os.path.exists(temp_wav):
            os.unlink(temp_wav)


def find_audio_offset(main_audio: np.ndarray, segment_audio: np.ndarray, sr: int = 8000, start_hint: float = 0.0) -> float:
    """
    使用 FFT Cross-Correlation 找出 segment 在 main 中的開始時間
    """
    if len(segment_audio) > len(main_audio):
        return 0.0
        
    # 優化：只在 hint 附近搜尋？
    # 為了簡化，我們先對全域搜尋，但為了避免計算量過大或誤判，
    # 如果 main audio 真的很長 (例如 > 10分鐘)，可以考慮切片。
    # 目前 10 分鐘 8000Hz = 4.8M 點，FFT 應該還在幾秒內可完成。
    
    n = len(main_audio)
    
    # 填充 segment 到相同長度
    segment_padded = np.zeros(n, dtype=np.float32)
    segment_padded[:len(segment_audio)] = segment_audio
    
    # 使用 FFT 計算 Cross Correlation
    # Correlation = IFFT( FFT(Main) * Conj(FFT(Segment)) )
    # 注意：這計算的是 Circular Correlation
    
    f_main = np.fft.rfft(main_audio)
    f_seg = np.fft.rfft(segment_padded)
    
    # 計算 correlation (注意 conjugat)
    # 我們希望找到 segment 在 main 中的位置，這相當於滑動 segment
    # 實際上，標準的 correlation 是 sum(f * g)，這裡用頻域乘法
    corr = np.fft.irfft(f_main * np.conj(f_seg))
    
    # 找出最大值位置
    # 為了避免誤判，我們可以限制搜尋範圍在 hint 附近 (例如 +/- 10秒)
    hint_idx = int(start_hint * sr)
    window = int(10.0 * sr)  # +/- 10秒
    
    search_start = max(0, hint_idx - window // 2)
    search_end = min(n, hint_idx + window * 2) # 向後多找一點
    
    # 只在視窗內找最大值
    if search_start < search_end:
        peak_idx = search_start + np.argmax(corr[search_start:search_end])
    else:
        peak_idx = np.argmax(corr)
        
    return peak_idx / sr


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
def create_segment_videos(pairs: list, temp_dir: Path, durations: Dict[str, float]) -> List[Path]:
    """
    為每個圖片+音訊配對創建影片片段
    [平行處理版] 使用 ThreadPoolExecutor 平行生成，大幅加速
    """
    segments = [None] * len(pairs)
    total_segments = len(pairs)
    completed_count = 0
    print_lock = threading.Lock()
    
    start_time_all = time.time()
    
    def process_single_segment(item):
        nonlocal completed_count
        idx, (seq, image_path, mp3_path) = item
        
        target_duration = durations.get(seq, 0.0)
        
        # 安全檢查
        original_duration = get_audio_duration(mp3_path)
        if target_duration < original_duration:
            with print_lock:
                 print(f"      ⚠️  警告：[{seq}] 目標長度 ({target_duration:.2f}s) 小於原始音訊 ({original_duration:.2f}s)，將使用原始長度")
            target_duration = original_duration

        output_segment = temp_dir / f"segment_{seq}.mp4"
        
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
            '-af', 'apad', # 填充靜音，確保音訊長度跟上影片
            '-pix_fmt', 'yuv420p',
            # '-shortest', # 移除 -shortest，否則會把靜音裁掉導致搶拍
            '-t', str(target_duration),
            '-loglevel', 'error', # 減少日誌干擾
            str(output_segment)
        ]
        
        subprocess.run(cmd, capture_output=True, text=True)
        
        with print_lock:
            completed_count += 1
            # 簡易進度條
            percent = (completed_count / total_segments) * 100
            bar_length = 20
            filled_length = int(bar_length * completed_count // total_segments)
            bar = '█' * filled_length + '-' * (bar_length - filled_length)
            
            print(f"   ▕{bar}▏ {percent:5.1f}% | 完成片段: {seq} (持續: {target_duration:.2f}s)", end="\r")
            
        return idx, output_segment

    # 準備參數
    work_items = []
    for idx, (seq, image_path, mp3_path) in enumerate(pairs):
        work_items.append((idx, (seq, image_path, mp3_path)))
        
    # 平行執行 (Max Workers 由 config 決定)
    max_workers = ProcessingConfig.MAX_WORKERS
    print(f"   🚀 啟動平行處理 (Workers: {max_workers})...")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        results = list(executor.map(process_single_segment, work_items))
        
    print() # 換行
    
    # 按照原始順序重組
    for idx, path in results:
        segments[idx] = path
        
    elapsed = time.time() - start_time_all
    print(f"   ✅ 全部片段生成完成，耗時: {elapsed:.2f}s")
    
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
    original_avatar_path: Path,  # 新增：原始 Avatar 檔案（音訊來源）
    ass_path: Path,
    output_path: Path
):
    """
    最終合成：基礎軌 + Avatar 疊加 + 字幕燒錄
    音訊來源：使用原始 Avatar 影片的音軌 (Single Source of Truth)
    """
    print(f"\n🎬 開始最終合成...")
    
    target_size = int(VideoConfig.WIDTH * AvatarConfig.SCALE_RATIO)
    pos_x = VideoConfig.WIDTH - target_size - AvatarConfig.MARGIN_X
    pos_y = VideoConfig.HEIGHT - target_size - AvatarConfig.MARGIN_Y
    
    # 構建濾鏡
    if ass_path and ass_path.exists():
        # 有字幕：疊加 Avatar + 燒錄字幕
        # 跨平台路徑處理：使用 as_posix() 統一為正斜線，再轉義冒號
        ass_escaped = ass_path.as_posix().replace(":", "\\:")
        filter_complex = (
            f"[0:v][1:v]overlay={pos_x}:{pos_y}[composited];"  # 移除 shortest=1，讓長度跟隨最長的流（通常是音訊）
            f"[composited]ass='{ass_escaped}'[out]"
        )
    else:
        # 無字幕：只疊加 Avatar
        filter_complex = f"[0:v][1:v]overlay={pos_x}:{pos_y}[out]"
    
    cmd = [
        'ffmpeg', '-y',
        '-i', str(base_video),          # Input 0: 基礎視覺軌 (由片段拼接)
        '-i', str(avatar_video),        # Input 1: 處理後的圓形 Avatar (無聲)
        '-i', str(original_avatar_path),# Input 2: 原始 Avatar (取其音訊)
        '-filter_complex', filter_complex,
        '-map', '[out]',                # 影像來自濾鏡輸出
        '-map', '2:a',                  # 音訊來自原始 Avatar
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
    
    # Audio Fingerprinting Sync (音訊指紋對齊)
    print("\n🎧 正在進行 Audio Fingerprinting 對齊...")
    print("   載入 Avatar 音軌數據 (8000Hz)...")
    main_audio = read_audio_data(avatar_path, target_sr=8000)
    avatar_duration = len(main_audio) / 8000.0
    print(f"   📊 Avatar 音軌長度: {avatar_duration:.2f}s")
    
    exact_durations = {}
    current_hint = 0.0
    
    start_times = {} # 記錄每段的開始時間，用於計算 duration
    
    # 1. 找出所有片段的開始時間
    for idx, (seq, _, mp3_path) in enumerate(pairs):
        print(f"   🔍 對齊中 [{idx+1}/{len(pairs)}]: {seq}.mp3...", end="\r")
        seg_audio = read_audio_data(mp3_path, target_sr=8000)
        
        # 使用 FFT 找出精確位置
        start_time = find_audio_offset(main_audio, seg_audio, sr=8000, start_hint=current_hint)
        start_times[seq] = start_time
        
        # 更新 hint (下一段應該在這一段結束後)
        seg_duration = len(seg_audio) / 8000.0
        current_hint = start_time + seg_duration
        
    print("\n   ✅ 對齊完成，計算每張圖片精確持續時間...")
    
    # 2. 計算 duration = Next_Start - Current_Start
    # 【修正搶拍問題】使用「幀級精確計算 (Frame-Perfect Calculation)」
    # 避免浮點數秒數在轉為幀數時產生量化誤差累積 (Quantization Drift)
    
    sorted_pairs = pairs # pairs 已經按照 seq 排序過
    fps = VideoConfig.FPS
    
    for i in range(len(sorted_pairs)):
        current_seq = sorted_pairs[i][0]
        current_start = start_times[current_seq]
        
        # 將「秒數」轉換為絕對的「幀數位置」 (四捨五入)
        # F_start[n] = Round( T_start[n] * FPS )
        current_frame_start = int(round(current_start * fps))
        
        if i < len(sorted_pairs) - 1:
            next_seq = sorted_pairs[i+1][0]
            next_start = start_times[next_seq]
            next_frame_start = int(round(next_start * fps))
            
            # Duration_Frames = Next_Frame_Start - Current_Frame_Start
            # 這保證了所有片段加起來的總幀數，嚴格等於總時間對應的幀數，誤差為 0
            duration_frames = next_frame_start - current_frame_start
            
            # 轉回秒數給 FFmpeg 使用 (FFmpeg 會視為精確的幀數整數倍)
            duration = duration_frames / fps
            
            # 安全檢查
            if duration <= 0.1:
                print(f"   ⚠️  警告：片段 {current_seq} 計算出的持續時間異常 ({duration:.2f}s / {duration_frames} frames)，使用預設值")
                duration = get_audio_duration(sorted_pairs[i][2])
                
        else:
            # 最後一段：持續到 Avatar 結束
            # 同樣使用幀數計算
            avatar_frame_len = int(round(avatar_duration * fps))
            duration_frames = avatar_frame_len - current_frame_start
            
            duration = duration_frames / fps
            
            if duration <= 0:
                 duration = get_audio_duration(sorted_pairs[i][2])
        
        exact_durations[current_seq] = duration
        # print(f"      - {current_seq}: {duration:.2f}s (Start: {current_start:.2f}s)")

    # Create temporary directory for processing
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        
        # Step 1: 創建影片片段
        print("\n🎞️  建立影片片段 (使用精確對齊時間)...")
        segments = create_segment_videos(pairs, temp_path, exact_durations)
        
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
        composite_final_video(base_video, avatar_processed, avatar_path, ass_path, output_path)
