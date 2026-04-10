"""이벤트/집회 관리 서비스"""
import asyncio
import logging
import sqlite3
from datetime import datetime
from typing import List, Dict, Any, Optional
from app.models.event import EventCreate, EventResponse, RouteEventCheck
from app.utils.geo_utils import haversine_distance, get_route_coordinates, is_event_near_route_accurate, is_point_near_route
from app.database.connection import get_db_connection
from app.services.notification_service import NotificationService

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
                    id=row["id"],
                    title=row["title"],
                    description=row["description"],
                    location_name=row["location_name"],
                    location_address=row["location_address"],
                    latitude=row["latitude"],
                    longitude=row["longitude"],
                    start_date=row["start_date"],
                    end_date=row["end_date"],
                    category=row["category"],
                    severity_level=row["severity_level"],
                    status=row["status"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"]
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
            if not user_row or any(user_row[k] is None for k in ("departure_x", "departure_y", "arrival_x", "arrival_y")):
                return RouteEventCheck(
                    user_id=user_id,
                    events_found=[],
                    route_info={},
                    total_events=0
                )

            dep_lon, dep_lat, arr_lon, arr_lat = user_row["departure_x"], user_row["departure_y"], user_row["arrival_x"], user_row["arrival_y"]
            
            # 활성 집회 목록 조회
            cursor.execute('''
                SELECT * FROM events 
                WHERE status = 'active' AND start_date > datetime('now', '+9 hours')
                ORDER BY start_date
            ''')
            
            events_rows = cursor.fetchall()
            route_events = []
            
            # 카카오 Mobility API로 실제 경로 좌표 가져오기
            route_coordinates = await get_route_coordinates(dep_lon, dep_lat, arr_lon, arr_lat)
            
            # 각 집회가 실제 경로 근처에 있는지 정확히 확인
            for row in events_rows:
                event_lat, event_lon = row["latitude"], row["longitude"]

                # 정확한 경로 기반 검사 (Mobility API 사용)
                if route_coordinates and is_event_near_route_accurate(route_coordinates, event_lat, event_lon):
                    route_events.append(EventResponse(
                        id=row["id"], title=row["title"], description=row["description"],
                        location_name=row["location_name"], location_address=row["location_address"],
                        latitude=row["latitude"], longitude=row["longitude"],
                        start_date=datetime.fromisoformat(row["start_date"]),
                        end_date=datetime.fromisoformat(row["end_date"]) if row["end_date"] else None,
                        category=row["category"], severity_level=row["severity_level"], status=row["status"],
                        created_at=datetime.fromisoformat(row["created_at"]),
                        updated_at=datetime.fromisoformat(row["updated_at"])
                    ))
                # Mobility API 실패 시 기존 직선 방식으로 폴백
                elif not route_coordinates and is_point_near_route(dep_lat, dep_lon, arr_lat, arr_lon, event_lat, event_lon):
                    logger.warning("Mobility API 실패로 직선 거리 방식 사용")
                    route_events.append(EventResponse(
                        id=row["id"], title=row["title"], description=row["description"],
                        location_name=row["location_name"], location_address=row["location_address"],
                        latitude=row["latitude"], longitude=row["longitude"],
                        start_date=datetime.fromisoformat(row["start_date"]),
                        end_date=datetime.fromisoformat(row["end_date"]) if row["end_date"] else None,
                        category=row["category"], severity_level=row["severity_level"], status=row["status"],
                        created_at=datetime.fromisoformat(row["created_at"]),
                        updated_at=datetime.fromisoformat(row["updated_at"])
                    ))
            
            route_info = {
                "departure": {"name": user_row["departure_name"], "address": user_row["departure_address"], "lat": dep_lat, "lon": dep_lon},
                "arrival": {"name": user_row["arrival_name"], "address": user_row["arrival_address"], "lat": arr_lat, "lon": arr_lon}
            }
            
            # 자동 알림 전송 (옵션)
            if auto_notify and route_events:
                # auto_notify_route_events 함수 호출
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
            safe_user_id = user_id or "unknown"
            logger.error(f"경로 집회 확인 실패 - {safe_user_id}: {str(e)}")
            return RouteEventCheck(
                user_id=safe_user_id,
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
        from app.services.alarm_status_service import AlarmStatusService

        logger.info("=== 정기 집회 확인 시작 ===")

        task_id = None
        try:
            task_id = AlarmStatusService.create_alarm_task(alarm_type="scheduled", total_recipients=0)
            AlarmStatusService.update_alarm_task_status(task_id, "processing")

            with get_db_connection() as db:
                # 활성 사용자 조회 (plusfriend_user_key 필수!)
                cursor = db.cursor()
                cursor.execute('''
                    SELECT plusfriend_user_key, departure_name, arrival_name
                    FROM users
                    WHERE active = 1
                      AND is_alarm_on = 1
                      AND plusfriend_user_key IS NOT NULL
                      AND departure_x IS NOT NULL
                      AND departure_y IS NOT NULL
                      AND arrival_x IS NOT NULL
                      AND arrival_y IS NOT NULL
                ''')

                users = cursor.fetchall()

                logger.info(f"경로 등록된 사용자 {len(users)}명 확인 중...")

                # 이벤트 결과가 정확히 일치하는 사용자끼리 그룹화
                grouped_users = {}
                for user_row in users:
                    plusfriend_key = user_row["plusfriend_user_key"]
                    departure = user_row["departure_name"]
                    arrival = user_row["arrival_name"]

                    # 경로 확인
                    result = await EventService.check_route_events(plusfriend_key, auto_notify=False, db=db)

                    if result.events_found:
                        # 해당 사용자에게 전달될 정확한 이벤트 집합을 키로 사용
                        event_key = tuple(sorted(event.id for event in result.events_found))

                        if event_key not in grouped_users:
                            grouped_users[event_key] = {
                                "user_ids": [],
                                "events_data": [
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
                            }

                        grouped_users[event_key]["user_ids"].append(plusfriend_key)

            # 실제 발송 대상 수(집회가 경로에 걸린 사용자) 기록
            actual_recipients = sum(len(g["user_ids"]) for g in grouped_users.values())
            AlarmStatusService.update_alarm_task_status(task_id, "processing", total_recipients=actual_recipients)

            # Event API로 일괄 전송
            total_success = 0
            total_fail = 0
            for event_key, group_data in grouped_users.items():
                user_ids = group_data["user_ids"]
                events_data = group_data["events_data"]

                logger.info(f"📢 수신 대상 {len(user_ids)}명에게 공통 이벤트({len(events_data)}건) 알림 전송")

                # Event API 호출 (type=plusfriendUserKey)
                send_result = await NotificationService.send_bulk_alert(
                    user_ids=user_ids,
                    events_data=events_data,
                    id_type="plusfriendUserKey"  # ← 타입 명시!
                )

                if not send_result.get("success", True):
                    total_fail += len(user_ids)
                else:
                    total_success += send_result.get("total_sent", 0)
                    total_fail += send_result.get("total_failed", 0)

            final_status = "completed" if total_fail == 0 else "partial"
            AlarmStatusService.update_alarm_task_status(
                task_id, final_status,
                successful_sends=total_success,
                failed_sends=total_fail,
            )

            logger.info(
                f"=== 정기 집회 확인 완료: 대상 {actual_recipients}명, 성공 {total_success}명, 실패 {total_fail}명 ==="
            )

            return {
                "success": True,
                "task_id": task_id,
                "total_users": len(users),
                "notifications_sent": total_success
            }

        except Exception as e:
            logger.error(f"정기 집회 확인 중 오류 발생: {str(e)}")
            if task_id:
                AlarmStatusService.update_alarm_task_status(task_id, "failed", error_messages=[str(e)])
            return {
                "success": False,
                "task_id": task_id,
                "error": str(e)
            }

    @staticmethod
    def get_upcoming_events(
        limit: int = 5,
        db: sqlite3.Connection = None
    ) -> List[EventResponse]:
        """
        다가오는 집회 목록 조회 (현재 시간 이후, KST 기준)
        
        Args:
            limit: 조회 제한 (기본 5개)
            db: 데이터베이스 연결
            
        Returns:
            List[EventResponse]: 다가오는 집회 목록
        """
        try:
            from zoneinfo import ZoneInfo
            cursor = db.cursor()
            
            # KST 현재 시간
            now_kst = datetime.now(ZoneInfo("Asia/Seoul"))
            now_str = now_kst.strftime("%Y-%m-%d %H:%M:%S")

            # SQLite에서는 날짜 비교를 위해 문자열 ISO format이나 datetime 객체를 사용
            # 여기서는 datetime 객체를 파라미터로 넘김 (adapter가 처리)
            # 또는 문자열로 변환하여 비교: now_kst.strftime("%Y-%m-%d %H:%M:%S")
            
            cursor.execute('''
                SELECT id, title, description, location_name, location_address,
                       latitude, longitude, start_date, end_date, category,
                       severity_level, status, created_at, updated_at
                FROM events
                WHERE status = 'active' AND start_date >= ?
                ORDER BY start_date ASC
                LIMIT ?
            ''', (now_str, limit))
            
            events = []
            for row in cursor.fetchall():
                events.append(EventResponse(
                    id=row["id"],
                    title=row["title"],
                    description=row["description"],
                    location_name=row["location_name"],
                    location_address=row["location_address"],
                    latitude=row["latitude"],
                    longitude=row["longitude"],
                    start_date=row["start_date"],
                    end_date=row["end_date"],
                    category=row["category"],
                    severity_level=row["severity_level"],
                    status=row["status"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"]
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
        오늘 진행되는 집회 목록 조회 (오늘 날짜, KST 기준)
        
        Args:
            db: 데이터베이스 연결
            
        Returns:
            List[EventResponse]: 오늘 집회 목록
        """
        try:
            from zoneinfo import ZoneInfo
            cursor = db.cursor()
            
            # KST 오늘 날짜 문자열 (YYYY-MM-DD)
            today_kst_str = datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()
            
            cursor.execute('''
                SELECT id, title, description, location_name, location_address,
                       latitude, longitude, start_date, end_date, category,
                       severity_level, status, created_at, updated_at
                FROM events
                WHERE status = 'active' AND date(start_date) = ?
                ORDER BY start_date ASC
            ''', (today_kst_str,))
            
            events = []
            for row in cursor.fetchall():
                events.append(EventResponse(
                    id=row["id"],
                    title=row["title"],
                    description=row["description"],
                    location_name=row["location_name"],
                    location_address=row["location_address"],
                    latitude=row["latitude"],
                    longitude=row["longitude"],
                    start_date=row["start_date"],
                    end_date=row["end_date"],
                    category=row["category"],
                    severity_level=row["severity_level"],
                    status=row["status"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"]
                ))

            return events

        except Exception as e:
            logger.error(f"오늘 집회 목록 조회 실패: {str(e)}")
            return []