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
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

# 환경변수 로드
load_dotenv()

# 기본 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# 스케줄러 초기화
scheduler = AsyncIOScheduler()

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
        cursor.execute('ALTER TABLE users ADD COLUMN marked_bus TEXT')
        cursor.execute('ALTER TABLE users ADD COLUMN language TEXT')
        logger.info("경로 정보 및 초기 설정 컬럼들이 성공적으로 추가되었습니다.")
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

# --------------------------
# Phase 9.4: 스케줄링 시스템
# --------------------------

async def scheduled_route_check():
    """
    매일 아침 7시 자동 실행되는 경로 기반 집회 확인 함수
    모든 사용자의 경로를 확인하고 집회 발견 시 자동 알림 전송
    """
    logger.info("=== 정기 집회 확인 시작 ===")
    
    try:
        # 데이터베이스 연결
        db = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        
        # auto_check_all_routes 로직 실행
        cursor = db.cursor()
        cursor.execute('''
            SELECT bot_user_key FROM users 
            WHERE active = 1 
            AND departure_x IS NOT NULL 
            AND departure_y IS NOT NULL
            AND arrival_x IS NOT NULL 
            AND arrival_y IS NOT NULL
        ''')
        
        users = cursor.fetchall()
        total_notifications = 0
        
        logger.info(f"경로 등록된 사용자 {len(users)}명 확인 중...")
        
        for user_row in users:
            user_id = user_row[0]
            
            try:
                # 각 사용자의 경로 확인 (자동 알림 포함)
                result = await check_user_route_events(user_id, auto_notify=True, db=db)
                
                if result.events_found:
                    total_notifications += 1
                    logger.info(f"✅ {user_id}: {len(result.events_found)}개 집회 감지 및 알림 전송")
                    
            except Exception as e:
                logger.error(f"❌ 사용자 {user_id} 처리 실패: {str(e)}")
        
        db.close()
        
        logger.info(f"=== 정기 집회 확인 완료: {total_notifications}명에게 알림 전송 ===")
        
    except Exception as e:
        logger.error(f"정기 집회 확인 중 오류 발생: {str(e)}")

# 중복된 이벤트 핸들러 제거됨 - 파일 하단의 이벤트 핸들러 사용

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

