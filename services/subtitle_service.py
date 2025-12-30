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
from integrations.openrouter_client import get_openrouter_client


class SubtitleService:
    """
    字幕生成服務
    
    流程：
    1. 從 Avatar 影片提取音軌
    2. Whisper 語音辨識（字級時間戳）
    3. Force Alignment（DTW 對齊修正錯字）
    4. AI 智慧斷句
    5. 時間戳對齊產生 SRT
    """
    
    # 檔案命名約定
    AVATAR_FILENAME = "avatar_full.mp4"
    EXTRACTED_AUDIO_FILENAME = "_extracted_audio.mp3"
    SCRIPT_FILENAME = "full_script.txt"
    SUBTITLE_FILENAME = "full_subtitle.srt"
    
    # Claude 字幕切片提示詞（貪婪匹配 + 視覺平衡）
    SEGMENTATION_PROMPT = """# Role
你是專業的字幕製作員。使用者會提供給你一段逐字稿，這段逐字稿已經經過預先處理，清除了所有特殊符號，僅保留必要的全形標點（，。？！）。

# Task
你的任務是將接收到的文字，嚴格遵守以下的「長度限制」與「語意優先原則」整理為適合閱讀的字幕格式。

# 重要原則（違反將導致系統崩潰）
- **嚴禁改寫**：你**只能進行斷行**，絕對不可新增、刪除、移動或修改任何文字（包括連接詞和語助詞）。
- **嚴禁調序**：所有字詞必須保持原稿的順序。
- **保留標點**：除了斷行可能需要的調整外，保留原稿標點。

# 處理邏輯（務必遵守）
## 大原則 - 字元計算方式
- **中文字/標點**：計為 1 個全形字元（例如：「你好。」= 3 字元）。
- **英文字母**：計為 0.5 個全形字元（例如：「Tom」= 1.5 字元）。
- **空白**：不計入字元數。

## 規則 1：安全長度內，絕對不換行
- 只要該段落的總長度（含標點符號） **≤ 20 個全形字元**，請保持原樣，直接輸出為一行。

## 規則 2：超過長度時，務必拆分
- 當段落總長度（含標點符號） **> 20 個全形字元** 時，請務必進行換行切分。
- **核心準則**：**語意完整性 > 視覺平衡**。切分後的每一行都必須是語意通順的詞組，**嚴禁**為了追求長度一致而切斷專有名詞或緊密關聯的詞組。

- **切分點決策流程（請依優先級執行）**：
    1.  **第一優先 - 標點符號**：
        優先尋找位於句子中間區域的標點符號（，、？！），並在符號**後方**進行換行。
    2.  **第二優先 - 語意邊界**：
        若無合適標點，必須在「語意停頓處」切分（例如：主詞與動詞之間、動詞與受詞之間）。
    3.  **第三優先 - 視覺平衡（僅作為輔助）**：
        只有當存在「多個」合理的語意切分點時，才選擇最接近「中間位置」的那一個。

- **例外處置**：
    若依據語意切分後，導致兩行長度懸殊（例如：上行 5 字，下行 22 字），**請保留此結果**，不可為了美觀強行將下行的字移至上行，語意正確最重要。

- **孤兒字防護**：
    除非該短句本身語意完整（例如：「我知道。」），否則拆分後的任何一行不應少於 4 個中文字。

# 範例對照
## 原稿（短句）
`今天天氣很好，我們去散步吧。`
### ❌ 錯誤輸出（不該拆分卻拆分）
今天天氣很好，
我們去散步吧。
### ✅ 正確輸出
今天天氣很好，我們去散步吧。

---
## 原稿（長句）
`Oracle 甲骨文這家讓人又愛又恨的軟體巨頭，終於發布了最新財報。`
### ❌ 錯誤輸出（該拆分卻沒拆）
Oracle 甲骨文這家讓人又愛又恨的軟體巨頭，終於發布了最新財報。
### ✅ 正確輸出
Oracle 甲骨文這家讓人又愛又恨的軟體巨頭
終於發布了最新財報。

# Output Format
- 請直接輸出最終的字幕文字。
- 經過拆分後的每一行文字，請獨立佔據一行。
- 嚴禁輸出任何解釋、編號、原文字數統計或 markdown 標記。"""
    
    def __init__(self):
        self.openai_client = get_openai_client()
        self.openrouter_client = get_openrouter_client()
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
        print("   Avatar 音軌提取 -> Whisper -> Force Align -> AI -> SRT")
        print("============================================================")
        print(f"📁 工作目錄：{folder_path}")
        
        try:
            # Step 0: 從 Avatar 影片提取音軌
            self._extract_audio(avatar_path, extracted_audio_path)
            
            # 載入逐字稿
            full_script = self._load_script(script_path)
            print(f"📝 原始逐字稿長度：{len(full_script)} 字")
            
            # Step 0.5: 符號清洗（確保 Step 2 和 Step 3 使用一致的文字）
            sanitized_script = self._sanitize_script(full_script)
            print(f"🧹 清洗後逐字稿長度：{len(sanitized_script)} 字")
            
            if debug:
                self._save_debug_text(folder_path / "_debug_sanitized_script.txt", [sanitized_script])
            
            # Step 1: Whisper 語音辨識
            whisper_timestamps = self._step1_transcribe_whisper(extracted_audio_path)
            
            if debug:
                self._save_debug_json(folder_path / "_debug_step1_whisper.json", whisper_timestamps)
            
            # Step 2: Force Alignment（使用清洗後的逐字稿）
            aligned_chars = self._step2_force_alignment(whisper_timestamps, sanitized_script)
            
            if debug:
                self._save_debug_json(folder_path / "_debug_step2_alignment.json", aligned_chars)
            
            # Step 3: Claude 文字切分（使用清洗後的逐字稿）
            subtitle_lines = self._step3_segment_text(sanitized_script)
            
            if debug:
                self._save_debug_text(folder_path / "_debug_step3_ai_segments.txt", subtitle_lines)
            
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
    
    def _sanitize_script(self, text: str) -> str:
        """
        符號清洗：確保 Alignment 和 Claude 斷句使用一致的文字
        
        清洗規則：
        1. 刪除：引號「」""、括號()、書名號《》
        2. 替換為逗號：頓號、、分號；
        3. 替換為空格：冒號：
        4. 刪除：破折號——、省略號……
        5. 中英文間加空格
        """
        # 1. 刪除引號、括號、書名號
        text = re.sub(r'[「」""()《》]', '', text)
        
        # 2. 頓號、分號 → 逗號
        text = text.replace('、', '，').replace('；', '，')
        
        # 3. 冒號 → 空格
        text = text.replace('：', ' ')
        
        # 4. 刪除破折號、省略號
        text = re.sub(r'——|……|\.{3,}', '', text)
        
        # 5. 中英文間加空格（英文/數字 ↔ 中文）
        text = re.sub(r'([a-zA-Z0-9])([^\x00-\x7F\s])', r'\1 \2', text)
        text = re.sub(r'([^\x00-\x7F])([a-zA-Z0-9])', r'\1 \2', text)
        
        # 清理多餘空格
        text = re.sub(r' +', ' ', text)
        
        return text
    
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
        """Step 3: AI 文字切分"""
        print("✂️  Step 3: AI 文字切分...")
        
        user_prompt = f"""請根據原稿的段落結構，將以下文字切分成字幕段落：

## 原稿
{transcript}

請輸出切分後的純文字（每行一段）。"""
        
        result = self.openrouter_client.chat_completion(
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
                # 跳過空格和標點，不參與匹配（修復 AI 新增標點導致的偏移累積）
                skip_chars = {' ', '，', '。', '、', '！', '？', '：', '；', '「', '」', '『', '』', '（', '）', ',', '.', '!', '?', ':', ';'}
                if char in skip_chars:
                    continue
                    
                found = False
                search_window = 100
                
                for k in range(min(search_window, total_chars - char_idx)):
                    # 跳過 aligned_chars 中的空格和標點
                    if aligned_chars[char_idx + k]["char"] in skip_chars:
                        continue
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
    
    def _save_debug_text(self, path: Path, lines: list):
        """儲存除錯用純文字檔（每行一段）"""
        with open(path, "w", encoding="utf-8") as f:
            for line in lines:
                f.write(line + "\n")
        print(f"   💾 除錯結果已儲存：{path}")

