# 🚨 關鍵演算法與邏輯 (`CRITICAL_LOGIC.md`)

此文件記錄專案中「牽一髮動全身」的核心邏輯。**修改這些部分前必須經過嚴格測試。**

## 1. 標點跳過演算法 (Punctuation Skipping)

位於 `services/subtitle_service.py` 的 `_step4_align_timestamps` 方法。

### 為什麼需要它？
AI (LLM) 在斷句時，經常會「自作聰明」地加入逗號、句號，或者調整空格。然而，我們的時間戳來源 (`aligned_chars`) 是基於 `sanitized_script`，兩者在標點上往往不一致。這會導致序列比對失敗，時間戳全面崩潰。

### 核心邏輯
定義了一個 `skip_chars` 集合：
```python
skip_chars = {
    ' ', '，', '。', '、', '！', '？', '：', '；', 
    '「', '」', '『', '』', '（', '）', 
    ',', '.', '!', '?', ':', ';'
}
```
在比對時，**如果 `char` 或 `aligned_char` 屬於此集合，無條件跳過，不移動 Pointer**。這保證了我們只比對「有意義的文字」。

> ⛔️ **禁止事項**：除非確定，否則不要從 `skip_chars` 中移除符號。

## 2. Force Alignment (DTW)

位於 `services/subtitle_service.py` 的 `_step2_force_alignment` 方法。

### 核心邏輯
使用 `difflib.SequenceMatcher` 來比對 Whisper 轉錄出的文字與正確的 `sanitized_script`。
- **原則**：以 `script` 為主。如果 Whisper 轉錄錯誤（聽錯字），我們保留 `script` 的正確文字，並「借用」Whisper 錯誤文字的時間戳。
- **目的**：保證字幕文字 100% 正確，同時擁有精確時間。

## 3. 嚴格指令遵循 (Strict Prompting)

位於 `services/subtitle_service.py` 的 `SEGMENTATION_PROMPT`。

### 核心邏輯
為了防止 AI 改寫內容，Prompt 包含了極端嚴格的負面約束：
- 「嚴禁改寫」
- 「嚴禁調序」
- 「嚴禁新增或刪除任何文字」

配合 **Claude 3.5 Sonnet** 模型使用效果最佳。若更換模型 (如 GPT-4)，可能需要重新調優 Prompt。