class InitialSetupRequest(BaseModel):
    userRequest: UserRequest
    departure: Optional[str] = None
    arrival: Optional[str] = None
    marked_bus: Optional[str] = None
    language: Optional[str] = None

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
                        "text": (
                            "안녕하세요! KT 종로구 집회 알림 서비스입니다.\n\n"
                            "📢 서비스가 정상적으로 활성화되었습니다.\n"
                            "🚗 출퇴근 경로를 등록하시면 경로상 집회 정보를 안내해드립니다.\n\n"
                            "💡 [🚗 출퇴근 경로 등록하기] 버튼을 눌러 시작해보세요!"
                        )
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
            type="botUserKey",  # open_id는 appUserId로 전송
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
            user=[EventUser(type="botUserKey", id=user_key) for user_key in batch],
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
            user=[EventUser(type="botUserKey", id=user_key) for user_key in batch],
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
    
    # id_type 검증 - app_user_id와 open_id 지원
    if id_type not in ["app_user_id", "open_id"]:
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
    logger.info(f"🔍 save_user_info 요청 body: {body}")
    
    # 카카오톡에서 온 요청인지 확인
    if 'userRequest' in body:
        user_id = body['userRequest']['user']['id']
    else:  # 로컬 테스트용
        user_id = body.get('userId', 'test-user')
    
    # botUserKey를 받은 경우 사용자 생성/업데이트
    if 'userRequest' in body:
        save_or_update_user(user_id, f"경로 등록: {body.get('action', {}).get('params', {}).get('departure', '')} → {body.get('action', {}).get('params', {}).get('arrival', '')}")
    
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
    
    if event_count == 1:
        event = events_found[0]
        start_date = event.start_date.strftime('%m월 %d일 %H:%M')
        
        message_lines = [
            f"🚨 설정하신 출퇴근 경로에 집회가 예정되어 있습니다!\n",
            f"📍 {event.title}",
            f"📅 {start_date}",
            f"📍 위치: {event.location_name}\n",
            "⚠️ 교통 지연이 예상되니 우회 경로를 고려해보세요!",
            "🕐 평소보다 10-15분 일찍 출발하시길 권합니다."
        ]
    else:
        message_lines = [
            f"🚨 설정하신 출퇴근 경로에 {event_count}개의 집회가 예정되어 있습니다!\n"
        ]
        
        for i, event in enumerate(events_found, 1):
            start_date = event.start_date.strftime('%m월 %d일 %H:%M')
            message_lines.append(f"{i}. {event.title} ({start_date})")
        
        message_lines.extend([
            "\n⚠️ 교통 지연이 예상되니 우회 경로를 고려해보세요!",
            "🕐 평소보다 15-20분 일찍 출발하시길 권합니다."
        ])
    
    message = "\n".join(message_lines)
    
    # Event API 요청 데이터 구성
    event_data = EventAPIRequest(
        event=Event(
            name="morning_demo_alarm",  # 기존 등록된 이벤트 사용
            data=EventData(text=message)
        ),
        user=[EventUser(
            type="botUserKey",
            id=user_id
        )],
        params={
            "location": "",
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
        # 디버그: Event API 요청 데이터 로깅
        logger.info(f"🔍 Event API 요청 - 사용자: {user_id}")
        logger.info(f"🔍 이벤트명: {event_data.event.name}")  
        logger.info(f"🔍 메시지 길이: {len(message)}자")
        logger.info(f"🔍 메시지 미리보기: {message[:100]}...")
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers=headers,
                json=event_data.model_dump()
            )
            
            logger.info(f"🔍 Event API 응답: {response.status_code}")
            if response.status_code == 200:
                result = response.json()
                task_id = result.get("taskId")
                status = result.get("status")
                
                if status == "SUCCESS":
                    logger.info(f"자동 집회 알림 요청 성공: {user_id}, {event_count}개 집회, taskId: {task_id}")
                    # TODO: taskId로 실제 발송 결과 확인 로직 추가 필요
                else:
                    logger.warning(f"자동 집회 알림 요청 실패: {user_id}, status: {status}")
                
                return {
                    "success": status == "SUCCESS",
                    "task_id": task_id,
                    "status": status,
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

@app.post("/manual-schedule-test")
async def manual_schedule_test():
    """
    스케줄링 함수를 수동으로 실행하여 테스트
    매일 7시 자동 실행과 동일한 로직
    """
    logger.info("📋 수동 스케줄 테스트 시작")
    await scheduled_route_check()
    return {"message": "스케줄 테스트 완료", "status": "success"}

@app.get("/scheduler-status")
async def get_scheduler_status():
    """
    스케줄러 상태 및 다음 실행 시간 확인
    """
    if not scheduler.running:
        return {"status": "stopped", "message": "스케줄러가 실행 중이지 않습니다"}
    
    jobs = []
    for job in scheduler.get_jobs():
        jobs.append({
            "id": job.id,
            "name": job.name,
            "next_run_time": str(job.next_run_time) if job.next_run_time else None,
            "trigger": str(job.trigger)
        })
    
    return {
        "status": "running",
        "message": "스케줄러가 정상 동작 중입니다",
        "jobs": jobs
    }

# ──────────────────────────────────────────────────────────────────────
# 집회 데이터 자동 크롤링 시스템 (MinhaKim02 동료 시스템 기반 완전 통합)
# Original crawling algorithms by MinhaKim02: https://github.com/MinhaKim02/protest-crawling-database
# Integration and DB layer by hoonly01
# ──────────────────────────────────────────────────────────────────────

import re
import os
import json
import time
import urllib.parse
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple, Any
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

# pdfminer.six 필요
try:
    from pdfminer.high_level import extract_text
except ImportError as e:
    try:
        from pdfminer_high_level import extract_text  # intentional failover name
    except ImportError:
        raise SystemExit("pdfminer.six가 필요합니다. 설치 후: pip install pdfminer.six") from e

# SMPA(서울경찰청) 크롤링 상수 및 유틸리티 (원본 by MinhaKim02)
BASE_URL = "https://www.smpa.go.kr"
LIST_URL = f"{BASE_URL}/user/nd54882.do"  # 서울경찰청 > 오늘의 집회
# DEFAULT_VWORLD_KEY 제거됨 - 보안상 환경변수만 사용
VWORLD_SEARCH_URL = "https://api.vworld.kr/req/search"

# 서울 경계 박스 및 종로 키워드 (원본 by MinhaKim02)
SEOUL_BBOX = (37.413, 37.715, 126.734, 127.269)  # (lat_min, lat_max, lon_min, lon_max)
JONGNO_KEYWORDS = [
    "종로", "종로구", "종로구청",
    "광화문", "광화문광장", "세종문화회관", "정부서울청사", "경복궁",
    "삼청동", "청운동", "부암동", "인사동", "익선동", "계동", "와룡동", "사직로", "율곡로", "자하문로",
    "경복궁역", "광화문역", "안국역", "종각역", "종로3가역", "종로5가역",
    "흥인지문",
]

def sanitize_filename(name: str, limit: int = 120) -> str:
    """파일명 안전화 (원본 by MinhaKim02)"""
    safe = re.sub(r'[^\w가-힣\.-]+', '_', name)
    return safe[:limit].strip('._')

def filename_from_cd(cd: str) -> Optional[str]:
    """Content-Disposition 헤더에서 파일명 추출 (원본 by MinhaKim02)"""
    if not cd:
        return None
    m_star = re.search(r"filename\*\s*=\s*[^']*'[^']*'([^;]+)", cd, re.I)
    if m_star:
        return urllib.parse.unquote(m_star.group(1))
    m = re.search(r'filename\s*=\s*"([^"]+)"', cd, re.I)
    if m:
        return m.group(1)
    m2 = re.search(r'filename\s*=\s*([^;]+)', cd, re.I)
    if m2:
        return m2.group(1).strip()
    return None

def parse_goBoardView(href: str) -> Optional[Tuple[str, str, str]]:
    """goBoardView 자바스크립트 함수 인자 파싱 (원본 by MinhaKim02)"""
    m = re.search(r"goBoardView\('([^']+)'\s*,\s*'([^']+)'\s*,\s*'(\d+)'\)", href)
    if not m:
        return None
    return m.group(1), m.group(2), m.group(3)

def build_view_urls(board_no: str) -> List[str]:
    """게시판 뷰 URL 생성 (원본 by MinhaKim02)"""
    return [
        f"{BASE_URL}/user/nd54882.do?View&boardNo={board_no}",
        f"{BASE_URL}/user/nd54882.do?dmlType=View&boardNo={board_no}",
    ]

def extract_ymd_from_title(title: str) -> Optional[Tuple[str, str, str]]:
    """제목에서 YYMMDD를 찾아 (YYYY, MM, DD)로 변환 (원본 by MinhaKim02)"""
    if not title:
        return None
    m = re.search(r'(\d{2})(\d{2})(\d{2})', title)
    if not m:
        return None
    yy, mm, dd = m.group(1), m.group(2), m.group(3)
    yyyy = f"20{yy}"
    return (yyyy, mm, dd)

def _current_title_pattern() -> Tuple[str, str]:
    """오늘 날짜 기반 제목 패턴 생성 (원본 by MinhaKim02)"""
    now_kst = datetime.now(ZoneInfo("Asia/Seoul"))
    current_date = now_kst.strftime("%y%m%d")
    weekdays = ["월", "화", "수", "목", "금", "토", "일"]
    current_day = weekdays[now_kst.weekday()]
    return current_date, f"오늘의 집회 {current_date} {current_day}"

async def get_today_post_info(session: requests.Session, list_url: str = LIST_URL) -> Tuple[str, str]:
    """
    목록 페이지에서 오늘자 게시글의 뷰 URL과 제목을 반환 (원본 by MinhaKim02)
    Integration: httpx → requests session for FastAPI compatibility
    """
    current_date, expected_full = _current_title_pattern()
    r = session.get(list_url, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    tbody = soup.select_one("#subContents > div > div.inContent > table > tbody")
    targets = tbody.select("a[href^='javascript:goBoardView']") if tbody \
        else soup.select("a[href^='javascript:goBoardView']")

    target_link = None
    target_title = None
    for a in targets:
        title = a.get_text(strip=True) or (a.find_parent('td').get_text(strip=True) if a.find_parent('td') else "")
        href = a.get("href", "")
        if expected_full in title or f"오늘의 집회 {current_date}" in title:
            target_link = href
            target_title = title
            break

    if not target_link:
        raise RuntimeError("오늘 날짜 게시글을 찾지 못했습니다.")

    parsed = parse_goBoardView(target_link)
    if not parsed:
        raise RuntimeError("goBoardView 인자를 파싱하지 못했습니다.")
    _, _, board_no = parsed

    for url in build_view_urls(board_no):
        resp = session.get(url, timeout=20)
        if resp.ok and "html" in (resp.headers.get("Content-Type") or "").lower():
            return url, (target_title or "")
    raise RuntimeError("View 페이지 요청에 실패했습니다.")

def parse_attach_onclick(a_tag):
    """첨부파일 다운로드 onclick 파싱 (원본 by MinhaKim02)"""
    oc = a_tag.get("onclick", "")
    m = re.search(r"attachfileDownload\('([^']+)'\s*,\s*'(\d+)'\)", oc)
    if not m:
        return None
    return m.group(1), m.group(2)

def _is_pdf(resp: requests.Response, first: bytes) -> bool:
    """PDF 파일 여부 확인 (원본 by MinhaKim02)"""
    ct = (resp.headers.get("Content-Type") or "").lower()
    return first.startswith(b"%PDF-") or "pdf" in ct

async def download_from_view(session: requests.Session, view_url: str, out_dir: str = "temp") -> str:
    """
    게시글 뷰 페이지에서 PDF 첨부파일 다운로드 (원본 by MinhaKim02)
    Integration: 임시 디렉토리 사용, async 지원 추가
    """
    os.makedirs(out_dir, exist_ok=True)
    
    r = session.get(view_url, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    candidates = []
    for a in soup.find_all("a"):
        oc = a.get("onclick", "")
        if "attachfileDownload" in oc:
            txt = (a.get_text(strip=True) or "").lower()
            if "pdf" in txt or ".pdf" in txt:
                candidates.append(a)
    if not candidates:
        candidates = [a for a in soup.find_all("a") if "attachfileDownload" in (a.get("onclick", "") or "")]

    last_error = None
    for a_tag in candidates:
        parsed = parse_attach_onclick(a_tag)
        if not parsed:
            continue
        path, attach_no = parsed
        download_url = urllib.parse.urljoin(BASE_URL, path)
        try:
            with session.get(download_url, params={"attachNo": attach_no}, stream=True, timeout=30) as resp:
                resp.raise_for_status()
                it = resp.iter_content(chunk_size=8192)
                first_chunk = next(it, b"")
                if not _is_pdf(resp, first_chunk):
                    continue
                cd = resp.headers.get("Content-Disposition", "")
                filename = filename_from_cd(cd) or (a_tag.get_text(strip=True) or f"{attach_no}.pdf")
                root, ext = os.path.splitext(filename)
                if ext.lower() != ".pdf":
                    filename = root + ".pdf"
                filename = sanitize_filename(filename)
                save_path = os.path.join(out_dir, filename)
                with open(save_path, "wb") as f:
                    if first_chunk:
                        f.write(first_chunk)
                    for chunk in it:
                        if chunk:
                            f.write(chunk)
                return save_path
        except Exception as e:
            last_error = e
            continue
    if last_error:
        raise last_error
    raise RuntimeError("PDF 첨부 다운로드에 실패했습니다.")

async def download_today_pdf_with_title(out_dir: str = "temp") -> Tuple[str, str]:
    """
    오늘자 게시글의 PDF를 다운로드하고 제목과 함께 반환 (원본 by MinhaKim02)
    Integration: async support, 임시 디렉토리 사용
    """
    sess = requests.Session()
    sess.headers.update({
        'User-Agent': 'Mozilla/5.0',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'ko-KR,ko;q=0.9,en;q=0.8',
        'Referer': LIST_URL,
    })
    view_url, title_text = await get_today_post_info(sess, LIST_URL)
    pdf_path = await download_from_view(sess, view_url, out_dir=out_dir)
    return pdf_path, title_text

# PDF 파싱 로직 (원본 by MinhaKim02)
TIME_RE = re.compile(
    r'(?P<start>\d{1,2}\s*:\s*\d{2})\s*~\s*(?P<end>\d{1,2}\s*:\s*\d{2})',
    re.DOTALL
)

def _normalize_time_breaks(text: str) -> str:
    """PDF 텍스트의 시간 표기 정규화 (원본 by MinhaKim02)"""
    t = text
    t = re.sub(r'(\d{1,2})\s*\n\s*:\s*(\d{2})', r'\1:\2', t)  # "18\n:00" → "18:00"
    t = re.sub(r'(\d{1,2}\s*:\s*\d{2})\s*\n\s*~\s*\n\s*(\d{1,2}\s*:\s*\d{2})',
               r'\1~\2', t)  # "12:00\n~\n13:30" → "12:00~13:30"
    return t

def _collapse_korean_gaps(s: str) -> str:
    """한국어 텍스트 간격 정리 (원본 by MinhaKim02)"""
    def fix_token(tok: str) -> str:
        core = tok.replace(" ", "")
        if re.fullmatch(r'[가-힣]+', core) and 2 <= len(core) <= 5:
            return core
        return tok
    return " ".join(fix_token(t) for t in s.split())

def _extract_place_nodes(place_text: str) -> List[str]:
    """장소 텍스트에서 노드들 추출 (원본 by MinhaKim02)"""
    clean = re.sub(r'<[^>]+>', ' ', place_text)  # 보조정보 제거
    clean = re.sub(r'\s+', ' ', clean).strip()
    parts = re.split(r'\s*(?:→|↔|~)\s*', clean)  # 경로 구분자
    nodes = [p.strip() for p in parts if p.strip()]
    return nodes

def _extract_headcount(block: str) -> Optional[Tuple[str, Tuple[int, int]]]:
    """텍스트 블록에서 인원수 추출 (원본 by MinhaKim02)"""
    m = re.search(r'(\d{1,3}(?:,\d{3})*)\s*명', block)
    if m:
        return m.group(1), m.span()
    for m2 in re.finditer(r'(\d{1,3}(?:,\d{3})*|\d{3,})', block):
        num = m2.group(1)
        tail = block[m2.end(): m2.end()+1]
        if tail == '出':  # 출구 번호 오검출 방지
            continue
        try:
            val = int(num.replace(',', ''))
            if val >= 100 or (',' in num):
                return num, m2.span()
        except ValueError:
            pass
    return None

def parse_pdf(pdf_path: str, ymd: Optional[Tuple[str, str, str]] = None) -> List[Dict[str, str]]:
    """
    PDF 파일에서 집회 정보 파싱 (원본 by MinhaKim02)
    Integration: 우리 DB 스키마에 맞게 결과 형식 조정
    """
    raw = extract_text(pdf_path) or ""
    text = _normalize_time_breaks(raw)

    rows: List[Dict[str, str]] = []
    matches = list(TIME_RE.finditer(text))
    
    for i, m in enumerate(matches):
        start_t = re.sub(r'\s+', '', m.group('start'))
        end_t   = re.sub(r'\s+', '', m.group('end'))

        start_idx = m.end()
        end_idx = matches[i+1].start() if i+1 < len(matches) else len(text)
        chunk = text[start_idx:end_idx].strip()

        # 인원 추출
        head = _extract_headcount(chunk)
        if head:
            head_str, (h_s, h_e) = head
            head_clean = head_str.replace(',', '')
            before = chunk[:h_s]
            after  = chunk[h_e:]
        else:
            head_clean = ""
            before = chunk
            after  = ""

        # 장소(경로) 및 보조정보 추출
        place_block = before.strip()
        aux_in_place = " ".join(re.findall(r'<([^>]+)>', place_block))
        nodes = _extract_place_nodes(place_block)

        # 비고 = 인원 이후 잔여 + 장소 보조정보
        remark_raw = " ".join(x for x in [after.strip(), aux_in_place.strip()] if x)
        remark = _collapse_korean_gaps(re.sub(r'\s+', ' ', remark_raw)).strip()

        # 장소 컬럼: 1개면 문자열, 2개 이상이면 JSON 리스트 문자열
        if len(nodes) == 0:
            place_col = ""
        elif len(nodes) == 1:
            place_col = nodes[0]
        else:
            place_col = json.dumps(nodes, ensure_ascii=False)

        row = {
            "년": ymd[0] if ymd else "",
            "월": ymd[1] if ymd else "",
            "일": ymd[2] if ymd else "",
            "start_time": start_t,
            "end_time": end_t,
            "장소": place_col,
            "인원": head_clean,   # 숫자만
            "위도": "[]",         # 지오코딩에서 설정됨
            "경도": "[]",         # 지오코딩에서 설정됨
            "비고": remark,
        }
        rows.append(row)

    return rows

def convert_raw_events_to_db_format(raw_events: List[Dict]) -> List[Dict]:
    """
    파싱된 PDF 데이터를 우리 events 테이블 형식으로 변환
    Integration: MinhaKim02의 파싱 결과를 우리 DB 스키마로 변환
    
    PDF Parse Schema (by MinhaKim02):
    - 년,월,일,start_time,end_time,장소,인원,위도,경도,비고
    
    Our events table:
    - title, description, location_name, latitude, longitude, start_date, end_date, category
    """
    events = []
    conversion_errors = []
    
    for i, row in enumerate(raw_events):
        try:
            # 데이터 유효성 검증
            if not row or all(not str(v).strip() for v in row.values()):
                logger.warning(f"행 {i+1}: 빈 데이터 건너뜀")
                continue
            
            # 날짜/시간 변환 (더 강력한 검증)
            try:
                year = int(row.get('년', 2025))
                month = int(row.get('월', 1))
                day = int(row.get('일', 1))
                
                # 날짜 유효성 검증
                if not (2020 <= year <= 2030):
                    raise ValueError(f"연도가 범위를 벗어남: {year}")
                if not (1 <= month <= 12):
                    raise ValueError(f"월이 범위를 벗어남: {month}")
                if not (1 <= day <= 31):
                    raise ValueError(f"일이 범위를 벗어남: {day}")
                
                # 실제 날짜 검증
                datetime(year, month, day)
                
            except (ValueError, TypeError) as e:
                raise ValueError(f"날짜 변환 오류: {e}")
            
            # 시간 변환 (HH:MM 형식 검증)
            start_time_raw = row.get('start_time', '09:00').strip()
            end_time_raw = row.get('end_time', '18:00').strip()
            
            # 시간 형식 정규화
            def normalize_time(time_str):
                if ':' not in time_str:
                    return "09:00"
                parts = time_str.split(':')
                if len(parts) != 2:
                    return "09:00"
                try:
                    hour = int(parts[0])
                    minute = int(parts[1])
                    if not (0 <= hour <= 23) or not (0 <= minute <= 59):
                        return "09:00"
                    return f"{hour:02d}:{minute:02d}"
                except ValueError:
                    return "09:00"
            
            start_time = normalize_time(start_time_raw)
            end_time = normalize_time(end_time_raw)
            
            start_date = f"{year}-{month:02d}-{day:02d} {start_time}:00"
            end_date = f"{year}-{month:02d}-{day:02d} {end_time}:00"
            
            # 장소 파싱 개선 (JSON 배열 또는 단일 문자열)
            location_raw = str(row.get('장소', '')).strip()
            location_name = "알 수 없는 장소"  # 기본값
            
            if location_raw:
                if location_raw.startswith('[') and location_raw.endswith(']'):
                    # JSON 배열인 경우
                    try:
                        locations = json.loads(location_raw)
                        if isinstance(locations, list) and locations:
                            # 비어있지 않은 첫 번째 장소 찾기
                            for loc in locations:
                                if loc and str(loc).strip():
                                    location_name = str(loc).strip()
                                    break
                    except json.JSONDecodeError:
                        # JSON 파싱 실패 시 대체 방법
                        cleaned = location_raw.strip('[]').replace('"', '').replace("'", "")
                        parts = [p.strip() for p in cleaned.split(',') if p.strip()]
                        if parts:
                            location_name = parts[0]
                else:
                    # 단일 문자열인 경우
                    location_name = location_raw
            
            # 좌표 파싱 개선 (기본값으로 광화문 사용)
            latitude = 37.5709  # 광화문 기본 좌표
            longitude = 126.9769
            
            try:
                lat_raw = str(row.get('위도', '[37.5709]')).strip()
                lon_raw = str(row.get('경도', '[126.9769]')).strip()
                
                def parse_coordinate(coord_str, default_val):
                    if coord_str.startswith('[') and coord_str.endswith(']'):
                        # JSON 배열
                        try:
                            coords = json.loads(coord_str)
                            if isinstance(coords, list) and coords:
                                for coord in coords:
                                    if coord is not None:
                                        val = float(coord)
                                        # 한국 좌표 범위 검증
                                        if 33 <= val <= 39 or 124 <= val <= 132:
                                            return val
                        except (json.JSONDecodeError, ValueError, TypeError):
                            pass
                    else:
                        # 단일 값
                        try:
                            val = float(coord_str)
                            if 33 <= val <= 39 or 124 <= val <= 132:
                                return val
                        except (ValueError, TypeError):
                            pass
                    return default_val
                
                latitude = parse_coordinate(lat_raw, 37.5709)
                longitude = parse_coordinate(lon_raw, 126.9769)
                
            except Exception as coord_e:
                logger.warning(f"행 {i+1}: 좌표 파싱 오류, 기본값 사용: {coord_e}")
            
            # 설명 구성 개선
            description_parts = []
            
            participants = str(row.get('인원', '')).strip()
            if participants and participants.isdigit():
                description_parts.append(f"참가인원: {participants}명")
            elif participants:
                description_parts.append(f"참가인원: {participants}")
            
            remarks = str(row.get('비고', '')).strip()
            if remarks:
                description_parts.append(f"추가정보: {remarks}")
            
            description_parts.append("데이터 출처: SMPA(서울경찰청) PDF 크롤링")
            description_parts.append("크롤링 시스템: MinhaKim02 알고리즘 기반")
            description = " | ".join(description_parts)
            
            # 제목 생성 개선
            title = f"{location_name} 집회"
            if participants and participants.isdigit():
                title += f" (참가자 {participants}명)"
            
            # 주소 생성 개선
            location_address = f"서울특별시 종로구"
            if location_name != "알 수 없는 장소":
                location_address += f" {location_name}"
            
            event = {
                'title': title,
                'description': description,
                'location_name': location_name,
                'location_address': location_address,
                'latitude': latitude,
                'longitude': longitude, 
                'start_date': start_date,
                'end_date': end_date,
                'category': '집회',
                'severity_level': 2,  # 중간 수준
                'status': 'active'
            }
            
            events.append(event)
            
        except Exception as e:
            error_msg = f"행 {i+1} 변환 실패: {e}"
            logger.warning(error_msg)
            conversion_errors.append(error_msg)
            continue
    
    # 변환 결과 로깅
    logger.info(f"데이터 변환 완료: {len(events)}개 성공, {len(conversion_errors)}개 실패")
    if conversion_errors:
        logger.warning(f"변환 실패 상세: {conversion_errors[:5]}...")  # 처음 5개만 로그
    
    return events

async def crawl_and_parse_today_events() -> List[Dict]:
    """
    오늘 집회 정보를 크롤링하고 파싱하여 DB 형식으로 반환
    Complete integration: MinhaKim02's crawling + parsing → our DB format
    """
    temp_dir = "temp_pdfs"
    
    try:
        # 1. SMPA 사이트에서 오늘자 PDF 다운로드
        logger.info("SMPA 사이트에서 오늘자 PDF 다운로드 시작")
        pdf_path, title_text = await download_today_pdf_with_title(out_dir=temp_dir)
        logger.info(f"PDF 다운로드 성공: {pdf_path}")
        
        # 2. 제목에서 날짜 추출
        ymd = extract_ymd_from_title(title_text)
        if ymd:
            logger.info(f"제목에서 날짜 추출: {ymd[0]}-{ymd[1]}-{ymd[2]}")
        else:
            logger.warning("제목에서 날짜 추출 실패, 현재 날짜 사용")
            now = datetime.now()
            ymd = (str(now.year), f"{now.month:02d}", f"{now.day:02d}")
        
        # 3. PDF 파싱
        logger.info("PDF 파싱 시작")
        raw_events = parse_pdf(pdf_path, ymd=ymd)
        logger.info(f"PDF 파싱 완료: {len(raw_events)}개 집회 정보 추출")
        
        # 4. DB 형식으로 변환  
        logger.info("DB 형식으로 데이터 변환 시작")
        db_events = convert_raw_events_to_db_format(raw_events)
        logger.info(f"DB 형식 변환 완료: {len(db_events)}개 이벤트")
        
        # 5. 임시 파일 정리
        try:
            os.remove(pdf_path)
            logger.debug(f"임시 PDF 파일 삭제: {pdf_path}")
        except:
            pass
        
        return db_events
        
    except Exception as e:
        logger.error(f"집회 정보 크롤링 및 파싱 실패: {e}")
        return []
    finally:
        # 임시 디렉토리 정리
        try:
            if os.path.exists(temp_dir):
                import shutil
                shutil.rmtree(temp_dir)
        except:
            pass

async def crawl_and_sync_events_to_db(db: sqlite3.Connection) -> Dict:
    """
    SMPA 사이트에서 직접 크롤링하여 DB에 동기화
    Complete integration: 동료의 크롤링 알고리즘 + 우리 DB 시스템
    """
    try:
        # 1. 오늘 집회 정보 크롤링 및 파싱
        logger.info("집회 정보 크롤링 및 파싱 시작")
        new_events = await crawl_and_parse_today_events()
        
        if not new_events:
            return {
                "status": "warning", 
                "message": "크롤링된 이벤트가 없습니다",
                "total_crawled": 0,
                "inserted_new_events": 0
            }
        
        # 2. 트랜잭션으로 안전하게 DB 작업
        cursor = db.cursor()
        inserted_count = 0
        duplicate_count = 0
        error_count = 0
        
        try:
            db.execute("BEGIN TRANSACTION")
            
            for i, event in enumerate(new_events):
                try:
                    # 중복 체크 (제목과 날짜로 정확한 검사)
                    cursor.execute("""
                        SELECT id FROM events 
                        WHERE (
                            (location_name = ? AND DATE(start_date) = DATE(?))
                            OR (title = ? AND DATE(start_date) = DATE(?))
                        )
                        LIMIT 1
                    """, (
                        event['location_name'], event['start_date'],
                        event['title'], event['start_date']
                    ))
                    
                    existing = cursor.fetchone()
                    
                    if existing:
                        duplicate_count += 1
                        logger.debug(f"중복 이벤트 건너뜀: {event['title']}")
                    else:
                        # 새 이벤트 삽입
                        cursor.execute("""
                            INSERT INTO events 
                            (title, description, location_name, location_address, latitude, longitude, 
                             start_date, end_date, category, severity_level, status)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            event['title'], event['description'], event['location_name'], 
                            event['location_address'], event['latitude'], event['longitude'],
                            event['start_date'], event['end_date'], event['category'],
                            event['severity_level'], event['status']
                        ))
                        inserted_count += 1
                        logger.debug(f"새 이벤트 삽입: {event['title']}")
                        
                except sqlite3.Error as db_error:
                    error_count += 1
                    logger.error(f"이벤트 {i+1} DB 삽입 실패: {db_error}")
                    continue
            
            db.commit()
            logger.info(f"DB 트랜잭션 커밋 완료: {inserted_count}개 삽입")
            
        except Exception as tx_error:
            db.rollback()
            logger.error(f"DB 트랜잭션 실패, 롤백: {tx_error}")
            raise
        
        return {
            "status": "success",
            "message": f"집회 데이터 크롤링 및 동기화 완료",
            "total_crawled": len(new_events),
            "inserted_new_events": inserted_count,
            "duplicate_events": duplicate_count,
            "error_events": error_count,
            "data_source": "SMPA 직접 크롤링 (MinhaKim02 알고리즘 기반)",
            "sync_timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"집회 데이터 크롤링 및 동기화 실패: {e}")
        return {"status": "error", "message": str(e), "error_details": str(type(e).__name__)}

# 스케줄러에서 실행되는 자동 크롤링 함수 업데이트
async def scheduled_crawling_and_sync():
    """
    스케줄러에서 실행되는 집회 데이터 자동 크롤링 및 동기화
    매일 오전 8시 30분에 실행
    """
    logger.info("스케줄된 집회 데이터 크롤링 및 동기화 시작")
    
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    try:
        result = await crawl_and_sync_events_to_db(conn)
        logger.info(f"스케줄된 크롤링 및 동기화 결과: {result}")
        
        # 새로운 이벤트가 추가되었다면 사용자들에게 경로 체크 실행
        if result.get("status") == "success" and result.get("inserted_new_events", 0) > 0:
            logger.info("새 집회 데이터 발견, 경로 체크 실행")
            await scheduled_route_check()
            
    except Exception as e:
        logger.error(f"스케줄된 집회 데이터 크롤링 및 동기화 실패: {e}")
    finally:
        conn.close()

@app.post("/crawl-and-sync-events")
async def crawl_and_sync_events_endpoint():
    """
    수동으로 집회 데이터를 크롤링하고 DB에 동기화하는 엔드포인트
    Complete SMPA crawling integration
    """
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    try:
        result = await crawl_and_sync_events_to_db(conn)
        return result
    finally:
        conn.close()

@app.post("/upcoming-protests")
async def get_upcoming_protests_skill(request: KakaoRequest):
    """
    카카오 스킬: 예정된 집회 정보를 조회하는 엔드포인트
    """
    try:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        cursor = conn.cursor()
        
        # 오늘 포함 이후의 집회들 조회 (최대 5개)
        cursor.execute('''
            SELECT title, location_name, start_date, description
            FROM events 
            WHERE status = 'active' AND date(start_date) >= date('now')
            ORDER BY start_date ASC 
            LIMIT 5
        ''')
        
        events = cursor.fetchall()
        conn.close()
        
        if not events:
            response_text = "📅 현재 예정된 집회가 없습니다.\n\n안전한 하루 되세요! 😊"
        else:
            response_text = "📅 예정된 집회 정보\n\n"
            for event in events:
                title, location, start_date, description = event
                # 날짜 파싱 및 포매팅
                try:
                    date_obj = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
                    date_str = date_obj.strftime("%m월 %d일 %H:%M")
                except:
                    date_str = start_date[:16]  # 간단한 폴백
                
                response_text += f"🔹 {title}\n"
                response_text += f"📍 {location}\n"
                response_text += f"📅 {date_str}\n"
                if description:
                    # 설명에서 참가인원 정보만 추출
                    if "참가인원:" in description:
                        participant_info = description.split("참가인원:")[1].split("|")[0].strip()
                        response_text += f"👥 {participant_info}\n"
                response_text += "\n"
            
            response_text += "⚠️ 해당 지역을 지날 예정이시라면 교통 혼잡에 유의하세요!"
        
        return {
            "version": "2.0",
            "template": {
                "outputs": [
                    {
                        "simpleText": {
                            "text": response_text
                        }
                    }
                ]
            }
        }
        
    except Exception as e:
        logger.error(f"예정 집회 정보 조회 중 오류: {e}")
        return {
            "version": "2.0",
            "template": {
                "outputs": [
                    {
                        "simpleText": {
                            "text": "죄송합니다. 집회 정보를 가져오는 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요."
                        }
                    }
                ]
            }
        }

@app.post("/today-protests")
async def get_today_protests_skill(request: KakaoRequest):
    """
    카카오 스킬: 오늘 진행되는 집회 정보를 조회하는 엔드포인트
    """
    try:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        cursor = conn.cursor()
        
        # 오늘 날짜의 집회들 조회
        cursor.execute('''
            SELECT title, location_name, start_date, description
            FROM events 
            WHERE status = 'active' AND date(start_date) = date('now')
            ORDER BY start_date ASC
        ''')
        
        events = cursor.fetchall()
        conn.close()
        
        if not events:
            response_text = "📅 오늘 진행되는 집회가 없습니다.\n\n평온한 하루 되세요! 😌"
        else:
            response_text = "📅 오늘의 집회 정보\n\n"
            for event in events:
                title, location, start_date, description = event
                # 시간만 파싱
                try:
                    date_obj = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
                    time_str = date_obj.strftime("%H:%M")
                except:
                    time_str = start_date[11:16]  # 간단한 폴백
                
                response_text += f"🔹 {title}\n"
                response_text += f"📍 {location}\n"
                response_text += f"🕐 {time_str}\n"
                if description:
                    # 설명에서 참가인원 정보만 추출
                    if "참가인원:" in description:
                        participant_info = description.split("참가인원:")[1].split("|")[0].strip()
                        response_text += f"👥 {participant_info}\n"
                response_text += "\n"
            
            response_text += "⚠️ 해당 지역은 교통 혼잡이 예상되니 우회 경로를 이용하세요!"
        
        return {
            "version": "2.0",
            "template": {
                "outputs": [
                    {
                        "simpleText": {
                            "text": response_text
                        }
                    }
                ]
            }
        }
        
    except Exception as e:
        logger.error(f"오늘 집회 정보 조회 중 오류: {e}")
        return {
            "version": "2.0",
            "template": {
                "outputs": [
                    {
                        "simpleText": {
                            "text": "죄송합니다. 집회 정보를 가져오는 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요."
                        }
                    }
                ]
            }
        }
    


# 서버 시작 시 실행
@app.on_event("startup")
async def startup_event():
    """애플리케이션 시작 시 스케줄러 실행"""
    # DB 초기화
    init_db()
    
    scheduler.add_job(
        scheduled_crawling_and_sync,
        CronTrigger(hour=8, minute=30),
        id="morning_crawling",
        name="매일 08:30 집회 데이터 크롤링",
        replace_existing=True
    )
    scheduler.add_job(
        scheduled_route_check,
        CronTrigger(hour=7, minute=0),  
        id="morning_route_check",
        name="매일 07:00 경로 기반 집회 감지",
        replace_existing=True
    )
    if not scheduler.running:
        scheduler.start()
        logger.info("스케줄러가 시작되었습니다: 08:30 크롤링, 07:00 경로체크")
    else:
        logger.info("스케줄러가 이미 실행 중입니다")

@app.on_event("shutdown")
async def shutdown_event():
    """애플리케이션 종료 시 스케줄러 정리"""
    scheduler.shutdown()

@app.post("/initial-setup")
async def initial_setup_skill(request: Request):
    """
    카카오 스킬: 사용자 초기 설정 (출발지, 도착지, 관심 버스, 언어)
    """
    try:
        body = await request.json()
        logger.info(f"🔍 initial-setup 전체 요청 body: {body}")
        
        user_id = body['userRequest']['user']['id']
        logger.info(f"사용자 {user_id} 초기 설정 시작")
        
        # 파라미터 추출 (save_user_info와 동일한 방식)
        departure = body.get('departure') or body.get('action', {}).get('params', {}).get('departure', '')
        arrival = body.get('arrival') or body.get('action', {}).get('params', {}).get('arrival', '')
        marked_bus = body.get('marked_bus') or body.get('action', {}).get('params', {}).get('marked_bus', '')
        language = body.get('language') or body.get('action', {}).get('params', {}).get('language', '')
        
        logger.info(f"🔍 추출된 파라미터: departure={departure}, arrival={arrival}, marked_bus={marked_bus}, language={language}")
        
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        cursor = conn.cursor()
        
        # 사용자 존재 확인 및 생성
        cursor.execute('SELECT * FROM users WHERE bot_user_key = ?', (user_id,))
        user = cursor.fetchone()
        if not user:
            cursor.execute('''
                INSERT INTO users (bot_user_key, first_message_at, last_message_at, message_count, active)
                VALUES (?, ?, ?, 1, 1)
            ''', (user_id, datetime.now(), datetime.now()))
        
        # 설정할 항목들 추적
        updated_items = []
        
        # 출발지 설정
        if departure:
            try:
                location_info = await get_location_info(departure)
                if location_info:
                    cursor.execute('''
                        UPDATE users SET 
                        departure_name = ?, departure_address = ?, 
                        departure_x = ?, departure_y = ?,
                        route_updated_at = ?
                        WHERE bot_user_key = ?
                    ''', (
                        location_info['name'], location_info['address'],
                        float(location_info['x']), float(location_info['y']),
                        datetime.now(), user_id
                    ))
                    updated_items.append(f"📍 출발지: {location_info['name']}")
                    logger.info(f"출발지 설정 완료: {location_info['name']}")
                else:
                    updated_items.append(f"❌ 출발지 '{departure}' 검색 실패")
            except Exception as e:
                logger.error(f"출발지 설정 오류: {e}")
                updated_items.append(f"❌ 출발지 설정 오류")
        
        # 도착지 설정
        if arrival:
            try:
                location_info = await get_location_info(arrival)
                if location_info:
                    cursor.execute('''
                        UPDATE users SET 
                        arrival_name = ?, arrival_address = ?, 
                        arrival_x = ?, arrival_y = ?,
                        route_updated_at = ?
                        WHERE bot_user_key = ?
                    ''', (
                        location_info['name'], location_info['address'],
                        float(location_info['x']), float(location_info['y']),
                        datetime.now(), user_id
                    ))
                    updated_items.append(f"🎯 도착지: {location_info['name']}")
                    logger.info(f"도착지 설정 완료: {location_info['name']}")
                else:
                    updated_items.append(f"❌ 도착지 '{arrival}' 검색 실패")
            except Exception as e:
                logger.error(f"도착지 설정 오류: {e}")
                updated_items.append(f"❌ 도착지 설정 오류")
        
        # 관심 버스 노선 설정
        if marked_bus:
            # 버스 노선 유효성 검증 (숫자 또는 숫자+문자 조합)
            import re
            if re.match(r'^\d+[가-힣]?$|^[가-힣]+\d+$|^\d+$', marked_bus.strip()):
                cursor.execute('''
                    UPDATE users SET marked_bus = ? WHERE bot_user_key = ?
                ''', (marked_bus.strip(), user_id))
                updated_items.append(f"🚌 관심 버스: {marked_bus}")
                logger.info(f"관심 버스 설정 완료: {marked_bus}")
            else:
                updated_items.append(f"❌ 잘못된 버스 노선 번호: {marked_bus}")
        
        # 언어 설정
        if language:
            cursor.execute('''
                UPDATE users SET language = ? WHERE bot_user_key = ?
            ''', (language, user_id))
            updated_items.append(f"🌐 언어: {language}")
            logger.info(f"언어 설정 완료: {language}")
        
        conn.commit()
        conn.close()
        
        # 응답 메시지 구성 (텍스트 + 버튼)
        if updated_items:
            response_text = "🎉 설정이 완료되었습니다!\n\n이제부터 맞춤 알림 서비스를 이용하실 수 있어요 ✨\n\n저희 서비스를 이용해주셔서 감사합니다 🙌\n즐거운 하루 되세요! 🌿\n\n🔽 다른 기능을 보고 싶으시다면 아래 메뉴 버튼을 눌러주세요."
        else:
            response_text = "⚠️ 설정할 항목이 없습니다.\n\n출발지, 도착지, 관심 버스 노선, 언어 중 하나 이상을 입력해주세요."
        
        return {
            "version": "2.0",
            "template": {
                "outputs": [
                    {
                        "textCard": {
                            "title": "🎉 설정이 완료되었습니다!",
                            "description": "이제부터 맞춤 알림 서비스를 이용하실 수 있어요 ✨\n\n저희 서비스를 이용해주셔서 감사합니다 🙌\n즐거운 하루 되세요! 🌿\n\n🔽 다른 기능을 보고 싶으시다면 아래 메뉴 버튼을 눌러주세요.",
                            "buttons": [
                                {
                                    "action": "block",
                                    "label": "📋 메인 메뉴",
                                    "blockId": "689449da627dea71c7953060"
                                }
                            ]
                        }
                    }
                ]
            }
        }
        
    except Exception as e:
        logger.error(f"초기 설정 중 오류: {e}")
        return {
            "version": "2.0",
            "template": {
                "outputs": [
                    {
                        "simpleText": {
                            "text": "죄송합니다. 초기 설정 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요."
                        }
                    }
                ]
            }
        }

# DB 초기화 실행
init_db()
