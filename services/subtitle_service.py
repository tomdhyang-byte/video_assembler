"""
字幕生成服務
從 generate_subtitles.py 抽離的核心業務邏輯
"""

import os
import re
import json
import difflib
import subprocess
from pathlib import Path
from opencc import OpenCC

from integrations.openai_client import get_openai_client


class SubtitleService:
    """
    字幕生成服務
    
    流程：
    1. 從 Avatar 影片提取音軌
    2. Whisper 語音辨識（字級時間戳）
    3. Force Alignment（DTW 對齊修正錯字）
    4. GPT 智慧斷句
    5. 時間戳對齊產生 SRT
    """
    
    # 檔案命名約定
    AVATAR_FILENAME = "avatar_full.mp4"
    EXTRACTED_AUDIO_FILENAME = "_extracted_audio.mp3"
    SCRIPT_FILENAME = "full_script.txt"
    SUBTITLE_FILENAME = "full_subtitle.srt"
    
    # GPT 斷句提示詞
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

### 原稿
```
這是一個瘋狂的時代，風來了，連豬都會飛，但在我們開始今天的話題之前，我想問你一個很嚴肅的問題：當風停下來的時候，誰會最先掉下來摔死？沒錯，就是那隻豬。
```
字數分析：共 60+ 個國字，遠超 18，必須拆分成多行。

### 輸出
```
這是一個瘋狂的時代，
風來了，連豬都會飛，
但在我們開始今天的話題之前，
我想問你一個很嚴肅的問題：
當風停下來的時候，
誰會最先掉下來摔死？
沒錯，就是那隻豬。
```

