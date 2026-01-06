# 📚 Lessons Learned (開發經驗與教訓)

記錄開發過程中踩過的坑，避免後人（或未來的 AI）重蹈覆轍。

---

## 1. 字幕崩潰事件 (The Subtitle Collapse of Dec 2024)

**現象**：字幕時間戳出現 9 秒以上的單句持續時間，或者時間倒流。

**原因**：AI (Claude/GPT) 在斷句時偷偷改了文字順序（例如「關於...的故事」變成「故事關於...」），導致 Force Alignment 演算法找不到匹配字元，隨機抓取了錯誤的時間戳。

**解法**：
1. 升級模型至 `anthropic/claude-sonnet-4.5` (OpenRouter)
2. 實作「標點跳過演算法」

> [!IMPORTANT]
> **教訓**：永遠不要信任 LLM 會逐字輸出，必須在程式碼層級做容錯。

---

## 2. FFmpeg 的 `stdin` 陷阱

**現象**：Python 呼叫 FFmpeg 時程式卡死 (Hang)，不報錯也不結束。

**原因**：FFmpeg 預設在覆蓋檔案時會詢問 `Overwrite? [y/N]`，如果沒有加 `-y` 參數，它會卡在後台等待標準輸入。

**解法**：所有 FFmpeg 指令**必須**包含 `-y` 參數。

---

## 3. Avatar 座標不能亂動

**現象**：合成出的影片中，Avatar 被切頭、位置偏掉或擋住簡報重點。

**原因**：`config.py` 中的 Avatar 座標與遮罩 (Mask) 參數是針對特定解析度 (1080p) 精確調整過的。

**解法**：除非更換 Avatar 來源影片，否則**不要修改** `AVATAR_` 開頭的設定參數。

---

## 4. API 大小限制

**現象**：Whisper API 回傳 `413 Payload Too Large`。

**原因**：OpenAI Whisper API 限制檔案大小為 25MB。

**解法**：目前的 `_step1` 流程尚未實作自動切分。若遇到長音檔，需先用 `pydub` 等工具切分後再送出。

> [!NOTE]
> 這是已知限制，待未來版本實作。

---

## 5. 字幕亂碼

**現象**：生成的影片字幕顯示為方塊 `□ □ □`。

**原因**：系統找不到支援中文的字體。

**解法**：
1. 系統會自動偵測平台預設字體（macOS 用 PingFang，Windows 用微軟正黑體）
2. 如需自訂字體，設定環境變數 `FONT_PATH=/path/to/font.ttc`
3. Docker 環境須確保容器內有中文字體

---

## 6. Windows 路徑轉義事件 (Jan 2025)

**現象**：Windows 上執行影片合成時，FFmpeg 報錯 `Unable to parse option value as image size`。

**原因**：FFmpeg 的 `ass` 濾鏡對 Windows 路徑（含 `C:` 盤符）有特殊的轉義要求，直接使用 `as_posix()` 不夠。

**解法**：
1. 實作 `utils/platform_utils.py` 的 `escape_ffmpeg_filter_path()` 函數
2. 自動偵測平台，Windows 上額外轉義冒號和空格

> [!IMPORTANT]
> **教訓**：FFmpeg CLI 在不同 OS 上的行為差異比想像中大，應統一用抽象層處理。

---

## Quick Reference

| 問題類型 | 關鍵字 | 解決方向 |
|:--------|:------|:--------|
| 程式卡死 | FFmpeg hang | 加 `-y` 參數 |
| 時間戳錯亂 | 9秒字幕 | 標點跳過演算法 |
| 字幕亂碼 | □□□ | 檢查字體路徑 |
| 413 錯誤 | Whisper | 檔案過大，需切分 |
| Windows 路徑 | `C:` 報錯 | 用 `escape_ffmpeg_filter_path()` |
