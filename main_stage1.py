# main.py - Stage 1: FastAPI 기본 구조 및 Pydantic 모델

from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel, Field
import logging

# 기본 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# --- Pydantic 모델 정의 ---
# 카카오톡 챗봇이 보내주는 데이터 구조를 클래스로 정의합니다.
# 이렇게 하면 타입 힌팅, 유효성 검사, 자동 완성이 가능해져 매우 편리합니다.

class User(BaseModel):
    id: str  # botUserKey. 카카오 문서에서는 plusfriendUserKey 또는 botUserKey 라고 함
    type: str
    properties: dict = {}

class UserRequest(BaseModel):
    user: User
    utterance: str # 사용자가 입력한 실제 메시지

class KakaoRequest(BaseModel):
    userRequest: UserRequest

@app.get("/")
def read_root():
    """서버가 살아있는지 확인하는 기본 엔드포인트"""
    return {"Hello": "World"}

@app.post("/kakao/chat")
async def kakao_chat_callback(request: KakaoRequest):
    """
    카카오톡 챗봇으로부터 사용자의 메시지를 받는 콜백 엔드포인트
    """
    user_key = request.userRequest.user.id
    user_message = request.userRequest.utterance
    
    logger.info(f"Received message from user {user_key}: {user_message}")

    # 지금은 간단한 응답만 반환합니다.
    # 이 응답은 사용자에게 카톡 메시지로 보여집니다.
    response = {
        "version": "2.0",
        "template": {
            "outputs": [
                {
                    "simpleText": {
                        "text": f"안녕하세요! 당신의 사용자 ID는 '{user_key}' 입니다. 곧 서비스가 준비될 예정입니다."
                    }
                }
            ]
        }
    }
    return response