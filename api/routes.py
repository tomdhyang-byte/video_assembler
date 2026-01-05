"""
API 路由定義
"""

import uuid
import httpx
import tempfile
from pathlib import Path
from fastapi import APIRouter, BackgroundTasks, HTTPException

from .schemas import (
    VideoRequest, 
    VideoResponse, 
    WebhookPayload,
    JobStatus,
    HealthResponse
)
from services.video_processor import VideoProcessor
from integrations.google_drive import GoogleDriveClient

router = APIRouter()

# 任務狀態存儲（生產環境應使用 Redis）
jobs: dict = {}


def generate_job_id() -> str:
    """生成唯一的任務 ID"""
    return str(uuid.uuid4())[:8]


async def send_webhook(callback_url: str, payload: WebhookPayload):
    """發送 Webhook 通知到 Make.com"""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                callback_url,
                json=payload.model_dump(),
                timeout=30.0
            )
            print(f"📤 Webhook 發送成功：{response.status_code}")
        except Exception as e:
            print(f"❌ Webhook 發送失敗：{e}")


async def process_video_task(
    job_id: str,
    drive_folder_id: str,
    callback_url: str,
    skip_subtitle: bool = False
):
    """
    背景任務：處理影片
    
    流程：
    1. 從 Google Drive 下載素材資料夾
    2. 執行影片處理（字幕 + 合成）
    3. 將結果上傳回 Google Drive
    4. 發送 Webhook 通知
    """
    print(f"\n{'='*60}")
    print(f"🎬 開始處理任務：{job_id}")
    print(f"   Drive Folder ID: {drive_folder_id}")
    print(f"{'='*60}")
    
    jobs[job_id] = {"status": JobStatus.PROCESSING, "message": "處理中..."}
    
    try:
        # 初始化 Google Drive 客戶端
        drive = GoogleDriveClient()
        
        # 建立暫存目錄
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            local_folder = temp_path / "source"
            
            # Step 1: 從 Google Drive 下載素材
            jobs[job_id]["message"] = "正在從 Google Drive 下載素材..."
            drive.download_folder(drive_folder_id, local_folder)
            
            # Step 2: 處理影片（字幕 + 合成）
            jobs[job_id]["message"] = "正在處理影片..."
            processor = VideoProcessor()
            output_path = temp_path / "output.mp4"
            
            processor.process(
                local_folder, 
                output_path,
                skip_subtitle=skip_subtitle,
                debug=True
            )
            
            # Step 3: 上傳結果到 Google Drive
            jobs[job_id]["message"] = "正在上傳結果到 Google Drive..."
            output_file_id = drive.upload_file(output_path, drive_folder_id)
            drive_url = drive.get_file_link(output_file_id)
            
            # Step 4: 上傳 Debug 檔案和字幕檔
            jobs[job_id]["message"] = "正在上傳 Debug 檔案..."
            debug_files = [
                "_debug_step1_whisper.json",
                "_debug_step2_alignment.json",
                "full_subtitle.srt"
            ]
            
            for debug_file in debug_files:
                debug_path = local_folder / debug_file
                if debug_path.exists():
                    try:
                        drive.upload_file(debug_path, drive_folder_id)
                    except Exception as e:
                        print(f"   ⚠️  上傳 {debug_file} 失敗：{e}")
        
        # 更新任務狀態
        jobs[job_id] = {
            "status": JobStatus.COMPLETED,
            "message": "處理完成",
            "output_file_id": output_file_id,
            "drive_url": drive_url
        }
        
        # 發送成功通知
        await send_webhook(callback_url, WebhookPayload(
            job_id=job_id,
            status=JobStatus.COMPLETED,
            message="影片處理完成",
            output_file_id=output_file_id,
            drive_url=drive_url
        ))
        
        print(f"✅ 任務完成！")
        print(f"   輸出檔案 ID: {output_file_id}")
        print(f"   Drive 連結: {drive_url}")
        
    except Exception as e:
        error_msg = str(e)
        print(f"❌ 任務失敗：{error_msg}")
        
        jobs[job_id] = {
            "status": JobStatus.FAILED,
            "message": error_msg
        }
        
        # 發送失敗通知
        await send_webhook(callback_url, WebhookPayload(
            job_id=job_id,
            status=JobStatus.FAILED,
            message="影片處理失敗",
            error=error_msg
        ))


