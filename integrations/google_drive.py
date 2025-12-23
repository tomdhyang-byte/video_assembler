"""
Google Drive API 整合
封裝下載/上傳功能
"""

import os
import io
from pathlib import Path
from typing import List, Optional

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload


class GoogleDriveClient:
    """
    Google Drive API 操作封裝
    
    使用 Service Account 認證，支援：
    - 下載資料夾內所有檔案
    - 上傳檔案到指定資料夾
    - 列出資料夾內容
    """
    
    SCOPES = ['https://www.googleapis.com/auth/drive']
    
    def __init__(self, credentials_path: str = None):
        """
        初始化 Google Drive 客戶端
        
        Args:
            credentials_path: Service Account JSON 金鑰路徑
                             預設為專案目錄下的 service_account.json
        """
        if credentials_path is None:
            # 預設路徑：專案根目錄
            project_root = Path(__file__).parent.parent
            credentials_path = project_root / "service_account.json"
        
        credentials_path = Path(credentials_path)
        
        if not credentials_path.exists():
            raise FileNotFoundError(
                f"找不到 Service Account 金鑰檔案：{credentials_path}\n"
                "請依照 README 說明設定 Google Cloud 專案並下載金鑰。"
            )
        
        # 建立認證
        credentials = service_account.Credentials.from_service_account_file(
            str(credentials_path),
            scopes=self.SCOPES
        )
        
        # 建立 Drive API 服務
        self.service = build('drive', 'v3', credentials=credentials)
        print("✅ Google Drive API 已連線")
    
    def list_files(self, folder_id: str) -> List[dict]:
        """
        列出資料夾內的所有檔案
        
        Args:
            folder_id: Google Drive 資料夾 ID
            
        Returns:
            檔案列表，每個項目包含 id, name, mimeType
        """
        results = []
        page_token = None
        
        while True:
            response = self.service.files().list(
                q=f"'{folder_id}' in parents and trashed=false",
                spaces='drive',
                fields='nextPageToken, files(id, name, mimeType, size)',
                pageToken=page_token,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True
            ).execute()
            
            results.extend(response.get('files', []))
            page_token = response.get('nextPageToken')
            
            if not page_token:
                break
        
        return results
    
    def download_file(self, file_id: str, local_path: Path) -> Path:
        """
        下載單一檔案
        
        Args:
            file_id: Google Drive 檔案 ID
            local_path: 本地儲存路徑
            
        Returns:
            下載完成的檔案路徑
        """
        request = self.service.files().get_media(fileId=file_id, supportsAllDrives=True)
        
        with open(local_path, 'wb') as f:
            downloader = MediaIoBaseDownload(f, request)
            done = False
            while not done:
                status, done = downloader.next_chunk()
        
        return local_path
    
    def download_folder(self, folder_id: str, local_path: Path) -> Path:
        """
        下載資料夾內的所有檔案到本地
        
        Args:
            folder_id: Google Drive 資料夾 ID
            local_path: 本地儲存目錄
            
        Returns:
            本地資料夾路徑
        """
        local_path = Path(local_path)
        local_path.mkdir(parents=True, exist_ok=True)
        
        # 取得資料夾名稱
        folder_meta = self.service.files().get(
            fileId=folder_id,
            fields='name',
            supportsAllDrives=True
        ).execute()
        folder_name = folder_meta.get('name', 'download')
        
        print(f"📂 開始下載資料夾：{folder_name}")
        
        # 列出所有檔案
        files = self.list_files(folder_id)
        
        if not files:
            print("   ⚠️  資料夾是空的")
            return local_path
        
        print(f"   找到 {len(files)} 個檔案")
        
        # 下載每個檔案
        for i, file in enumerate(files, 1):
            file_name = file['name']
            file_id = file['id']
            mime_type = file['mimeType']
            
            # 跳過子資料夾（不遞迴下載）
            if mime_type == 'application/vnd.google-apps.folder':
                print(f"   ⏭️  跳過子資料夾：{file_name}")
                continue
            
            # 跳過 Google Docs 等雲端原生格式
            if mime_type.startswith('application/vnd.google-apps.'):
                print(f"   ⏭️  跳過雲端文件：{file_name}")
                continue
            
            local_file_path = local_path / file_name
            print(f"   ⬇️  [{i}/{len(files)}] {file_name}...", end="", flush=True)
            
            try:
                self.download_file(file_id, local_file_path)
                print(" ✅")
            except Exception as e:
                print(f" ❌ {e}")
        
        print(f"✅ 資料夾下載完成：{local_path}")
        return local_path
    
    def upload_file(
        self, 
        file_path: Path, 
        parent_folder_id: str,
        file_name: Optional[str] = None
    ) -> str:
        """
        上傳檔案到 Google Drive
        
        Args:
            file_path: 本地檔案路徑
            parent_folder_id: 目標資料夾 ID
            file_name: 上傳後的檔案名稱（預設使用原檔名）
            
        Returns:
            上傳後的檔案 ID
        """
        file_path = Path(file_path)
        
        if not file_path.exists():
            raise FileNotFoundError(f"找不到要上傳的檔案：{file_path}")
        
        if file_name is None:
            file_name = file_path.name
        
        # 設定檔案 metadata
        file_metadata = {
            'name': file_name,
            'parents': [parent_folder_id]
        }
        
        # 根據副檔名設定 MIME 類型
        mime_types = {
            '.mp4': 'video/mp4',
            '.mp3': 'audio/mpeg',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.srt': 'text/plain',
            '.txt': 'text/plain',
            '.json': 'application/json',
        }
        mime_type = mime_types.get(file_path.suffix.lower(), 'application/octet-stream')
        
        # 上傳
        media = MediaFileUpload(
            str(file_path),
            mimetype=mime_type,
            resumable=True
        )
        
        print(f"⬆️  上傳檔案：{file_name}...", end="", flush=True)
        
        file = self.service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id, webViewLink',
            supportsAllDrives=True
        ).execute()
        
        file_id = file.get('id')
        web_link = file.get('webViewLink')
        
        print(f" ✅ (ID: {file_id})")
        
        return file_id
    
    def get_file_link(self, file_id: str) -> str:
        """
        取得檔案的 Google Drive 連結
        
        Args:
            file_id: 檔案 ID
            
        Returns:
            檔案的 webViewLink
        """
        file = self.service.files().get(
            fileId=file_id,
            fields='webViewLink',
            supportsAllDrives=True
        ).execute()
        
        return file.get('webViewLink', f"https://drive.google.com/file/d/{file_id}/view")


# 便捷函數
def get_drive_client() -> GoogleDriveClient:
    """取得 Google Drive 客戶端實例"""
    return GoogleDriveClient()
