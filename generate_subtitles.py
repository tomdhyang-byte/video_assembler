#!/usr/bin/env python3
"""
AI 自動字幕生成器 V7 (Force Alignment 版)
Whisper 字級時間戳 -> Python 強制對齊 (修正錯字與時間) -> GPT 段落切分 -> Python 字幕對齊

主要功能：
1. 使用 faster-whisper 產生字級時間戳
2. 使用 difflib 將 Whisper 辨識結果與正確逐字稿強制對齊 (Force Alignment)
3. 使用 GPT-4o-mini 將正確逐字稿依語意和字數限制切分成字幕行
4. 將切分好的字幕行與對齊後的時間戳合併，產生 SRT
"""

import os
import sys
import json
import re
import difflib
import subprocess
from pathlib import Path
from dotenv import load_dotenv
# from faster_whisper import WhisperModel # 已移除
from openai import OpenAI
from opencc import OpenCC

# 載入環境變數
load_dotenv()

# 設定常數
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = "gpt-4o-mini"
OPENAI_TEMPERATURE = 0.3
# WHISPER_MODEL_SIZE = "medium"  # 已棄用，API 固定使用 whisper-1

# 檔案命名約定
AVATAR_FILENAME = "avatar_full.mp4"
EXTRACTED_AUDIO_FILENAME = "_extracted_audio.mp3"  # 從 avatar 提取的音軌
SCRIPT_FILENAME = "full_script.txt"
SUBTITLE_FILENAME = "full_subtitle.srt"

if not OPENAI_API_KEY:
    print("❌ 錯誤：未設定 OPENAI_API_KEY")
    sys.exit(1)

client = OpenAI(api_key=OPENAI_API_KEY)
# 初始化繁簡轉換 (雖主要依賴逐字稿，但在某此字串處理仍可能用到)
cc = OpenCC('s2t')


# ============================================================
# Step 3 Prompt: 文字切分（跟隨原稿段落結構 + 純字數規則）
# ============================================================
SEGMENTATION_PROMPT = """你是專業的字幕製作員。你的任務是將校正後的文字切分成適合字幕顯示的段落。

## 斷句邏輯（非常重要，請嚴格遵守）

### 規則 1：尊重原稿的段落結構
- 原稿中的每一個段落（以換行分隔）是獨立的處理單位
- 段落與段落之間是自然的分隔點，**必須換行**

### 規則 2：18 字原則（不含標點）
- 計算字數時，**忽略** 標點符號（，。？！：；「」等），只計算**國字/英文字母/數字**
- 如果一段文字的**純字數 ≤ 18**：**保持完整，不拆分**
- 如果一段文字的**純字數 > 18**：**必須拆分**

### 規則 3：拆分策略
- 如果必須拆分，優先在 **逗號（，）、頓號（、）** 後面斷開
- 如果沒有標點可斷，則在詞語邊界斷開
- 絕對不要在詞語中間斷開

## 範例

### 原稿
```
當風停下來的時候，誰會最先掉下來摔死？
```
字數分析：「當風停下來的時候誰會最先掉下來摔死」共 18 個國字。
判斷：≤ 18 字，不拆分。

### 輸出
```
當風停下來的時候，誰會最先掉下來摔死？
```

### 原稿
```
今天要跟親愛的 KQ 朋友們聊的這間公司，最近可是站在風口上的超級巨星
```
字數分析：共 30+ 個國字，超過 18，需拆分。

### 輸出
```
今天要跟親愛的 KQ 朋友們聊的這間公司，
最近可是站在風口上的超級巨星
```

## 輸出格式
- 每行一段字幕文字
- 不要輸出編號或時間戳
- 只輸出純文字
- 確保是繁體中文"""


# ============================================================
# 工具函數
# ============================================================
def normalize_path(input_path: str) -> Path:
    input_path = input_path.strip().strip('"').strip("'")
    return Path(input_path).expanduser().resolve()

def format_timestamp(seconds: float) -> str:
    """將秒數轉換為 SRT 時間格式 (HH:MM:SS,mmm)"""
    millis = int((seconds % 1) * 1000)
    seconds = int(seconds)
    minutes = seconds // 60
    hours = minutes // 60
    minutes %= 60
    seconds %= 60
    return f"{hours:02}:{minutes:02}:{seconds:02},{millis:03}"

def save_srt(subtitles: list, output_path: Path):
    """儲存 SRT 檔案"""
    with open(output_path, "w", encoding="utf-8") as f:
        for i, sub in enumerate(subtitles, 1):
            start = format_timestamp(sub["start"])
            end = format_timestamp(sub["end"])
            text = sub["text"]
            f.write(f"{i}\n{start} --> {end}\n{text}\n\n")
    print(f"✅ 成功！字幕已儲存至：{output_path}")
    print(f"   共 {len(subtitles)} 行字幕")

