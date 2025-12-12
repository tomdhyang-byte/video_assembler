# 自動化簡報影片合成工具 (AutoVideoMaker)

這是一個自動化工具，用於將**語音檔 (MP3)** 與**簡報圖片 (JPG/PNG)** 結合成 1080p 影片，並自動疊加去背後的 **Avatar 解說影片**。

## 功能特色

*   **自動配對**：自動掃描資料夾中的同名 MP3 與圖片（如 `01.mp3` + `01.jpg`）。
*   **完美拼接**：使用 FFmpeg 無損拼接音訊，確保無雜音。
*   **全螢幕圖片**：自動將簡報圖片裁切填滿 16:9 畫面（無黑邊）。
*   **圓形 Avatar**：自動從直式影片中裁切出人頭，套用圓形遮罩，並定位於右下角。

## 環境需求

*   Python 3.8+
*   FFmpeg (必須安裝並設為系統環境變數)

## 安裝

1. 建立並啟動虛擬環境：
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

2. 安裝 Python 依賴：
   ```bash
   pip install moviepy numpy pillow
   ```

## 使用方法

1. 準備素材資料夾，結構如下：
   ```
   素材資料夾/
   ├── 01.jpg          # 簡報圖片 1
   ├── 01.mp3          # 對應語音 1
   ├── 02.jpg
   ├── 02.mp3
   ├── ...
   └── avatar_full_silent.mp4  # 無聲的直式 Avatar 影片 (1080x1920)
   ```

2. 執行程式：
   ```bash
   python batch_video_assembler.py
   ```

3. 依照提示輸入**素材資料夾路徑**。

## 參數調整

如果更換了 Avatar 影片，可能需要調整 `batch_video_assembler.py` 中的裁切參數：

```python
# Avatar 裁切設定（針對 1080x1920 直式影片）
AVATAR_CROP_X = 200       # 水平位置（往右移讓人頭居中）
AVATAR_CROP_Y = 550       # 垂直位置（從上方略過空白處）
AVATAR_CROP_SIZE = 650    # 正方形大小（剛好包住人頭）

# 縮放比例
AVATAR_SCALE_RATIO = 0.12 # Avatar 佔畫面寬度的 12%
```