async def process_local_task(
    job_id: str,
    folder_path: str,
    callback_url: str,
    skip_subtitle: bool = False
):
    """
    背景任務：處理本地資料夾（測試用）
    """
    print(f"\n{'='*60}")
    print(f"🎬 開始處理本地任務：{job_id}")
    print(f"   資料夾路徑：{folder_path}")
    print(f"{'='*60}")
    
    jobs[job_id] = {"status": JobStatus.PROCESSING, "message": "處理中..."}
    
    try:
        folder = Path(folder_path)
        if not folder.exists():
            raise FileNotFoundError(f"資料夾不存在：{folder_path}")
        
        # 處理影片
        processor = VideoProcessor()
        output_path = folder.parent / f"{folder.name}_output.mp4"
        
        video_path = processor.process(
            folder, 
            output_path,
            skip_subtitle=skip_subtitle,
            debug=True
        )
        
        # 更新任務狀態
        jobs[job_id] = {
            "status": JobStatus.COMPLETED,
            "message": "處理完成",
            "output_path": str(video_path)
        }
        
        # 發送成功通知
        await send_webhook(callback_url, WebhookPayload(
            job_id=job_id,
            status=JobStatus.COMPLETED,
            message=f"影片處理完成：{video_path}"
        ))
        
        print(f"✅ 任務完成：{video_path}")
        
    except Exception as e:
        error_msg = str(e)
        print(f"❌ 任務失敗：{error_msg}")
        
        jobs[job_id] = {
            "status": JobStatus.FAILED,
            "message": error_msg
        }
        
        # 發送失敗通知
        await send_webhook(callback_url, WebhookPayload(
            job_id=job_id,
            status=JobStatus.FAILED,
            message="影片處理失敗",
            error=error_msg
        ))


# ============================================================
# API 端點
# ============================================================

@router.get("/health", response_model=HealthResponse)
async def health_check():
    """健康檢查端點"""
    return HealthResponse()


@router.post("/process-video-online", response_model=VideoResponse)
async def process_video(request: VideoRequest, background_tasks: BackgroundTasks):
    """
    處理 Google Drive 上的影片素材
    
    接收 Drive 資料夾 ID，在背景處理影片，完成後透過 Webhook 通知。
    
    - **drive_folder_id**: Google Drive 資料夾 ID
    - **callback_url**: Webhook URL（Make.com Custom Webhook）
    - **skip_subtitle**: 是否跳過字幕生成
    """
    job_id = generate_job_id()
    
    # 初始化任務狀態
    jobs[job_id] = {"status": JobStatus.PENDING, "message": "任務已排程"}
    
    # 加入背景任務
    background_tasks.add_task(
        process_video_task,
        job_id=job_id,
        drive_folder_id=request.drive_folder_id,
        callback_url=request.callback_url,
        skip_subtitle=request.skip_subtitle
    )
    
    return VideoResponse(
        job_id=job_id,
        status=JobStatus.PROCESSING,
        message="影片處理中，完成後會透過 Webhook 通知"
    )


@router.post("/process-video-local", response_model=VideoResponse)
async def process_local(
    folder_path: str,
    callback_url: str,
    background_tasks: BackgroundTasks,
    skip_subtitle: bool = False
):
    """
    處理本地資料夾的影片素材（測試用）
    
    - **folder_path**: 本地素材資料夾絕對路徑
    - **callback_url**: Webhook URL
    - **skip_subtitle**: 是否跳過字幕生成
    """
    job_id = generate_job_id()
    
    # 驗證路徑存在
    if not Path(folder_path).exists():
        raise HTTPException(status_code=400, detail=f"資料夾不存在：{folder_path}")
    
    # 初始化任務狀態
    jobs[job_id] = {"status": JobStatus.PENDING, "message": "任務已排程"}
    
    # 加入背景任務
    background_tasks.add_task(
        process_local_task,
        job_id=job_id,
        folder_path=folder_path,
        callback_url=callback_url,
        skip_subtitle=skip_subtitle
    )
    
    return VideoResponse(
        job_id=job_id,
        status=JobStatus.PROCESSING,
        message="影片處理中，完成後會透過 Webhook 通知"
    )


@router.get("/jobs/{job_id}")
async def get_job_status(job_id: str):
    """查詢任務狀態"""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail=f"找不到任務：{job_id}")
    
    return {"job_id": job_id, **jobs[job_id]}