## 輸出格式
- 每行一段字幕文字
- 不要輸出編號或時間戳
- 只輸出純文字
- 確保是繁體中文"""
    
    def __init__(self):
        self.openai_client = get_openai_client()
        self.cc = OpenCC('s2t')
    
    def generate(self, folder_path: Path, debug: bool = True) -> Path:
        """
        生成字幕的主入口
        
        Args:
            folder_path: 素材資料夾路徑
            debug: 是否儲存中間結果供除錯
            
        Returns:
            生成的 SRT 檔案路徑
        """
        folder_path = Path(folder_path)
        
        # 檔案路徑
        avatar_path = folder_path / self.AVATAR_FILENAME
        script_path = folder_path / self.SCRIPT_FILENAME
        output_path = folder_path / self.SUBTITLE_FILENAME
        extracted_audio_path = folder_path / self.EXTRACTED_AUDIO_FILENAME
        
        # 驗證必要檔案
        self._validate_files(avatar_path, script_path)
        
        print("============================================================")
        print("🎙️  字幕生成服務")
        print("   Avatar 音軌提取 -> Whisper -> Force Align -> GPT -> SRT")
        print("============================================================")
        print(f"📁 工作目錄：{folder_path}")
        
        try:
            # Step 0: 從 Avatar 影片提取音軌
            self._extract_audio(avatar_path, extracted_audio_path)
            
            # 載入逐字稿
            full_script = self._load_script(script_path)
            print(f"📝 逐字稿長度：{len(full_script)} 字")
            
            # Step 1: Whisper 語音辨識
            whisper_timestamps = self._step1_transcribe_whisper(extracted_audio_path)
            
            if debug:
                self._save_debug_json(folder_path / "_debug_step1_whisper.json", whisper_timestamps)
            
            # Step 2: Force Alignment
            aligned_chars = self._step2_force_alignment(whisper_timestamps, full_script)
            
            if debug:
                self._save_debug_json(folder_path / "_debug_step2_alignment.json", aligned_chars)
            
            # Step 3: GPT 文字切分
            subtitle_lines = self._step3_segment_text(full_script)
            
            # Step 4: 時間戳對齊
            final_subtitles = self._step4_align_timestamps(subtitle_lines, aligned_chars)
            
            # 儲存 SRT
            self._save_srt(final_subtitles, output_path)
            
            print("============================================================")
            
            return output_path
            
        finally:
            # 清理暫存的提取音檔
            if extracted_audio_path.exists():
                extracted_audio_path.unlink()
                print("   🗑️  已清理暫存音檔")
    
    def _validate_files(self, avatar_path: Path, script_path: Path):
        """驗證必要檔案存在"""
        if not avatar_path.exists():
            raise FileNotFoundError(f"找不到 Avatar 影片：{avatar_path}")
        if not script_path.exists():
            raise FileNotFoundError(f"找不到逐字稿：{script_path}")
    
    def _extract_audio(self, video_path: Path, output_path: Path) -> Path:
        """從 Avatar 影片提取音軌"""
        print("\n🔊 從 Avatar 影片提取音軌...")
        
        result = subprocess.run([
            'ffmpeg', '-y',
            '-i', str(video_path),
            '-vn',
            '-acodec', 'libmp3lame',
            '-q:a', '2',
            str(output_path)
        ], capture_output=True, text=True)
        
        if result.returncode != 0:
            print(f"⚠️  FFmpeg 警告：{result.stderr[-500:] if result.stderr else 'unknown'}")
        
        print(f"   ✅ 音軌提取完成：{output_path}")
        return output_path
    
    def _load_script(self, script_path: Path) -> str:
        """讀取並標準化逐字稿"""
        with open(script_path, "r", encoding="utf-8") as f:
            content = f.read()
        content = content.replace("\r\n", "\n").replace("\r", "\n")
        return content
    
    def _step1_transcribe_whisper(self, audio_path: Path) -> list:
        """Step 1: Whisper 語音辨識"""
        print("🚀 開始 Step 1: Whisper API 語音辨識...")
        print("   正在上傳音訊至 OpenAI...")
        
        response = self.openai_client.transcribe_audio(audio_path)
        
        print(f"   API 回傳成功 (Duration: {response.duration:.2f}s)")
        
        word_timestamps = []
        if hasattr(response, 'words'):
            for word_obj in response.words:
                word_timestamps.append({
                    "word": self.cc.convert(word_obj.word.strip()),
                    "start": word_obj.start,
                    "end": word_obj.end
                })
        else:
            print("   ⚠️  警告：API 未回傳詳細字級時間戳")
        
        print(f"   ✅ 取得 {len(word_timestamps)} 個字級時間戳")
        return word_timestamps
    
    def _step2_force_alignment(self, whisper_timestamps: list, full_script: str) -> list:
        """Step 2: Force Alignment (DTW 對齊)"""
        print("🔧 Step 2: 執行 Force Alignment (時間戳對齊)...")
        
        # 準備 Whisper 的字元列表
        whisper_chars = []
        for w in whisper_timestamps:
            for char in w["word"]:
                whisper_chars.append({"char": char, "start": w["start"], "end": w["end"]})
        
        # 準備 Script 的字元列表
        script_chars = list(full_script.replace("\n", ""))
        
        whisper_str = "".join([x["char"] for x in whisper_chars])
        script_str = "".join(script_chars)
        
        # 使用 difflib 進行序列比對
        matcher = difflib.SequenceMatcher(None, whisper_str, script_str, autojunk=False)
        
        aligned_results = []
        current_time = 0.0
        if whisper_chars:
            current_time = whisper_chars[0]["start"]
        
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == 'equal':
                for k in range(j2 - j1):
                    w_char = whisper_chars[i1 + k]
                    aligned_results.append({
                        "char": script_str[j1 + k],
                        "start": w_char["start"],
                        "end": w_char["end"]
                    })
                    current_time = w_char["end"]
                    
            elif tag == 'replace':
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
                if i2 > i1:
                    current_time = whisper_chars[i2-1]["end"]
                
            elif tag == 'insert':
                for k in range(j2 - j1):
                    aligned_results.append({
                        "char": script_str[j1 + k],
                        "start": current_time,
                        "end": current_time
                    })
        
        print(f"   ✅ Force Alignment 完成 (共 {len(aligned_results)} 個字元)")
        return aligned_results
    
    def _step3_segment_text(self, transcript: str) -> list:
        """Step 3: GPT 文字切分"""
        print("✂️  Step 3: GPT 文字切分...")
        
        user_prompt = f"""請根據原稿的段落結構，將以下文字切分成字幕段落：

