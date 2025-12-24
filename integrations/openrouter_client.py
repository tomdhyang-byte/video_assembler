"""
OpenRouter API 客戶端封裝
用於呼叫 Claude 等模型進行字幕斷句
"""

import os
from openai import OpenAI
from dotenv import load_dotenv

# 載入環境變數
load_dotenv()


class OpenRouterClient:
    """OpenRouter API 客戶端"""
    
    # 預設設定
    DEFAULT_MODEL = "anthropic/claude-sonnet-4.5"
    DEFAULT_TEMPERATURE = 0.3
    BASE_URL = "https://openrouter.ai/api/v1"
    
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
            
        api_key = os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            raise ValueError("❌ 錯誤：未設定 OPENROUTER_API_KEY 環境變數")
        
        self.client = OpenAI(
            base_url=self.BASE_URL,
            api_key=api_key,
            default_headers={
                "HTTP-Referer": "https://autovideomaker.local",
                "X-Title": "AutoVideoMaker"
            }
        )
        self._initialized = True
    
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
            model: 模型名稱（預設 anthropic/claude-sonnet-4.5）
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
def get_openrouter_client() -> OpenRouterClient:
    """取得 OpenRouter 客戶端單例"""
    return OpenRouterClient()