def load_script(script_path: Path) -> str:
    """讀取並標準化逐字稿（假設已是繁體中文，不做轉換）"""
    if not script_path.exists():
        print(f"❌ 錯誤：找不到逐字稿 {script_path}")
        sys.exit(1)
    
    with open(script_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    # 統一換行符（不做簡繁轉換，保留原始用字）
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    return content


def extract_audio_from_video(video_path: Path, output_path: Path) -> Path:
    """
    從 Avatar 影片提取音軌供 Whisper 使用
    確保字幕時間戳與 Avatar 對嘴完全一致（Single Source of Truth）
    """
    print("\n🔊 從 Avatar 影片提取音軌...")
    
    result = subprocess.run([
        'ffmpeg', '-y',
        '-i', str(video_path),
        '-vn',  # 不要影像
        '-acodec', 'libmp3lame',
        '-q:a', '2',  # 高品質
        str(output_path)
    ], capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"⚠️  FFmpeg 警告：{result.stderr[-500:] if result.stderr else 'unknown'}")
    
    print(f"   ✅ 音軌提取完成：{output_path}")
    return output_path

# ============================================================
# 核心步驟
# ============================================================

def step1_transcribe_whisper(audio_path: Path) -> list:
    """Step 1: 使用 OpenAI Whisper API 進行語音辨識（獲取字級時間戳）"""
    print("🚀 開始 Step 1: Whisper API 語音辨識...")
    print("   正在上傳音訊至 OpenAI...")
    
    try:
        with open(audio_path, "rb") as audio_file:
            response = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                language="zh",
                response_format="verbose_json",
                timestamp_granularities=["word"]
            )
        
        # API 回傳的是物件，需要轉為我們需要的格式
        # response.words 是一個 list of objects (word, start, end)
        
        print(f"   API 回傳成功 (Duration: {response.duration:.2f}s)")
        
        word_timestamps = []
        if hasattr(response, 'words'):
            for word_obj in response.words:
                word_timestamps.append({
                    "word": cc.convert(word_obj.word.strip()),
                    "start": word_obj.start,
                    "end": word_obj.end
                })
        else:
            # Fallback (雖不太可能，若沒 words 只有 text)
            print("   ⚠️  警告：API 未回傳詳細字級時間戳")
        
        print(f"   ✅ 取得 {len(word_timestamps)} 個字級時間戳")
        return word_timestamps
        
    except Exception as e:
        print(f"❌ Whisper API 辨識失敗：{e}")
        sys.exit(1)

def step2_force_alignment(whisper_timestamps: list, full_script: str) -> list:
    """Step 2: Force Alignment (Python)
    將 Whisper 的時間戳強制對齊到正確的逐字稿上。
    """
    print("🔧 Step 2: 執行 Force Alignment (時間戳對齊)...")
    
    # 為了最精確，我們採用「字元級」比對
    # 1. 準備 Whisper 的字元列表 (包含時間)
    whisper_chars = []
    for w in whisper_timestamps:
        for char in w["word"]:
            whisper_chars.append({"char": char, "start": w["start"], "end": w["end"]})
            
    # 2. 準備 Script 的字元列表 (不含換行，以便進行序列比對)
    # 但我們需要保留換行符的「位置感」，或者在對齊後能映射回去。
    # 最簡單的方法：只對齊實體字元，標點符號視為字元之一。
    # full_script 包含全部正確的字和標點
    
    script_chars = list(full_script.replace("\n", "")) 
    
    whisper_str = "".join([x["char"] for x in whisper_chars])
    script_str = "".join(script_chars)
    
    # 3. 使用 difflib 進行序列比對
    # autojunk=False 很重要，避免長字串被當作垃圾忽略
    matcher = difflib.SequenceMatcher(None, whisper_str, script_str, autojunk=False)
    
    aligned_results = []
    
    # 記錄正確文本目前處理到的時間進度
    current_time = 0.0
    if whisper_chars:
        current_time = whisper_chars[0]["start"]
        
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        # tag: replace, delete, insert, equal
        # whisper_str[i1:i2] vs script_str[j1:j2]
        
        if tag == 'equal':
            # 完全匹配：直接使用 Whisper 的時間
            # 對於標點符號，如果 Whisper 也有聽到(或輸出)，時間也會對
            for k in range(j2 - j1):
                w_char = whisper_chars[i1 + k]
                aligned_results.append({
                    "char": script_str[j1 + k],
                    "start": w_char["start"],
                    "end": w_char["end"]
                })
                current_time = w_char["end"]
                
        elif tag == 'replace':
            # 替換：Whisper 聽錯了，Script 是對的
            # 將 Whisper 這段的時間區間，平均分配給 Script 這段的字
            if i2 > i1:
                start_t = whisper_chars[i1]["start"]
                end_t = whisper_chars[i2-1]["end"]
            else:
                start_t = current_time
                end_t = current_time 
                
            duration = end_t - start_t
            num_script_chars = j2 - j1
            
            if num_script_chars > 0:
                char_duration = duration / num_script_chars
                for k in range(num_script_chars):
                    aligned_results.append({
                        "char": script_str[j1 + k],
                        "start": start_t + (k * char_duration),
                        "end": start_t + ((k + 1) * char_duration)
                    })
            current_time = end_t
            
        elif tag == 'delete':
            # 刪除：Whisper 多聽到了 (hallucination)，Script 沒有
            # 直接忽略這段 Whisper 的時間
            if i2 > i1:
                current_time = whisper_chars[i2-1]["end"]
            
        elif tag == 'insert':
            # 插入：Whisper 沒聽到，但 Script 有 (漏字)
            # 這些字沒有對應的時間，暫時擠在 current_time
             for k in range(j2 - j1):
                aligned_results.append({
                    "char": script_str[j1 + k],
                    "start": current_time,
                    "end": current_time
                })

    print(f"   ✅ Force Alignment 完成 (共 {len(aligned_results)} 個字元)")
    return aligned_results