## 原稿
{transcript}

請輸出切分後的純文字（每行一段）。"""
        
        result = self.openai_client.chat_completion(
            system_prompt=self.SEGMENTATION_PROMPT,
            user_prompt=user_prompt
        )
        
        # 清理結果
        result = re.sub(r'^```\n?', '', result)
        result = re.sub(r'\n?```$', '', result)
        
        lines = [line.strip() for line in result.strip().split('\n') if line.strip()]
        
        print(f"   ✅ 切分完成")
        print(f"   📝 切分為 {len(lines)} 行")
        return lines
    
    def _step4_align_timestamps(self, subtitle_lines: list, aligned_chars: list) -> list:
        """Step 4: 時間戳對齊"""
        print("⏱️  Step 4: Python 字幕對齊...")
        
        final_subtitles = []
        char_idx = 0
        total_chars = len(aligned_chars)
        
        matched_count = 0
        fallback_count = 0
        total_script_chars = sum(len(line.replace("\n", "").replace("\r", "")) for line in subtitle_lines)
        
        current_time = aligned_chars[0]["start"] if aligned_chars else 0.0
        
        for line in subtitle_lines:
            line_clean = line.replace("\n", "").replace("\r", "")
            if not line_clean:
                continue
                
            start_time = None
            end_time = None
            
            for char in line_clean:
                found = False
                search_window = 100
                
                for k in range(min(search_window, total_chars - char_idx)):
                    if aligned_chars[char_idx + k]["char"] == char:
                        found_idx = char_idx + k
                        item = aligned_chars[found_idx]
                        
                        if start_time is None:
                            start_time = item["start"]
                        
                        end_time = item["end"]
                        current_time = item["end"]
                        char_idx = found_idx + 1
                        found = True
                        matched_count += 1
                        break
                
                if not found:
                    fallback_count += 1
                    
                    if char_idx < total_chars:
                        item = aligned_chars[char_idx]
                        if start_time is None:
                            start_time = item["start"]
                        end_time = item["end"]
                        current_time = item["end"]
                        char_idx += 1
                    else:
                        if start_time is None:
                            start_time = current_time
                        end_time = current_time
            
            if start_time is not None:
                if end_time <= start_time:
                    end_time = start_time + 0.5
                
                final_subtitles.append({
                    "start": start_time,
                    "end": end_time,
                    "text": line
                })
        
        # 覆蓋率檢查
        if total_script_chars > 0:
            coverage = matched_count / total_script_chars
            print(f"   📊 對齊覆蓋率：{coverage:.1%} ({matched_count}/{total_script_chars} 字元)")
            
            if coverage < 0.8:
                print(f"   ⚠️  警告：覆蓋率低於 80%，字幕時間可能不夠精確！")
            
            if fallback_count > 0:
                print(f"   ℹ️  使用 fallback 時間的字元數：{fallback_count}")
        
        print("   ✅ 對齊完成")
        return final_subtitles
    
    def _format_timestamp(self, seconds: float) -> str:
        """將秒數轉換為 SRT 時間格式"""
        millis = int((seconds % 1) * 1000)
        seconds = int(seconds)
        minutes = seconds // 60
        hours = minutes // 60
        minutes %= 60
        seconds %= 60
        return f"{hours:02}:{minutes:02}:{seconds:02},{millis:03}"
    
    def _save_srt(self, subtitles: list, output_path: Path):
        """儲存 SRT 檔案"""
        with open(output_path, "w", encoding="utf-8") as f:
            for i, sub in enumerate(subtitles, 1):
                start = self._format_timestamp(sub["start"])
                end = self._format_timestamp(sub["end"])
                text = re.sub(r'[，。、；：,.]+$', '', sub["text"])
                f.write(f"{i}\n{start} --> {end}\n{text}\n\n")
        
        print(f"✅ 成功！字幕已儲存至：{output_path}")
        print(f"   共 {len(subtitles)} 行字幕")
    
    def _save_debug_json(self, path: Path, data):
        """儲存除錯用 JSON"""
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"   💾 除錯結果已儲存：{path}")
