"""
AutoVideoMaker WebAPI
FastAPI 應用入口
"""

import sys
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# 確保專案根目錄在 Python 路徑中
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from api.routes import router
from utils.platform_utils import validate_ffmpeg_installed, get_default_font_path, get_platform

# 啟動時環境檢查
print(f"🖥️  Platform: {get_platform()}")
print(f"🔤 Font: {get_default_font_path()}")

if not validate_ffmpeg_installed():
    print("⚠️  Warning: FFmpeg not found in PATH! Video processing will fail.")

# 建立 FastAPI 應用
app = FastAPI(
    title="AutoVideoMaker API",
    description="""
    自動化簡報影片生成 API
    
    ## 功能
    - 從 Google Drive 下載素材
    - AI 自動生成字幕（Whisper + GPT）
    - 合成 16:9 簡報影片（FFmpeg）
    - 上傳結果到 Google Drive
    - 透過 Webhook 通知 Make.com
    
    ## 使用流程
    1. 呼叫 `/api/process-video` 提交處理請求
    2. API 立即返回 `job_id`
    3. 背景處理完成後，透過 `callback_url` 發送 Webhook
    """,
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS 設定（允許 Make.com 等外部服務呼叫）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生產環境應限制來源
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 註冊路由
app.include_router(router, prefix="/api", tags=["Video Processing"])


@app.get("/")
async def root():
    """API 根路徑"""
    return {
        "message": "AutoVideoMaker API",
        "docs": "/docs",
        "health": "/api/health"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )
