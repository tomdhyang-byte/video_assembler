"""
API 請求/回應資料模型
使用 Pydantic 定義
"""

from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum


class JobStatus(str, Enum):
    """任務狀態"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class VideoRequest(BaseModel):
    """影片處理請求"""
    drive_folder_id: str = Field(..., description="Google Drive 資料夾 ID")
    callback_url: str = Field(..., description="完成後通知的 Webhook URL (Make.com)")
    skip_subtitle: bool = Field(default=False, description="是否跳過字幕生成")
    
    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "drive_folder_id": "1abc123def456",
                    "callback_url": "https://hook.make.com/xxx",
                    "skip_subtitle": False
                }
            ]
        }
    }


class VideoResponse(BaseModel):
    """影片處理回應"""
    job_id: str = Field(..., description="任務 ID，用於追蹤進度")
    status: JobStatus = Field(..., description="任務狀態")
    message: Optional[str] = Field(None, description="狀態訊息")
    output_file_id: Optional[str] = Field(None, description="輸出影片的 Drive File ID")
    drive_url: Optional[str] = Field(None, description="輸出影片的 Drive 連結")


class WebhookPayload(BaseModel):
    """Webhook 回調內容（發送給 Make.com）"""
    job_id: str
    status: JobStatus
    message: str
    output_file_id: Optional[str] = None
    drive_url: Optional[str] = None
    error: Optional[str] = None


class HealthResponse(BaseModel):
    """健康檢查回應"""
    status: str = "ok"
    version: str = "1.0.0"
