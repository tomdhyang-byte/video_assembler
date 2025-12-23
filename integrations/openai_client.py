"""
OpenAI API 客戶端封裝
統一管理 OpenAI API 呼叫
"""

import os
from openai import OpenAI
from dotenv import load_dotenv

# 載入環境變數
load_dotenv()


class OpenAIClient:
    """OpenAI API 客戶端"""
    
    # 預設設定
    DEFAULT_MODEL = "gpt-4o-mini"
    DEFAULT_TEMPERATURE = 0.3
    WHISPER_MODEL = "whisper-1"
    
    _instance = None
    
    def __new__(cls):
        """Singleton pattern - 確保只有一個實例"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
            
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("❌ 錯誤：未設定 OPENAI_API_KEY 環境變數")
        
        self.client = OpenAI(api_key=api_key)
        self._initialized = True
    
    def transcribe_audio(self, audio_path, language: str = "zh") -> dict:
        """
        使用 Whisper API 進行語音辨識
        
        Args:
            audio_path: 音訊檔案路徑
            language: 語言代碼
            
        Returns:
            API 回傳的完整結果（包含 words 時間戳）
        """
        with open(audio_path, "rb") as audio_file:
            response = self.client.audio.transcriptions.create(
                model=self.WHISPER_MODEL,
                file=audio_file,
                language=language,
                response_format="verbose_json",
                timestamp_granularities=["word"]
            )
        return response
    
    def chat_completion(
        self, 
        system_prompt: str, 
        user_prompt: str,
        model: str = None,
        temperature: float = None
    ) -> str:
        """
        呼叫 Chat Completion API
        
        Args:
            system_prompt: 系統提示詞
            user_prompt: 用戶提示詞
            model: 模型名稱（預設 gpt-4o-mini）
            temperature: 溫度參數
            
        Returns:
            回應文字內容
        """
        response = self.client.chat.completions.create(
            model=model or self.DEFAULT_MODEL,
            temperature=temperature or self.DEFAULT_TEMPERATURE,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
        )
        return response.choices[0].message.content


# 便捷函數：取得單例實例
def get_openai_client() -> OpenAIClient:
    """取得 OpenAI 客戶端單例"""
    return OpenAIClient()