def step3_segment_text(transcript: str, client: OpenAI) -> list:
    """Step 3: GPT 文字切分（根據原稿段落結構） - 只有切分，不涉及時間"""
    print("✂️  Step 3: GPT 文字切分...")
    
    user_prompt = f"""請根據原稿的段落結構，將以下文字切分成字幕段落：

## 原稿
{transcript}

請輸出切分後的純文字（每行一段）。"""

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            temperature=OPENAI_TEMPERATURE,
            messages=[
                {"role": "system", "content": SEGMENTATION_PROMPT},
                {"role": "user", "content": user_prompt}
            ]
        )
        
        result = response.choices[0].message.content
        result = re.sub(r'^```\n?', '', result)
        result = re.sub(r'\n?```$', '', result)
        
        lines = [line.strip() for line in result.strip().split('\n') if line.strip()]
        
        print(f"   ✅ 切分完成 (tokens: {response.usage.total_tokens})")
        print(f"   📝 切分為 {len(lines)} 行")
        return lines
        
    except Exception as e:
        print(f"❌ API 錯誤：{e}")
        sys.exit(1)

def step4_align_timestamps(subtitle_lines: list, aligned_chars: list) -> list:
    """Step 4: 將切分好的字幕行與時間戳對齊
    
    改進版：
    1. 找不到精確匹配時，使用「當前時間」繼續推進（不會漏字幕）
    2. 完成後檢查覆蓋率，低於 80% 時警告
    """
    print("⏱️  Step 4: Python 字幕對齊...")
    
    final_subtitles = []
    char_idx = 0
    total_chars = len(aligned_chars)
    
    # 統計用
    matched_count = 0
    fallback_count = 0
    total_script_chars = sum(len(line.replace("\n", "").replace("\r", "")) for line in subtitle_lines)
    
    # 取得基準時間（用於 fallback）
    current_time = aligned_chars[0]["start"] if aligned_chars else 0.0
    last_end_time = aligned_chars[-1]["end"] if aligned_chars else 0.0
    
    for line in subtitle_lines:
        line_clean = line.replace("\n", "").replace("\r", "")
        if not line_clean:
            continue
            
        start_time = None
        end_time = None
        
        # 尋找這行字幕的開始與結束時間
        for char in line_clean:
            # 貪婪匹配：在 aligned_chars 中尋找下一個匹配的字元
            found = False
            search_window = 100  # 不要無限往後找
            
            for k in range(min(search_window, total_chars - char_idx)):
                if aligned_chars[char_idx + k]["char"] == char:
                    found_idx = char_idx + k
                    item = aligned_chars[found_idx]
                    
                    if start_time is None:
                        start_time = item["start"]
                    
                    # 持續更新 end_time 直到整句結束
                    end_time = item["end"]
                    current_time = item["end"]
                    
                    # 更新全域指針
                    char_idx = found_idx + 1
                    found = True
                    matched_count += 1
                    break
            
            if not found:
                # 【修復延遲】找不到精確匹配時：
                # 1. 使用當前位置的時間（而非陳舊的 current_time）
                # 2. 推進 char_idx 避免卡住
                fallback_count += 1
                
                if char_idx < total_chars:
                    # 使用當前位置的時間
                    item = aligned_chars[char_idx]
                    if start_time is None:
                        start_time = item["start"]
                    end_time = item["end"]
                    current_time = item["end"]
                    # 【關鍵修復】推進指針，避免延遲累積
                    char_idx += 1
                else:
                    # 已經到達末尾，使用最後的時間
                    if start_time is None:
                        start_time = current_time
                    end_time = current_time
        
        # 【改進】即使只有 fallback 時間，也要產生字幕（不會漏）
        if start_time is not None:
            # 確保 end_time 至少比 start_time 大一點點
            if end_time <= start_time:
                end_time = start_time + 0.5
            
            final_subtitles.append({
                "start": start_time,
                "end": end_time,
                "text": line
            })
    
    # 【改進】覆蓋率檢查
    if total_script_chars > 0:
        coverage = matched_count / total_script_chars
        print(f"   📊 對齊覆蓋率：{coverage:.1%} ({matched_count}/{total_script_chars} 字元)")
        
        if coverage < 0.8:
            print(f"   ⚠️  警告：覆蓋率低於 80%，字幕時間可能不夠精確！")
            print(f"   ⚠️  建議檢查逐字稿與音訊是否匹配。")
        
        if fallback_count > 0:
            print(f"   ℹ️  使用 fallback 時間的字元數：{fallback_count}")
    
    print("   ✅ 對齊完成")
    return final_subtitles

