# main.py

from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel, Field
import logging
import httpx
import json
from typing import List, Optional
import sqlite3
import os
from datetime import datetime
from dotenv import load_dotenv

# 환경변수 로드
load_dotenv()

# 기본 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# 카카오 API 설정
KAKAO_REST_API_KEY = os.getenv("KAKAO_REST_API_KEY")
BOT_ID = os.getenv("BOT_ID")
DATABASE_PATH = os.getenv("DATABASE_PATH", "users.db")

# 데이터베이스 초기화
def init_db():
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bot_user_key TEXT UNIQUE NOT NULL,
            first_message_at DATETIME,
            last_message_at DATETIME,
            message_count INTEGER DEFAULT 1,
            location TEXT,
            categories TEXT,  -- JSON 형태로 관심 카테고리 저장
            preferences TEXT, -- JSON 형태로 기타 설정 저장
            active BOOLEAN DEFAULT TRUE,
            departure_name TEXT,
            departure_address TEXT,
            departure_x REAL,
            departure_y REAL,
            arrival_name TEXT,
            arrival_address TEXT,
            arrival_x REAL,
            arrival_y REAL,
            route_updated_at DATETIME
        )
    ''')
    
    # 기존 테이블에 새 컬럼 추가 (마이그레이션)
    try:
        cursor.execute('ALTER TABLE users ADD COLUMN departure_name TEXT')
        cursor.execute('ALTER TABLE users ADD COLUMN departure_address TEXT')
        cursor.execute('ALTER TABLE users ADD COLUMN departure_x REAL')
        cursor.execute('ALTER TABLE users ADD COLUMN departure_y REAL')
        cursor.execute('ALTER TABLE users ADD COLUMN arrival_name TEXT')
        cursor.execute('ALTER TABLE users ADD COLUMN arrival_address TEXT')
        cursor.execute('ALTER TABLE users ADD COLUMN arrival_x REAL')
        cursor.execute('ALTER TABLE users ADD COLUMN arrival_y REAL')
        cursor.execute('ALTER TABLE users ADD COLUMN route_updated_at DATETIME')
        logger.info("경로 정보 컬럼들이 성공적으로 추가되었습니다.")
    except sqlite3.OperationalError:
        # 컬럼이 이미 존재하는 경우
        logger.info("경로 정보 컬럼들이 이미 존재합니다.")
    
    conn.commit()
    conn.close()

# 앱 시작시 DB 초기화
init_db()

# --------------------------
# 카카오 지도 API 함수
# --------------------------
async def get_location_info(query: str):
    """
    카카오 지도 API를 사용하여 검색어를 장소 정보로 변환
    """
    url = "https://dapi.kakao.com/v2/local/search/keyword.json"
    headers = {"Authorization": f"KakaoAK {KAKAO_REST_API_KEY}"}
    params = {"query": query}

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, params=params)
            
            if response.status_code == 200:
                data = response.json()
                
                if data.get("documents"):
                    doc = data["documents"][0]  # 첫 번째 검색 결과 사용
                    return {
                        "name": doc["place_name"],
                        "address": doc.get("road_address_name") or doc.get("address_name"),
                        "x": float(doc["x"]),  # 경도
                        "y": float(doc["y"])   # 위도
                    }
                else:
                    logger.warning(f"검색 결과가 없습니다: {query}")
                    return None
            else:
                logger.error(f"카카오 지도 API 호출 실패: {response.status_code}")
                return None
                
    except Exception as e:
        logger.error(f"카카오 지도 API 호출 중 오류: {str(e)}")
        return None

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

class FilteredAlarmRequest(BaseModel):
    message: str
    location_filter: Optional[str] = None
    category_filter: Optional[List[str]] = None
    user_filter: Optional[List[str]] = None  # 특정 사용자들만

class UserPreferences(BaseModel):
    location: Optional[str] = None
    categories: Optional[List[str]] = None
    preferences: Optional[dict] = None

@app.get("/")
def read_root():
    """서버가 살아있는지 확인하는 기본 엔드포인트"""
    return {"Hello": "World"}

def save_or_update_user(bot_user_key: str, message: str = ""):
    """사용자 정보를 DB에 저장하거나 업데이트"""
    conn = sqlite3.connect(DATABASE_PATH)
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

@app.post("/send-alarm")
async def send_alarm(alarm_request: AlarmRequest):
    """
    특정 사용자에게 알림 메시지를 전송하는 엔드포인트
    """
    
    # Event API 요청 데이터 구성
    event_data = EventAPIRequest(
        event=Event(
            name="morning_demo_alarm",  # 카카오 관리자센터에서 설정한 이벤트 이름
            data=EventData(text=alarm_request.message)
        ),
        user=[EventUser(
            type="appUserId",  # open_id는 appUserId로 전송
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
    """
    등록된 모든 사용자 목록을 조회하는 엔드포인트
    """
    conn = sqlite3.connect(DATABASE_PATH)
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

@app.post("/send-alarm-to-all")
async def send_alarm_to_all(message: str):
    """
    모든 등록된 사용자에게 알림을 전송하는 엔드포인트
    """
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    cursor.execute('SELECT bot_user_key FROM users WHERE active = 1')
    users = cursor.fetchall()
    conn.close()
    
    if not users:
        raise HTTPException(status_code=404, detail="등록된 사용자가 없습니다.")
    
    # 최대 100명씩 배치로 전송
    user_keys = [user[0] for user in users]
    batch_size = 100
    results = []
    
    for i in range(0, len(user_keys), batch_size):
        batch = user_keys[i:i + batch_size]
        
        # Event API 요청 데이터 구성
        event_data = EventAPIRequest(
            event=Event(
                name="morning_demo_alarm",
                data=EventData(text=message)
            ),
            user=[EventUser(type="appUserId", id=user_key) for user_key in batch],
            params={
                "broadcast": "true",
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
                    results.append({
                        "batch": i // batch_size + 1,
                        "user_count": len(batch),
                        "task_id": result.get("taskId"),
                        "status": result.get("status")
                    })
                else:
                    logger.error(f"Batch {i // batch_size + 1} 전송 실패: {response.status_code}")
                    results.append({
                        "batch": i // batch_size + 1,
                        "user_count": len(batch),
                        "error": response.text
                    })
                    
        except Exception as e:
            logger.error(f"Batch {i // batch_size + 1} 전송 중 오류: {str(e)}")
            results.append({
                "batch": i // batch_size + 1,
                "user_count": len(batch),
                "error": str(e)
            })
    
    return {
        "total_users": len(user_keys),
        "batches": len(results),
        "results": results
    }

@app.post("/users/{user_id}/preferences")
async def update_user_preferences(user_id: str, preferences: UserPreferences):
    """
    사용자 설정 업데이트 (지역, 카테고리 등)
    """
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    # 기존 사용자 확인
    cursor.execute('SELECT * FROM users WHERE bot_user_key = ?', (user_id,))
    user = cursor.fetchone()
    
    if not user:
        conn.close()
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")
    
    # 설정 업데이트
    categories_json = json.dumps(preferences.categories) if preferences.categories else None
    preferences_json = json.dumps(preferences.preferences) if preferences.preferences else None
    
    cursor.execute('''
        UPDATE users 
        SET location = ?, categories = ?, preferences = ?, last_message_at = ?
        WHERE bot_user_key = ?
    ''', (preferences.location, categories_json, preferences_json, datetime.now(), user_id))
    
    conn.commit()
    conn.close()
    
    return {"message": "설정이 업데이트되었습니다."}

@app.post("/send-filtered-alarm")
async def send_filtered_alarm(alarm_request: FilteredAlarmRequest):
    """
    필터링된 사용자들에게 알림을 전송하는 엔드포인트
    """
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    # 쿼리 구성
    query = "SELECT bot_user_key FROM users WHERE active = 1"
    params = []
    
    # 지역 필터
    if alarm_request.location_filter:
        query += " AND location = ?"
        params.append(alarm_request.location_filter)
    
    # 카테고리 필터
    if alarm_request.category_filter:
        category_conditions = []
        for category in alarm_request.category_filter:
            category_conditions.append("categories LIKE ?")
            params.append(f"%{category}%")
        if category_conditions:
            query += f" AND ({' OR '.join(category_conditions)})"
    
    # 특정 사용자 필터
    if alarm_request.user_filter:
        placeholders = ",".join(["?" for _ in alarm_request.user_filter])
        query += f" AND bot_user_key IN ({placeholders})"
        params.extend(alarm_request.user_filter)
    
    cursor.execute(query, params)
    users = cursor.fetchall()
    conn.close()
    
    if not users:
        raise HTTPException(status_code=404, detail="조건에 맞는 사용자가 없습니다.")
    
    # 필터링된 사용자들에게 알림 전송
    user_keys = [user[0] for user in users]
    batch_size = 100
    results = []
    
    for i in range(0, len(user_keys), batch_size):
        batch = user_keys[i:i + batch_size]
        
        # Event API 요청 데이터 구성
        event_data = EventAPIRequest(
            event=Event(
                name="morning_demo_alarm",
                data=EventData(text=alarm_request.message)
            ),
            user=[EventUser(type="appUserId", id=user_key) for user_key in batch],
            params={
                "filtered": "true",
                "location_filter": alarm_request.location_filter or "",
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
                    results.append({
                        "batch": i // batch_size + 1,
                        "user_count": len(batch),
                        "task_id": result.get("taskId"),
                        "status": result.get("status")
                    })
                else:
                    logger.error(f"Batch {i // batch_size + 1} 전송 실패: {response.status_code}")
                    results.append({
                        "batch": i // batch_size + 1,
                        "user_count": len(batch),
                        "error": response.text
                    })
                    
        except Exception as e:
            logger.error(f"Batch {i // batch_size + 1} 전송 중 오류: {str(e)}")
            results.append({
                "batch": i // batch_size + 1,
                "user_count": len(batch),
                "error": str(e)
            })
    
    return {
        "filtered_users": len(user_keys),
        "total_batches": len(results),
        "filter_applied": {
            "location": alarm_request.location_filter,
            "categories": alarm_request.category_filter,
            "specific_users": alarm_request.user_filter
        },
        "results": results
    }

@app.post("/webhook/kakao-channel")
async def kakao_channel_webhook(request: Request):
    """
    카카오톡 채널 웹훅 - 사용자 채널 추가/차단 상태 동기화
    """
    # 헤더 검증
    auth_header = request.headers.get("authorization")
    if not auth_header or not auth_header.startswith("KakaoAK"):
        raise HTTPException(status_code=401, detail="Invalid authorization header")
    
    # 요청 본문 파싱
    body = await request.json()
    
    event = body.get("event")  # "added" or "blocked"
    user_id = body.get("id")
    id_type = body.get("id_type")  # "app_user_id" or "open_id"
    channel_public_id = body.get("channel_public_id")
    updated_at = body.get("updated_at")
    
    logger.info(f"웹훅 수신: event={event}, user_id={user_id}, id_type={id_type}")
    
    # DB에서 사용자 상태 업데이트
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    if event == "added":
        # 채널 추가됨 - 사용자 활성화
        cursor.execute('''
            UPDATE users SET active = 1, last_message_at = ? 
            WHERE bot_user_key = ?
        ''', (datetime.now(), user_id))
        
        if cursor.rowcount == 0:
            # 새 사용자인 경우 생성
            cursor.execute('''
                INSERT INTO users (bot_user_key, first_message_at, last_message_at, active)
                VALUES (?, ?, ?, 1)
            ''', (user_id, datetime.now(), datetime.now()))
            logger.info(f"새 사용자 웹훅으로 등록: {user_id}")
        else:
            logger.info(f"사용자 활성화: {user_id}")
            
    elif event == "blocked":
        # 채널 차단됨 - 사용자 비활성화
        cursor.execute('''
            UPDATE users SET active = 0, last_message_at = ? 
            WHERE bot_user_key = ?
        ''', (datetime.now(), user_id))
        logger.info(f"사용자 비활성화: {user_id}")
    
    conn.commit()
    conn.close()
    
    # 성공 응답 (3초 내 2XX 응답 필요)
    return {"status": "ok", "processed_event": event, "user_id": user_id}