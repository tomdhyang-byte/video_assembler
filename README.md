# 自動化簡報影片合成工具 (AutoVideoMaker)

這是一個自動化工具，用於將**語音檔 (MP3)** 與**簡報圖片 (JPG/PNG)** 結合成 1080p 影片，並自動疊加 **Avatar 解說影片**與**AI 生成的字幕**。

## 功能特色

*   **自動配對**：掃描資料夾中的同名 MP3 與圖片
*   **完美拼接**：使用 FFmpeg 無損拼接音訊
*   **全螢幕圖片**：自動將簡報圖片裁切填滿 16:9 畫面
*   **圓形 Avatar**：自動裁切人頭並套用圓形遮罩
*   **AI 字幕生成 (V7)**：
    *   Whisper 語音辨識取得精確字級時間戳
    *   Python Force Alignment（精準對齊逐字稿與時間戳）
    *   GPT 智慧斷句（每行 ≤18 字）
    *   精確時間對齊

## 環境需求

*   Python 3.12
*   FFmpeg
*   ImageMagick (`brew install imagemagick`)
*   OpenAI API Key

## 安裝

```bash
# 建立虛擬環境
python3.12 -m venv venv
source venv/bin/activate

# 安裝依賴
pip install moviepy numpy pillow faster-whisper opencc-python-reimplemented openai python-dotenv

# 設定 API Key
echo "OPENAI_API_KEY=your_key" > .env
```

## 使用流程

### Step 1：準備素材

```
素材資料夾/
├── 01.jpg              # 簡報圖片
├── 01.mp3              # 對應語音
├── 02.jpg
├── 02.mp3
├── ...
├── avatar_full.mp4     # Avatar 直式影片 (1080x1920)
├── full_audio.mp3      # 完整音訊 ← 你提供
└── full_script.txt     # 正確逐字稿 ← 你提供
```

### Step 2：生成字幕

```bash
python generate_subtitles.py
```

輸出：`full_subtitle.srt` ← 程式產出

### Step 3：合成影片

```bash
python batch_video_assembler.py
```

輸出：`~/Desktop/{資料夾名稱}.mp4` ← 程式產出（輸出至桌面）

## 檔案命名規範

### 你提供的素材

| 檔名 | 用途 |
|------|------|
| `full_audio.mp3` | 完整音訊（語音辨識用）|
| `full_script.txt` | 正確逐字稿（錯字校正用）|
| `avatar_full.mp4` | Avatar 直式影片 |
| `01.mp3`, `02.mp3`... | 切片音訊 |
| `01.jpg`, `02.jpg`... | 簡報圖片 |

### 程式產出的檔案

| 檔名 | 用途 |
|------|------|
| `full_subtitle.srt` | 最終字幕檔 |
| `{資料夾名稱}.mp4` | 最終輸出影片（桌面）|

## 技術架構 (V7)

```
generate_subtitles.py
│
├── Step 1: Whisper 語音辨識
│   └── 產出：字級時間戳 JSON
│
├── Step 2: Python Force Alignment
│   └── 輸入：時間戳 + 逐字稿 → 輸出：精確字元級時間戳
│
├── Step 3: GPT 文字切分
│   └── 輸入：逐字稿 → 輸出：純文字行列表（每行 ≤18 字）
│
└── Step 4: Python 時間戳對齊
    └── 輸入：文字行 + 時間戳 → 輸出：精確 SRT
```

## 參數調整

### Avatar 裁切 (`batch_video_assembler.py`)

```python
AVATAR_CROP_X = 200
AVATAR_CROP_Y = 550
AVATAR_CROP_SIZE = 650
AVATAR_SCALE_RATIO = 0.12
```

### 字幕樣式 (`batch_video_assembler.py`)

```python
SUBTITLE_STYLE = {
    "fontsize": 64,
    "color": "yellow",
    "stroke_color": "black",
    "stroke_width": 6,
    "font": "/System/Library/Fonts/PingFang.ttc",
}
SUBTITLE_CENTER_Y = 1000  # 字幕視覺中心 Y 座標
```

### 模型設定 (`generate_subtitles.py`)

```python
MODEL_SIZE = "small"         # Whisper: tiny/base/small/medium/large
OPENAI_MODEL = "gpt-4o-mini" # GPT 模型
```
