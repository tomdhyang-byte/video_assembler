# 🏗️ 系統架構與模組職責 (`ARCHITECTURE.md`)

此文件定義了 AutoVideoMaker 的核心架構原則。未來的修改必須遵守這些邊界與職責。

## 1. 架構分層 (Layered Architecture)

系統嚴格遵循單向依賴原則：`API/CLI` -> `Services` -> `Integration/Engine`

```mermaid
graph TD
    subgraph "入口層 (Entry Layer)"
        API[WebAPI (FastAPI)]
        CLI[Command Line Interface]
    end
    
    subgraph "服務層 (Service Layer)"
        VP[VideoProcessor (Facade)]
        SS[SubtitleService]
        AS[AssemblyService]
    end
    
    subgraph "核心與整合層 (Core & Integration)"
        ENG[FFmpeg Engine]
        OAI[OpenAI Client]
        OR[OpenRouter Client]
        GD[Google Drive Client]
    end
    
    API --> VP
    CLI --> VP
    VP --> SS
    VP --> AS
    AS --> ENG
    SS --> OAI
    SS --> OR
```

## 2. 模組單一職責 (Single Responsibility)

| 模組 | 職責 (Do's) | 禁止事項 (Don'ts) |
|---|---|---|
| **api/routes.py** | 接收請求、驗證參數、發送 Webhook | 不要寫任何影片處理邏輯，不要直接呼叫 FFmpeg |
| **services/video_processor.py** | 流程控制 (Facade)、串接各個 Service | 不要包含具體的演算法實作 (如怎麼對齊時間戳) |
| **services/subtitle_service.py** | 生成 SRT 字幕、時間軸對齊 | 不要處理影片合成、不要處理音訊合併 |
| **services/assembly_service.py** | 準備素材清單、計算片段長度 | 不要執行實際的渲染指令 (交給 Engine) |
| **engines/ffmpeg_engine.py** | 執行 FFmpeg 指令、濾鏡處理 | 不要包含業務邏輯 (如判斷是否跳過字幕) |

## 3. 關鍵設計原則

1.  **Facade Pattern**: 外部 (API/CLI) 只能透過 `VideoProcessor` 操作系統，不應直接存取底層 Service。
2.  **Dependency Injection**: 雖然目前使用簡單的 `get_client()` 函數，但應保持 Client 的獨立性，方便未來 Mock 測試。
3.  **Stateless Clients**: `OpenAIClient` 和 `OpenRouterClient` 應保持無狀態設計，所有上下文由 Service 傳入。
