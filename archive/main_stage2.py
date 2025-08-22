# main.py - Stage 2: 사용자 데이터베이스 시스템 추가

from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel, Field
import logging
import sqlite3
import os
from datetime import datetime

# 기본 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

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

# 앱 시작시 DB 초기화
init_db()

# --- Pydantic 모델 정의 ---
class User(BaseModel):
    id: str  # botUserKey
    type: str
    properties: dict = {}

class UserRequest(BaseModel):
    user: User
    utterance: str

class KakaoRequest(BaseModel):
    userRequest: UserRequest

@app.get("/")
def read_root():
    """서버가 살아있는지 확인하는 기본 엔드포인트"""
    return {"Hello": "World"}

def save_or_update_user(bot_user_key: str, message: str = ""):
    """사용자 정보를 DB에 저장하거나 업데이트"""
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    
    now = datetime.now()
    
    # 기존 사용자 확인
    cursor.execute('SELECT * FROM users WHERE bot_user_key = ?', (bot_user_key,))
    user = cursor.fetchone()
    
    if user:
        # 기존 사용자 업데이트
        cursor.execute('''
            UPDATE users 
            SET last_message_at = ?, message_count = message_count + 1 
            WHERE bot_user_key = ?
        ''', (now, bot_user_key))
        logger.info(f"사용자 업데이트: {bot_user_key}")
    else:
        # 새 사용자 생성
        cursor.execute('''
            INSERT INTO users (bot_user_key, first_message_at, last_message_at, message_count)
            VALUES (?, ?, ?, 1)
        ''', (bot_user_key, now, now))
        logger.info(f"새 사용자 등록: {bot_user_key}")
    
    conn.commit()
    conn.close()

@app.post("/kakao/chat")
async def kakao_chat_callback(request: KakaoRequest):
    """
    카카오톡 챗봇으로부터 사용자의 메시지를 받는 콜백 엔드포인트
    """
    user_key = request.userRequest.user.id
    user_message = request.userRequest.utterance
    
    logger.info(f"Received message from user {user_key}: {user_message}")

    # 사용자 정보를 DB에 저장
    save_or_update_user(user_key, user_message)
    
    # 응답 메시지
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

@app.get("/users")
async def get_all_users():
    """
    등록된 모든 사용자 목록을 조회하는 엔드포인트
    """
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