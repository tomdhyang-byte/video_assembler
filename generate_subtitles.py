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
from pathlib import Path
from dotenv import load_dotenv
from faster_whisper import WhisperModel
from openai import OpenAI
from opencc import OpenCC

# 載入環境變數
load_dotenv()

# 設定常數
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = "gpt-4o-mini"
OPENAI_TEMPERATURE = 0.3
WHISPER_MODEL_SIZE = "small"  # 可選 tiny, base, small, medium, large-v3

# 檔案命名約定
AUDIO_FILENAME = "full_audio.mp3"
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
    """讀取並標準化逐字稿"""
    if not script_path.exists():
        print(f"❌ 錯誤：找不到逐字稿 {script_path}")
        sys.exit(1)
    
    with open(script_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    # 統一換行符並轉繁體
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    return cc.convert(content)

# ============================================================
# 核心步驟
# ============================================================

def step1_transcribe_whisper(audio_path: Path) -> list:
    """Step 1: 使用 faster-whisper 進行語音辨識（獲取字級時間戳）"""
    print("🚀 開始 Step 1: Whisper 語音辨識...")
    print(f"   載入模型: {WHISPER_MODEL_SIZE} ...")
    
    try:
        model = WhisperModel(WHISPER_MODEL_SIZE, device="cpu", compute_type="int8")
        segments, info = model.transcribe(str(audio_path), word_timestamps=True, language="zh")
        
        print(f"   偵測到語言：{info.language} (機率 {info.language_probability:.2%})")
        
        word_timestamps = []
        for segment in segments:
            for word in segment.words:
                word_timestamps.append({
                    "word": cc.convert(word.word.strip()),
                    "start": word.start,
                    "end": word.end
                })
        
        print(f"   ✅ 取得 {len(word_timestamps)} 個字級時間戳")
        return word_timestamps
        
    except Exception as e:
        print(f"❌ Whisper 辨識失敗：{e}")
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
    """Step 4: 將切分好的字幕行與時間戳對齊"""
    print("⏱️  Step 4: Python 字幕對齊...")
    
    final_subtitles = []
    char_idx = 0
    total_chars = len(aligned_chars)
    
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
            search_window = 100 # 不要無限往後找
            
            for k in range(min(search_window, total_chars - char_idx)):
                if aligned_chars[char_idx + k]["char"] == char:
                    found_idx = char_idx + k
                    item = aligned_chars[found_idx]
                    
                    if start_time is None:
                        start_time = item["start"]
                    
                    # 持續更新 end_time 直到整句結束
                    end_time = item["end"]
                    
                    # 更新全域指針
                    char_idx = found_idx + 1
                    found = True
                    break
            
            if not found:
                # 找不到字(可能被 GPT 吃掉或改了標點)，就跳過該字
                pass
        
        if start_time is not None and end_time is not None:
             final_subtitles.append({
                "start": start_time,
                "end": end_time,
                "text": line
            })
            
    print("   ✅ 對齊完成")
    return final_subtitles

# ============================================================
# 主程式
# ============================================================
def main():
    print("============================================================")
    print("🎙️  AI 自動字幕生成器 V7 (Force Alignment 版)")
    print("   Whisper -> Force Align -> GPT Segment -> Python Align")
    print("============================================================")
    
    # 預設路徑 (方便測試)
    default_path = "/Users/a01-0218-0512/Downloads/nvdia_jay"
    user_input = input(f"📂 請輸入包含 'full_audio.mp3' 的資料夾路徑 (預設: {default_path})：").strip()
    
    if not user_input:
        folder_path = default_path
    else:
        folder_path = user_input.strip('"').strip("'")

    work_dir = normalize_path(folder_path)
    if not work_dir.exists():
        print(f"❌ 找不到路徑：{work_dir}")
        return

    print(f"📁 工作目錄：{work_dir}")
    
    audio_path = work_dir / AUDIO_FILENAME
    script_path = work_dir / SCRIPT_FILENAME
    output_path = work_dir / SUBTITLE_FILENAME
    
    if not audio_path.exists():
        print(f"❌ 找不到音訊檔案：{audio_path}")
        return
    if not script_path.exists():
        print(f"❌ 找不到逐字稿：{script_path}")
        return

    # Loading Script
    full_script = load_script(script_path)
    print(f"📝 逐字稿長度：{len(full_script)} 字")

    # Step 1: Whisper
    whisper_timestamps = step1_transcribe_whisper(audio_path)
    
    # Step 2: Force Alignment
    aligned_chars = step2_force_alignment(whisper_timestamps, full_script)
    
    # Step 3: Segmentation
    subtitle_lines = step3_segment_text(full_script, client)
    
    # Step 4: Final Alignment
    final_subtitles = step4_align_timestamps(subtitle_lines, aligned_chars)
    
    # Save
    save_srt(final_subtitles, output_path)
    print("============================================================")

if __name__ == "__main__":
    main()
