"""이벤트/집회 관리 서비스"""
import asyncio
import logging
import sqlite3
from datetime import datetime
from typing import List, Dict, Any, Optional
from app.models.event import EventCreate, EventResponse, RouteEventCheck
from app.utils.geo_utils import haversine_distance, get_route_coordinates, is_event_near_route_accurate, is_point_near_route
from app.database.connection import DATABASE_PATH

logger = logging.getLogger(__name__)


class EventService:
    """이벤트/집회 관리 비즈니스 로직"""

    @staticmethod
    def create_event(event_data: EventCreate, db: sqlite3.Connection) -> Dict[str, Any]:
        """
        새로운 집회/이벤트 생성
        
        Args:
            event_data: 이벤트 생성 데이터
            db: 데이터베이스 연결
            
        Returns:
            Dict: 생성 결과
        """
        try:
            cursor = db.cursor()
            cursor.execute('''
                INSERT INTO events (title, description, location_name, location_address,
                                  latitude, longitude, start_date, end_date, category, 
                                  severity_level, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                event_data.title,
                event_data.description,
                event_data.location_name,
                event_data.location_address,
                event_data.latitude,
                event_data.longitude,
                event_data.start_date,
                event_data.end_date,
                event_data.category,
                event_data.severity_level,
                'active'  # 기본값으로 'active' 설정
            ))
            
            event_id = cursor.lastrowid
            db.commit()
            
            logger.info(f"새 집회 생성 완료: {event_id} - {event_data.title}")
            return {"success": True, "event_id": event_id}
            
        except Exception as e:
            logger.error(f"집회 생성 실패: {str(e)}")
            return {"success": False, "error": str(e)}

    @staticmethod
    def get_events(
        category: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
        db: sqlite3.Connection = None
    ) -> List[EventResponse]:
        """
        집회 목록 조회
        
        Args:
            category: 카테고리 필터
            status: 상태 필터
            limit: 조회 제한
            db: 데이터베이스 연결
            
        Returns:
            List[EventResponse]: 집회 목록
        """
        try:
            cursor = db.cursor()
            
            # 쿼리 조건 구성
            where_conditions = []
            params = []
            
            if category:
                where_conditions.append("category = ?")
                params.append(category)
            
            if status:
                where_conditions.append("status = ?")
                params.append(status)
            
            where_clause = " WHERE " + " AND ".join(where_conditions) if where_conditions else ""
            
            query = f'''
                SELECT id, title, description, location_name, location_address,
                       latitude, longitude, start_date, end_date, category,
                       severity_level, status, created_at, updated_at
                FROM events{where_clause}
                ORDER BY start_date DESC
                LIMIT ?
            '''
            
            params.append(limit)
            cursor.execute(query, params)
            
            events = []
            for row in cursor.fetchall():
                events.append(EventResponse(
                    id=row[0],
                    title=row[1],
                    description=row[2],
                    location_name=row[3],
                    location_address=row[4],
                    latitude=row[5],
                    longitude=row[6],
                    start_date=row[7],
                    end_date=row[8],
                    category=row[9],
                    severity_level=row[10],
                    status=row[11],
                    created_at=row[12],
                    updated_at=row[13]
                ))
            
            return events
            
        except Exception as e:
            logger.error(f"집회 목록 조회 실패: {str(e)}")
            return []

    @staticmethod
    async def check_route_events(
        user_id: str,
        auto_notify: bool = False,
        db: sqlite3.Connection = None
    ) -> RouteEventCheck:
        """
        사용자 경로 기반 집회 확인

        Args:
            user_id: 사용자 ID (plusfriend_user_key 권장)
            auto_notify: 자동 알림 여부
            db: 데이터베이스 연결

        Returns:
            RouteEventCheck: 경로 확인 결과
        """
        try:
            cursor = db.cursor()

            # 사용자 경로 정보 조회 (plusfriend_user_key 우선 조회)
            cursor.execute('''
                SELECT departure_name, departure_address, departure_x, departure_y,
                       arrival_name, arrival_address, arrival_x, arrival_y
                FROM users WHERE plusfriend_user_key = ? OR bot_user_key = ?
            ''', (user_id, user_id))
            
            user_row = cursor.fetchone()
            if not user_row or not all([user_row[2], user_row[3], user_row[6], user_row[7]]):
                return RouteEventCheck(
                    user_id=user_id,
                    events_found=[],
                    route_info={},
                    total_events=0
                )
            
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
                # auto_notify_route_events 함수 호출
                from app.services.notification_service import NotificationService
                events_data = []
                for event in route_events:
                    events_data.append({
                        "id": event.id,
                        "title": event.title,
                        "location": event.location_name,
                        "latitude": event.latitude,
                        "longitude": event.longitude,
                        "start_date": event.start_date.isoformat(),
                        "category": event.category,
                        "severity_level": event.severity_level
                    })
                await NotificationService.send_route_alert(user_id, events_data)
                logger.info(f"사용자 {user_id}에게 {len(route_events)}개 집회 자동 알림 전송")
            
            return RouteEventCheck(
                user_id=user_id,
                events_found=route_events,
                route_info=route_info,
                total_events=len(route_events)
            )
            
        except Exception as e:
            logger.error(f"경로 집회 확인 실패 - {user_id}: {str(e)}")
            return RouteEventCheck(
                user_id=user_id,
                events_found=[],
                route_info={},
                total_events=0
            )

    @staticmethod
    async def scheduled_route_check() -> Dict[str, Any]:
        """
        매일 아침 자동 실행되는 경로 기반 집회 확인 함수
        - plusfriend_user_key 기반 조회
        - 조건에 맞는 사용자에게 일괄 전송

        Returns:
            Dict: 처리 결과
        """
        logger.info("=== 정기 집회 확인 시작 ===")

        try:
            # 데이터베이스 연결
            db = sqlite3.connect(DATABASE_PATH, check_same_thread=False)

            # 활성 사용자 조회 (plusfriend_user_key 필수!)
            cursor = db.cursor()
            cursor.execute('''
                SELECT plusfriend_user_key, departure_name, arrival_name
                FROM users
                WHERE active = 1
                  AND plusfriend_user_key IS NOT NULL
                  AND departure_x IS NOT NULL
                  AND departure_y IS NOT NULL
                  AND arrival_x IS NOT NULL
                  AND arrival_y IS NOT NULL
            ''')

            users = cursor.fetchall()
            total_notifications = 0

            logger.info(f"경로 등록된 사용자 {len(users)}명 확인 중...")

            # 조건별로 그룹화 (예: 출발지가 같은 사용자끼리)
            grouped_users = {}
            for user_row in users:
                plusfriend_key, departure, arrival = user_row

                # 경로 확인
                result = await EventService.check_route_events(plusfriend_key, auto_notify=False, db=db)

                if result.events_found:
                    # 조건별로 그룹화 (출발지 기준)
                    if departure not in grouped_users:
                        grouped_users[departure] = []
                    grouped_users[departure].append({
                        "plusfriend_key": plusfriend_key,
                        "events": [
                            {
                                "id": event.id,
                                "title": event.title,
                                "location": event.location_name,
                                "latitude": event.latitude,
                                "longitude": event.longitude,
                                "start_date": event.start_date.isoformat() if hasattr(event.start_date, 'isoformat') else str(event.start_date),
                                "category": event.category,
                                "severity_level": event.severity_level
                            }
                            for event in result.events_found
                        ]
                    })

            # Event API로 일괄 전송
            from app.services.notification_service import NotificationService
            for departure, user_group in grouped_users.items():
                user_ids = [u["plusfriend_key"] for u in user_group]
                events_data = user_group[0]["events"]  # 공통 이벤트

                logger.info(f"📢 출발지 '{departure}' 사용자 {len(user_ids)}명에게 알림 전송")

                # Event API 호출 (type=plusfriendUserKey)
                await NotificationService.send_bulk_alert(
                    user_ids=user_ids,
                    events_data=events_data,
                    id_type="plusfriendUserKey"  # ← 타입 명시!
                )

                total_notifications += len(user_ids)

            db.close()

            logger.info(f"=== 정기 집회 확인 완료: {total_notifications}명에게 알림 전송 ===")

            return {
                "success": True,
                "total_users": len(users),
                "notifications_sent": total_notifications
            }

        except Exception as e:
            logger.error(f"정기 집회 확인 중 오류 발생: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }

    @staticmethod
    def get_upcoming_events(
        limit: int = 5,
        db: sqlite3.Connection = None
    ) -> List[EventResponse]:
        """
        다가오는 집회 목록 조회 (오늘 포함 이후)
        
        Args:
            limit: 조회 제한 (기본 5개)
            db: 데이터베이스 연결
            
        Returns:
            List[EventResponse]: 다가오는 집회 목록
        """
        try:
            cursor = db.cursor()
            
            cursor.execute('''
                SELECT id, title, description, location_name, location_address,
                       latitude, longitude, start_date, end_date, category,
                       severity_level, status, created_at, updated_at
                FROM events
                WHERE status = 'active' AND date(start_date) >= date('now')
                ORDER BY start_date ASC
                LIMIT ?
            ''', (limit,))
            
            events = []
            for row in cursor.fetchall():
                events.append(EventResponse(
                    id=row[0],
                    title=row[1],
                    description=row[2],
                    location_name=row[3],
                    location_address=row[4],
                    latitude=row[5],
                    longitude=row[6],
                    start_date=row[7],
                    end_date=row[8],
                    category=row[9],
                    severity_level=row[10],
                    status=row[11],
                    created_at=row[12],
                    updated_at=row[13]
                ))
            
            return events
            
        except Exception as e:
            logger.error(f"다가오는 집회 목록 조회 실패: {str(e)}")
            return []

    @staticmethod
    def get_today_events(
        db: sqlite3.Connection = None
    ) -> List[EventResponse]:
        """
        오늘 진행되는 집회 목록 조회
        
        Args:
            db: 데이터베이스 연결
            
        Returns:
            List[EventResponse]: 오늘 집회 목록
        """
        try:
            cursor = db.cursor()
            
            cursor.execute('''
                SELECT id, title, description, location_name, location_address,
                       latitude, longitude, start_date, end_date, category,
                       severity_level, status, created_at, updated_at
                FROM events
                WHERE status = 'active' AND date(start_date) = date('now')
                ORDER BY start_date ASC
            ''')
            
            events = []
            for row in cursor.fetchall():
                events.append(EventResponse(
                    id=row[0],
                    title=row[1],
                    description=row[2],
                    location_name=row[3],
                    location_address=row[4],
                    latitude=row[5],
                    longitude=row[6],
                    start_date=row[7],
                    end_date=row[8],
                    category=row[9],
                    severity_level=row[10],
                    status=row[11],
                    created_at=row[12],
                    updated_at=row[13]
                ))
            
            return events
            
        except Exception as e:
            logger.error(f"오늘 집회 목록 조회 실패: {str(e)}")
            return []