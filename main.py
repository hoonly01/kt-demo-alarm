# main.py

from fastapi import FastAPI, Request, HTTPException, BackgroundTasks, Depends
from pydantic import BaseModel, Field
import logging
import httpx
import json
from typing import List, Optional
import sqlite3
import os
import time
import math
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
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
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
    
    # events 테이블 생성 (Phase 9: 집회 데이터 저장)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            location_name TEXT NOT NULL,
            location_address TEXT,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            start_date DATETIME NOT NULL,
            end_date DATETIME,
            category TEXT,
            severity_level INTEGER DEFAULT 1,
            status TEXT DEFAULT 'active',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
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

# DB 의존성 주입 함수
def get_db():
    """데이터베이스 연결을 위한 의존성 주입 함수"""
    db = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    try:
        yield db
    finally:
        db.close()

# 앱 시작시 DB 초기화
init_db()

# --------------------------
# 거리 계산 함수 (Phase 9)
# --------------------------
def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Haversine 공식을 사용하여 두 지점 간의 거리를 계산 (단위: 미터)
    
    Args:
        lat1, lon1: 첫 번째 지점의 위도, 경도
        lat2, lon2: 두 번째 지점의 위도, 경도
    
    Returns:
        float: 두 지점 간의 거리 (미터)
    """
    # 지구의 반지름 (미터)
    R = 6371000
    
    # 위도와 경도를 라디안으로 변환
    lat1_rad = math.radians(lat1)
    lon1_rad = math.radians(lon1)
    lat2_rad = math.radians(lat2)
    lon2_rad = math.radians(lon2)
    
    # 위도와 경도의 차이
    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad
    
    # Haversine 공식
    a = math.sin(dlat/2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon/2)**2
    c = 2 * math.asin(math.sqrt(a))
    
    # 거리 계산
    distance = R * c
    
    return distance

def is_point_near_route(start_lat: float, start_lon: float, end_lat: float, end_lon: float, 
                       point_lat: float, point_lon: float, threshold_meters: float = 500) -> bool:
    """
    한 점이 두 지점을 잇는 직선 경로 근처에 있는지 확인
    
    Args:
        start_lat, start_lon: 출발지 좌표
        end_lat, end_lon: 도착지 좌표
        point_lat, point_lon: 확인할 점의 좌표
        threshold_meters: 임계거리 (미터, 기본값: 500m)
    
    Returns:
        bool: 경로 근처에 있으면 True
    """
    # 출발지와 도착지에서 점까지의 거리 계산
    dist_to_start = haversine_distance(start_lat, start_lon, point_lat, point_lon)
    dist_to_end = haversine_distance(end_lat, end_lon, point_lat, point_lon)
    
    # 출발지와 도착지 사이의 거리
    route_distance = haversine_distance(start_lat, start_lon, end_lat, end_lon)
    
    # 만약 점이 출발지나 도착지에서 임계거리 내에 있다면 True
    if dist_to_start <= threshold_meters or dist_to_end <= threshold_meters:
        return True
    
    # 삼각형 부등식을 이용한 간단한 경로 근처 판별
    # 만약 (출발지->점->도착지)의 거리가 직선거리와 크게 차이나지 않으면 경로 근처
    triangle_distance = dist_to_start + dist_to_end
    deviation = triangle_distance - route_distance
    
    # 편차가 임계값보다 작으면 경로 근처로 판단
    return deviation <= threshold_meters * 2

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

async def get_route_coordinates(start_x: float, start_y: float, end_x: float, end_y: float):
    """
    카카오 Mobility API를 사용하여 실제 보행 경로 좌표를 가져옴
    
    Args:
        start_x, start_y: 출발지 경도, 위도
        end_x, end_y: 도착지 경도, 위도
    
    Returns:
        List[Tuple[float, float]]: 경로상의 (위도, 경도) 좌표 리스트
    """
    url = f"https://apis-navi.kakaomobility.com/v1/directions"
    headers = {"Authorization": f"KakaoAK {KAKAO_REST_API_KEY}"}
    params = {
        "origin": f"{start_x},{start_y}",
        "destination": f"{end_x},{end_y}",
        "priority": "RECOMMEND"  # 추천 경로
    }
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, params=params)
            
            if response.status_code == 200:
                data = response.json()
                
                if "routes" in data and len(data["routes"]) > 0:
                    route = data["routes"][0]
                    coordinates = []
                    
                    # 경로의 모든 섹션에서 좌표 추출
                    for section in route["sections"]:
                        for road in section["roads"]:
                            vertexes = road["vertexes"]
                            # vertexes는 [경도, 위도, 경도, 위도, ...] 형태
                            for i in range(0, len(vertexes), 2):
                                if i + 1 < len(vertexes):
                                    lon = vertexes[i]      # 경도
                                    lat = vertexes[i + 1]  # 위도
                                    coordinates.append((lat, lon))
                    
                    logger.info(f"경로 좌표 {len(coordinates)}개 추출 완료")
                    return coordinates
                else:
                    logger.warning("경로를 찾을 수 없습니다")
                    return []
            else:
                logger.error(f"카카오 Mobility API 호출 실패: {response.status_code}, {response.text}")
                return []
                
    except Exception as e:
        logger.error(f"카카오 Mobility API 호출 중 오류: {str(e)}")
        return []

def is_event_near_route_accurate(route_coordinates: list, event_lat: float, event_lon: float, threshold_meters: float = 500) -> bool:
    """
    실제 경로 좌표를 사용하여 집회가 경로 근처에 있는지 정확히 확인
    
    Args:
        route_coordinates: 경로상의 (위도, 경도) 좌표 리스트
        event_lat, event_lon: 집회 위치
        threshold_meters: 임계거리 (미터)
    
    Returns:
        bool: 경로 근처에 있으면 True
    """
    if not route_coordinates:
        return False
    
    # 경로상의 각 점에서 집회까지의 거리 확인
    for lat, lon in route_coordinates:
        distance = haversine_distance(lat, lon, event_lat, event_lon)
        if distance <= threshold_meters:
            logger.info(f"집회가 경로에서 {distance:.0f}m 거리에 감지됨")
            return True
    
    return False

# --------------------------
# 경로 정보 저장 함수
# --------------------------
async def save_route_to_db(user_id: str, departure: str, arrival: str):
    """
    사용자 경로 정보를 데이터베이스에 저장
    """
    try:
        # 카카오 지도 API로 위치 정보 조회
        dep_info = await get_location_info(departure) if departure else None
        arr_info = await get_location_info(arrival) if arrival else None
        
        # 데이터베이스 업데이트
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        cursor = conn.cursor()
        
        now = datetime.now()
        
        # 사용자 경로 정보 업데이트
        cursor.execute('''
            UPDATE users 
            SET departure_name = ?, departure_address = ?, departure_x = ?, departure_y = ?,
                arrival_name = ?, arrival_address = ?, arrival_x = ?, arrival_y = ?,
                route_updated_at = ?
            WHERE bot_user_key = ?
        ''', (
            dep_info["name"] if dep_info else departure,
            dep_info["address"] if dep_info else None,
            dep_info["x"] if dep_info else None,
            dep_info["y"] if dep_info else None,
            arr_info["name"] if arr_info else arrival,
            arr_info["address"] if arr_info else None,
            arr_info["x"] if arr_info else None,
            arr_info["y"] if arr_info else None,
            now,
            user_id
        ))
        
        if cursor.rowcount > 0:
            logger.info(f"사용자 {user_id} 경로 정보 업데이트 완료: {departure} → {arrival}")
        else:
            logger.warning(f"사용자 {user_id}를 찾을 수 없어 경로 정보 업데이트 실패")
        
        conn.commit()
        conn.close()
        
    except Exception as e:
        logger.error(f"경로 정보 저장 중 오류 발생: {str(e)}")

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

# Phase 9: 집회 관련 Pydantic 모델
class EventCreate(BaseModel):
    title: str = Field(..., description="집회 제목")
    description: Optional[str] = Field(None, description="집회 설명")
    location_name: str = Field(..., description="집회 장소명")
    location_address: Optional[str] = Field(None, description="집회 주소")
    latitude: float = Field(..., description="위도")
    longitude: float = Field(..., description="경도")
    start_date: datetime = Field(..., description="시작 일시")
    end_date: Optional[datetime] = Field(None, description="종료 일시")
    category: Optional[str] = Field(None, description="집회 카테고리")
    severity_level: int = Field(1, description="심각도 (1: 낮음, 2: 보통, 3: 높음)")

class EventResponse(BaseModel):
    id: int
    title: str
    description: Optional[str]
    location_name: str
    location_address: Optional[str]
    latitude: float
    longitude: float
    start_date: datetime
    end_date: Optional[datetime]
    category: Optional[str]
    severity_level: int
    status: str
    created_at: datetime
    updated_at: datetime

class RouteEventCheck(BaseModel):
    user_id: str
    events_found: List[EventResponse]
    route_info: dict
    total_events: int

@app.get("/")
def read_root():
    """서버가 살아있는지 확인하는 기본 엔드포인트"""
    return {"Hello": "World"}

def save_or_update_user(bot_user_key: str, message: str = ""):
    """사용자 정보를 DB에 저장하거나 업데이트"""
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
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
            "timestamp": str(int(time.time()))
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
                json=event_data.model_dump()
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
async def get_all_users(db: sqlite3.Connection = Depends(get_db)):
    """
    등록된 모든 사용자 목록을 조회하는 엔드포인트
    """
    cursor = db.cursor()
    
    cursor.execute('''
        SELECT bot_user_key, first_message_at, last_message_at, message_count, location, active,
               departure_name, departure_address, departure_x, departure_y,
               arrival_name, arrival_address, arrival_x, arrival_y, route_updated_at
        FROM users 
        WHERE active = 1
        ORDER BY last_message_at DESC
    ''')
    
    users = cursor.fetchall()
    
    return {
        "total_users": len(users),
        "users": [
            {
                "bot_user_key": user[0],
                "first_message_at": user[1],
                "last_message_at": user[2], 
                "message_count": user[3],
                "location": user[4],
                "active": user[5],
                "route_info": {
                    "departure": {
                        "name": user[6],
                        "address": user[7],
                        "coordinates": {"x": user[8], "y": user[9]} if user[8] and user[9] else None
                    },
                    "arrival": {
                        "name": user[10],
                        "address": user[11], 
                        "coordinates": {"x": user[12], "y": user[13]} if user[12] and user[13] else None
                    },
                    "updated_at": user[14]
                } if user[6] or user[10] else None
            }
            for user in users
        ]
    }

@app.post("/send-alarm-to-all")
async def send_alarm_to_all(message: str):
    """
    모든 등록된 사용자에게 알림을 전송하는 엔드포인트
    """
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
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
                "timestamp": str(int(time.time()))
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
                    json=event_data.model_dump()
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
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
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
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
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
                "timestamp": str(int(time.time()))
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
                    json=event_data.model_dump()
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
    
    # id_type 검증 - 보안 강화
    if id_type != "app_user_id":
        logger.warning(f"Unsupported id_type '{id_type}' received from webhook for user {user_id}")
        return {"status": "ignored", "reason": "unsupported id_type"}
    
    # DB에서 사용자 상태 업데이트
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
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

@app.post("/save_user_info")
async def save_user_info(request: Request, background_tasks: BackgroundTasks):
    """
    카카오톡 스킬 블록에서 사용자 경로 정보를 저장하는 엔드포인트
    """
    body = await request.json()
    
    # 카카오톡에서 온 요청인지 확인
    if 'userRequest' in body:
        user_id = body['userRequest']['user']['id']
    else:  # 로컬 테스트용
        user_id = body.get('userId', 'test-user')
    
    # 출발지와 도착지 정보 추출
    departure = body.get('action', {}).get('params', {}).get('departure', '')
    arrival = body.get('action', {}).get('params', {}).get('arrival', '')
    
    # 백그라운드에서 경로 정보 저장
    background_tasks.add_task(save_route_to_db, user_id, departure, arrival)
    
    # 즉시 응답 (사용자 대기 시간 단축)
    return {
        "version": "2.0",
        "template": {
            "outputs": [
                {
                    "simpleText": {
                        "text": (
                            f"📍 출발지: {departure}\n"
                            f"📍 도착지: {arrival}\n\n"
                            "✅ 출발지와 도착지가 정상적으로 등록되었습니다.\n"
                            "📢 매일 아침, 등록하신 경로에 예정된 집회 정보를 안내해드립니다.\n"
                            "🔄 경로를 변경하고 싶으실 땐, 언제든 [🚗 출퇴근 경로 등록하기] 버튼을 눌러주세요."
                        )
                    }
                }
            ]
        }
    }

# --------------------------
# Phase 9: 집회 관리 API
# --------------------------

async def auto_notify_route_events(user_id: str, events_found: List[EventResponse]):
    """
    감지된 집회를 사용자에게 자동으로 알림 전송
    
    Args:
        user_id: 사용자 ID  
        events_found: 감지된 집회 목록
    """
    if not events_found:
        return
    
    # 알림 메시지 구성
    event_count = len(events_found)
    message_lines = [f"🚨 출퇴근 경로에 {event_count}개의 집회가 예정되어 있습니다.\n"]
    
    for event in events_found:
        start_date = event.start_date.strftime('%m월 %d일 %H:%M')
        severity = "🔴 높음" if event.severity_level == 3 else "🟡 보통" if event.severity_level == 2 else "🟢 낮음"
        
        message_lines.append(f"📍 {event.title}")
        message_lines.append(f"📅 {start_date}")
        message_lines.append(f"🏢 {event.location_name}")
        message_lines.append(f"⚠️ 심각도: {severity}")
        message_lines.append("─" * 20)
    
    message_lines.append("💡 교통 상황을 미리 확인하시고 우회 경로를 고려해보세요!")
    
    message = "\n".join(message_lines)
    
    # Event API 요청 데이터 구성
    event_data = EventAPIRequest(
        event=Event(
            name="route_rally_alert",  # 경로 집회 알림 이벤트
            data=EventData(text=message)
        ),
        user=[EventUser(
            type="appUserId",
            id=user_id
        )],
        params={
            "alert_type": "route_events",
            "event_count": event_count,
            "timestamp": str(int(time.time()))
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
                json=event_data.model_dump()
            )
            
            if response.status_code == 200:
                result = response.json()
                logger.info(f"자동 집회 알림 전송 성공: {user_id}, {event_count}개 집회")
                return {
                    "success": True,
                    "task_id": result.get("taskId"),
                    "event_count": event_count
                }
            else:
                logger.error(f"자동 집회 알림 전송 실패: {response.status_code}, {response.text}")
                return {"success": False, "error": response.text}
                
    except Exception as e:
        logger.error(f"자동 집회 알림 전송 중 오류: {str(e)}")
        return {"success": False, "error": str(e)}

@app.post("/events", response_model=EventResponse)
async def create_event(event: EventCreate, db: sqlite3.Connection = Depends(get_db)):
    """새로운 집회 정보를 등록"""
    cursor = db.cursor()
    
    cursor.execute('''
        INSERT INTO events (title, description, location_name, location_address, 
                          latitude, longitude, start_date, end_date, category, severity_level)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        event.title, event.description, event.location_name, event.location_address,
        event.latitude, event.longitude, event.start_date, event.end_date,
        event.category, event.severity_level
    ))
    
    event_id = cursor.lastrowid
    db.commit()
    
    # 생성된 집회 정보 반환
    cursor.execute('SELECT * FROM events WHERE id = ?', (event_id,))
    row = cursor.fetchone()
    
    return EventResponse(
        id=row[0], title=row[1], description=row[2], location_name=row[3],
        location_address=row[4], latitude=row[5], longitude=row[6],
        start_date=datetime.fromisoformat(row[7]),
        end_date=datetime.fromisoformat(row[8]) if row[8] else None,
        category=row[9], severity_level=row[10], status=row[11],
        created_at=datetime.fromisoformat(row[12]),
        updated_at=datetime.fromisoformat(row[13])
    )

@app.get("/events", response_model=List[EventResponse])
async def get_events(
    status: str = "active",
    category: Optional[str] = None,
    limit: int = 100,
    db: sqlite3.Connection = Depends(get_db)
):
    """집회 목록 조회 (필터링 지원)"""
    cursor = db.cursor()
    
    query = "SELECT * FROM events WHERE status = ?"
    params = [status]
    
    if category:
        query += " AND category = ?"
        params.append(category)
    
    query += " ORDER BY start_date DESC LIMIT ?"
    params.append(limit)
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    
    events = []
    for row in rows:
        events.append(EventResponse(
            id=row[0], title=row[1], description=row[2], location_name=row[3],
            location_address=row[4], latitude=row[5], longitude=row[6],
            start_date=datetime.fromisoformat(row[7]),
            end_date=datetime.fromisoformat(row[8]) if row[8] else None,
            category=row[9], severity_level=row[10], status=row[11],
            created_at=datetime.fromisoformat(row[12]),
            updated_at=datetime.fromisoformat(row[13])
        ))
    
    return events

@app.get("/check-route-events/{user_id}", response_model=RouteEventCheck)
async def check_user_route_events(
    user_id: str, 
    auto_notify: bool = False,  # 자동 알림 여부
    db: sqlite3.Connection = Depends(get_db)
):
    """사용자의 경로상에 있는 집회들을 확인"""
    cursor = db.cursor()
    
    # 사용자 경로 정보 조회
    cursor.execute('''
        SELECT departure_name, departure_address, departure_x, departure_y,
               arrival_name, arrival_address, arrival_x, arrival_y
        FROM users WHERE bot_user_key = ?
    ''', (user_id,))
    
    user_row = cursor.fetchone()
    if not user_row or not all([user_row[2], user_row[3], user_row[6], user_row[7]]):
        raise HTTPException(status_code=404, detail="사용자의 경로 정보를 찾을 수 없습니다.")
    
    dep_lon, dep_lat, arr_lon, arr_lat = user_row[2], user_row[3], user_row[6], user_row[7]
    
    # 활성 집회 목록 조회
    cursor.execute('''
        SELECT * FROM events 
        WHERE status = 'active' AND start_date > datetime('now')
        ORDER BY start_date
    ''')
    
    events_rows = cursor.fetchall()
    route_events = []
    
    # 카카오 Mobility API로 실제 경로 좌표 가져오기
    route_coordinates = await get_route_coordinates(dep_lon, dep_lat, arr_lon, arr_lat)
    
    # 각 집회가 실제 경로 근처에 있는지 정확히 확인
    for row in events_rows:
        event_lat, event_lon = row[5], row[6]
        
        # 정확한 경로 기반 검사 (Mobility API 사용)
        if route_coordinates and is_event_near_route_accurate(route_coordinates, event_lat, event_lon):
            route_events.append(EventResponse(
                id=row[0], title=row[1], description=row[2], location_name=row[3],
                location_address=row[4], latitude=row[5], longitude=row[6],
                start_date=datetime.fromisoformat(row[7]),
                end_date=datetime.fromisoformat(row[8]) if row[8] else None,
                category=row[9], severity_level=row[10], status=row[11],
                created_at=datetime.fromisoformat(row[12]),
                updated_at=datetime.fromisoformat(row[13])
            ))
        # Mobility API 실패 시 기존 직선 방식으로 폴백
        elif not route_coordinates and is_point_near_route(dep_lat, dep_lon, arr_lat, arr_lon, event_lat, event_lon):
            logger.warning("Mobility API 실패로 직선 거리 방식 사용")
            route_events.append(EventResponse(
                id=row[0], title=row[1], description=row[2], location_name=row[3],
                location_address=row[4], latitude=row[5], longitude=row[6],
                start_date=datetime.fromisoformat(row[7]),
                end_date=datetime.fromisoformat(row[8]) if row[8] else None,
                category=row[9], severity_level=row[10], status=row[11],
                created_at=datetime.fromisoformat(row[12]),
                updated_at=datetime.fromisoformat(row[13])
            ))
    
    route_info = {
        "departure": {"name": user_row[0], "address": user_row[1], "lat": dep_lat, "lon": dep_lon},
        "arrival": {"name": user_row[4], "address": user_row[5], "lat": arr_lat, "lon": arr_lon}
    }
    
    # 자동 알림 전송 (옵션)
    if auto_notify and route_events:
        await auto_notify_route_events(user_id, route_events)
        logger.info(f"사용자 {user_id}에게 {len(route_events)}개 집회 자동 알림 전송")
    
    return RouteEventCheck(
        user_id=user_id,
        events_found=route_events,
        route_info=route_info,
        total_events=len(route_events)
    )

@app.post("/auto-check-all-routes")
async def auto_check_all_routes(db: sqlite3.Connection = Depends(get_db)):
    """
    모든 사용자의 경로를 확인하고 집회 발견 시 자동 알림 전송
    Phase 9.4: 자동화 시스템의 핵심 API
    """
    cursor = db.cursor()
    
    # 경로 정보가 등록된 모든 활성 사용자 조회
    cursor.execute('''
        SELECT bot_user_key FROM users 
        WHERE active = 1 
        AND departure_x IS NOT NULL 
        AND departure_y IS NOT NULL
        AND arrival_x IS NOT NULL 
        AND arrival_y IS NOT NULL
    ''')
    
    users = cursor.fetchall()
    results = []
    
    logger.info(f"경로 기반 집회 확인 시작: {len(users)}명 사용자")
    
    for user_row in users:
        user_id = user_row[0]
        
        try:
            # 각 사용자의 경로 확인 (자동 알림 포함)
            result = await check_user_route_events(user_id, auto_notify=True, db=db)
            
            results.append({
                "user_id": user_id,
                "events_found": len(result.events_found),
                "auto_notified": len(result.events_found) > 0,
                "status": "success"
            })
            
            if result.events_found:
                logger.info(f"사용자 {user_id}: {len(result.events_found)}개 집회 감지 및 알림 전송")
                
        except Exception as e:
            logger.error(f"사용자 {user_id} 경로 확인 실패: {str(e)}")
            results.append({
                "user_id": user_id,
                "events_found": 0,
                "auto_notified": False,
                "status": "failed",
                "error": str(e)
            })
    
    summary = {
        "total_users": len(users),
        "successful_checks": len([r for r in results if r["status"] == "success"]),
        "users_with_events": len([r for r in results if r["events_found"] > 0]),
        "total_notifications_sent": len([r for r in results if r["auto_notified"]]),
        "results": results
    }
    
    logger.info(f"경로 기반 집회 확인 완료: {summary['users_with_events']}명에게 알림 전송")
    
    return summary