# ============================================================
# 主程式
# ============================================================
def main():
    print("============================================================")
    print("🎙️  AI 自動字幕生成器 V9 (Avatar Audio 版)")
    print("   Avatar 音軌提取 -> Whisper -> Force Align -> GPT -> SRT")
    print("============================================================")
    
    # 預設路徑 (方便測試)
    default_path = "/Users/a01-0218-0512/Downloads/nvdia_jay"
    user_input = input(f"📂 請輸入素材資料夾路徑 (預設: {default_path})：").strip()
    
    if not user_input:
        folder_path = default_path
    else:
        folder_path = user_input.strip('"').strip("'")

    work_dir = normalize_path(folder_path)
    if not work_dir.exists():
        print(f"❌ 找不到路徑：{work_dir}")
        return

    print(f"📁 工作目錄：{work_dir}")
    
    avatar_path = work_dir / AVATAR_FILENAME
    script_path = work_dir / SCRIPT_FILENAME
    output_path = work_dir / SUBTITLE_FILENAME
    extracted_audio_path = work_dir / EXTRACTED_AUDIO_FILENAME
    
    # 檢查必要檔案
    if not avatar_path.exists():
        print(f"❌ 找不到 Avatar 影片：{avatar_path}")
        return
    if not script_path.exists():
        print(f"❌ 找不到逐字稿：{script_path}")
        return

    # 從 Avatar 影片提取音軌（Single Source of Truth）
    extract_audio_from_video(avatar_path, extracted_audio_path)

    # Loading Script
    full_script = load_script(script_path)
    print(f"📝 逐字稿長度：{len(full_script)} 字")

    # Step 1: Whisper（使用從 Avatar 提取的音軌）
    whisper_timestamps = step1_transcribe_whisper(extracted_audio_path)
    
    # 【偵錯】儲存 Step 1 結果
    step1_output_path = work_dir / "_debug_step1_whisper.json"
    with open(step1_output_path, "w", encoding="utf-8") as f:
        json.dump(whisper_timestamps, f, ensure_ascii=False, indent=2)
    print(f"   💾 Step 1 結果已儲存：{step1_output_path}")

    
    # Step 2: Force Alignment
    aligned_chars = step2_force_alignment(whisper_timestamps, full_script)
    
    # 【偵錯】儲存 Step 2 結果
    step2_output_path = work_dir / "_debug_step2_alignment.json"
    with open(step2_output_path, "w", encoding="utf-8") as f:
        json.dump(aligned_chars, f, ensure_ascii=False, indent=2)
    print(f"   💾 Step 2 結果已儲存：{step2_output_path}")
    
    # Step 3: Segmentation
    subtitle_lines = step3_segment_text(full_script, client)
    
    # Step 4: Final Alignment
    final_subtitles = step4_align_timestamps(subtitle_lines, aligned_chars)
    
    # Save
    save_srt(final_subtitles, output_path)
    
    # 清理暫存的提取音檔
    if extracted_audio_path.exists():
        extracted_audio_path.unlink()
        print("   🗑️  已清理暫存音檔")
    
    print("============================================================")

if __name__ == "__main__":
    main()
