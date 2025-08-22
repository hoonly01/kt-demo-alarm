# main.py - Stage 3: Event API 기본 구현

from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel, Field
import logging
import httpx
import json
from typing import List, Optional
import sqlite3
import os
from datetime import datetime

# 기본 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# 카카오 API 설정 (환경변수로 관리 예정)
KAKAO_REST_API_KEY = "YOUR_REST_API_KEY"
BOT_ID = "YOUR_BOT_ID"

# 데이터베이스 초기화
def init_db():
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bot_user_key TEXT UNIQUE NOT NULL,
            first_message_at DATETIME,
            last_message_at DATETIME,
            message_count INTEGER DEFAULT 1,
            location TEXT,
            active BOOLEAN DEFAULT TRUE
        )
    ''')
    
    conn.commit()
    conn.close()

init_db()

# --- Pydantic 모델 정의 ---
class User(BaseModel):
    id: str
    type: str
    properties: dict = {}

class UserRequest(BaseModel):
    user: User
    utterance: str

class KakaoRequest(BaseModel):
    userRequest: UserRequest

# Event API 모델 정의
class EventData(BaseModel):
    text: Optional[str] = None

class Event(BaseModel):
    name: str
    data: Optional[EventData] = None

class EventUser(BaseModel):
    type: str  # "botUserKey", "plusfriendUserKey", "appUserId"
    id: str
    properties: Optional[dict] = None

class EventAPIRequest(BaseModel):
    event: Event
    user: List[EventUser]
    params: Optional[dict] = None

class AlarmRequest(BaseModel):
    user_id: str
    message: str
    location: Optional[str] = None

@app.get("/")
def read_root():
    return {"Hello": "World"}

def save_or_update_user(bot_user_key: str, message: str = ""):
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    
    now = datetime.now()
    cursor.execute('SELECT * FROM users WHERE bot_user_key = ?', (bot_user_key,))
    user = cursor.fetchone()
    
    if user:
        cursor.execute('''
            UPDATE users 
            SET last_message_at = ?, message_count = message_count + 1 
            WHERE bot_user_key = ?
        ''', (now, bot_user_key))
        logger.info(f"사용자 업데이트: {bot_user_key}")
    else:
        cursor.execute('''
            INSERT INTO users (bot_user_key, first_message_at, last_message_at, message_count)
            VALUES (?, ?, ?, 1)
        ''', (bot_user_key, now, now))
        logger.info(f"새 사용자 등록: {bot_user_key}")
    
    conn.commit()
    conn.close()

@app.post("/kakao/chat")
async def kakao_chat_callback(request: KakaoRequest):
    user_key = request.userRequest.user.id
    user_message = request.userRequest.utterance
    
    logger.info(f"Received message from user {user_key}: {user_message}")
    save_or_update_user(user_key, user_message)
    
    response = {
        "version": "2.0",
        "template": {
            "outputs": [
                {
                    "simpleText": {
                        "text": f"안녕하세요! 당신의 사용자 ID는 '{user_key}' 입니다. 알림 서비스에 등록되었습니다."
                    }
                }
            ]
        }
    }
    return response

@app.post("/send-alarm")
async def send_alarm(alarm_request: AlarmRequest):
    """
    특정 사용자에게 알림 메시지를 전송하는 엔드포인트
    """
    
    # Event API 요청 데이터 구성
    event_data = EventAPIRequest(
        event=Event(
            name="kt_alarm",  # 카카오 관리자센터에서 설정한 이벤트 이름
            data=EventData(text=alarm_request.message)
        ),
        user=[EventUser(
            type="botUserKey",
            id=alarm_request.user_id
        )],
        params={
            "location": alarm_request.location or "",
            "timestamp": str(int(__import__('time').time()))
        }
    )
    
    # 카카오 Event API 호출
    headers = {
        "Authorization": f"KakaoAK {KAKAO_REST_API_KEY}",
        "Content-Type": "application/json"
    }
    
    url = f"https://bot-api.kakao.com/v2/bots/{BOT_ID}/talk"
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers=headers,
                json=event_data.dict()
            )
            
            if response.status_code == 200:
                result = response.json()
                logger.info(f"Event API 호출 성공: {result}")
                return {
                    "success": True,
                    "task_id": result.get("taskId"),
                    "status": result.get("status"),
                    "message": "알림이 전송되었습니다."
                }
            else:
                logger.error(f"Event API 호출 실패: {response.status_code}, {response.text}")
                raise HTTPException(status_code=500, detail="알림 전송에 실패했습니다.")
                
    except Exception as e:
        logger.error(f"알림 전송 중 오류 발생: {str(e)}")
        raise HTTPException(status_code=500, detail=f"알림 전송 중 오류: {str(e)}")

@app.get("/alarm-status/{task_id}")
async def check_alarm_status(task_id: str):
    """
    알림 전송 상태를 확인하는 엔드포인트
    """
    headers = {
        "Authorization": f"KakaoAK {KAKAO_REST_API_KEY}",
        "Content-Type": "application/json"
    }
    
    url = f"https://bot-api.kakao.com/v1/tasks/{task_id}"
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers)
            
            if response.status_code == 200:
                result = response.json()
                return {
                    "task_id": task_id,
                    "status": result.get("status"),
                    "success_count": result.get("successCount"),
                    "all_request_count": result.get("allRequestCount"),
                    "fail": result.get("fail")
                }
            else:
                raise HTTPException(status_code=500, detail="상태 확인에 실패했습니다.")
                
    except Exception as e:
        logger.error(f"상태 확인 중 오류 발생: {str(e)}")
        raise HTTPException(status_code=500, detail=f"상태 확인 중 오류: {str(e)}")

@app.get("/users")
async def get_all_users():
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT bot_user_key, first_message_at, last_message_at, message_count, location, active 
        FROM users 
        WHERE active = 1
        ORDER BY last_message_at DESC
    ''')
    
    users = cursor.fetchall()
    conn.close()
    
    return {
        "total_users": len(users),
        "users": [
            {
                "bot_user_key": user[0],
                "first_message_at": user[1],
                "last_message_at": user[2], 
                "message_count": user[3],
                "location": user[4],
                "active": user[5]
            }
            for user in users
        ]
    }