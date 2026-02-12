"""사용자 관리 서비스"""
import logging
import sqlite3
from datetime import datetime
from typing import Optional, Dict, Any
from app.models.user import UserPreferences, InitialSetupRequest
from app.utils.geo_utils import get_location_info

logger = logging.getLogger(__name__)


class UserService:
    """사용자 관리 비즈니스 로직"""

    @staticmethod
    def save_or_update_user(bot_user_key: str, db: sqlite3.Connection, message: str = "") -> None:
        """
        사용자 정보를 DB에 저장하거나 업데이트
        
        Args:
            bot_user_key: 사용자 식별 키
            db: 데이터베이스 연결
            message: 메시지 (로깅용)
        """
        try:
            cursor = db.cursor()
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
            
            db.commit()
            
        except Exception as e:
            logger.error(f"사용자 저장/업데이트 실패: {str(e)}")
            raise

    @staticmethod
    def sync_kakao_user(bot_user_key: str, plusfriend_key: Optional[str], db: sqlite3.Connection) -> None:
        """
        카카오톡 사용자 동기화 (식별 및 매칭)
        - plusfriend_user_key를 우선 식별자로 사용
        - 웹훅 연동으로 생성된 '고아 사용자(orphan)' 매칭 로직 포함
        
        Args:
            bot_user_key: 봇 사용자 키 (필수)
            plusfriend_key: 카카오 채널 사용자 키 (권장)
            db: 데이터베이스 연결
        """
        try:
            cursor = db.cursor()
            
            if not plusfriend_key:
                # plusfriend_key가 없는 경우 기존 레거시 로직(bot_user_key 기준) 사용
                logger.warning(f"plusfriend_key 누락. bot_user_key({bot_user_key})로 대체합니다.")
                UserService.save_or_update_user(bot_user_key, db)
                return

            # plusfriend_key로 조회 (primary identifier)
            cursor.execute(
                "SELECT id, open_id FROM users WHERE plusfriend_user_key = ?",
                (plusfriend_key,)
            )
            existing = cursor.fetchone()

            if existing:
                # 기존 사용자 업데이트
                logger.debug(f"✅ 기존 사용자 발견: plusfriend={plusfriend_key}")
                cursor.execute("""
                    UPDATE users
                    SET bot_user_key = ?, last_message_at = ?, message_count = message_count + 1
                    WHERE plusfriend_user_key = ?
                """, (bot_user_key, datetime.now(), plusfriend_key))
            else:
                # 웹훅 사용자 찾기 시도 (open_id만 있는 경우)
                cursor.execute("""
                    SELECT id, open_id FROM users
                    WHERE bot_user_key IS NULL AND plusfriend_user_key IS NULL
                    ORDER BY first_message_at ASC, id ASC
                    LIMIT 1
                """)
                orphan = cursor.fetchone()

                if orphan:
                    # 웹훅 사용자 연결 (Orphan Matching)
                    logger.info(f"✅ 웹훅 사용자 연결: open_id={orphan[1]} → plusfriend={plusfriend_key}")
                    cursor.execute("""
                        UPDATE users
                        SET bot_user_key = ?, plusfriend_user_key = ?, last_message_at = ?
                        WHERE id = ?
                    """, (bot_user_key, plusfriend_key, datetime.now(), orphan[0]))
                else:
                    # 완전 신규 사용자
                    logger.info(f"✅ 신규 사용자 생성: plusfriend={plusfriend_key}")
                    cursor.execute("""
                        INSERT INTO users (bot_user_key, plusfriend_user_key, first_message_at, last_message_at, message_count, active)
                        VALUES (?, ?, ?, ?, 1, 1)
                    """, (bot_user_key, plusfriend_key, datetime.now(), datetime.now()))
            
            db.commit()
            
        except Exception as e:
            logger.error(f"카카오 사용자 동기화 실패: {str(e)}")
            raise

    @staticmethod
    def update_user_status(bot_user_key: str, db: sqlite3.Connection, active: bool) -> None:
        """
        사용자 활성 상태 업데이트
        """
        try:
            cursor = db.cursor()
            cursor.execute(
                'UPDATE users SET active = ? WHERE bot_user_key = ?',
                (active, bot_user_key)
            )
            db.commit()
            logger.info(f"사용자 상태 업데이트: {bot_user_key} -> {'활성' if active else '비활성'}")
            
        except Exception as e:
            logger.error(f"사용자 상태 업데이트 실패: {str(e)}")
            raise

    @staticmethod
    async def update_user_route(user_id: str, departure: str, arrival: str, db: sqlite3.Connection) -> Dict[str, Any]:
        """
        사용자 경로 정보만 업데이트 (출발지/도착지)
        - marked_bus, language 등 개인화 설정은 건드리지 않음
        
        Args:
            user_id: 사용자 ID (plusfriend_user_key)
            departure: 출발지 검색어
            arrival: 도착지 검색어
            db: 데이터베이스 연결
        """
        try:
            cursor = db.cursor()

            # 1. 지오코딩
            departure_info = await get_location_info(departure)
            if not departure_info:
                return {"success": False, "error": "출발지를 찾을 수 없습니다"}

            arrival_info = await get_location_info(arrival)
            if not arrival_info:
                return {"success": False, "error": "도착지를 찾을 수 없습니다"}

            # 2. 경로 정보만 업데이트
            cursor.execute('''
                UPDATE users SET
                    departure_name = ?, departure_address = ?, departure_x = ?, departure_y = ?,
                    arrival_name = ?, arrival_address = ?, arrival_x = ?, arrival_y = ?,
                    route_updated_at = ?
                WHERE plusfriend_user_key = ?
            ''', (
                departure_info["name"], departure_info["address"],
                departure_info["x"], departure_info["y"],
                arrival_info["name"], arrival_info["address"],
                arrival_info["x"], arrival_info["y"],
                datetime.now(),
                user_id
            ))

            if cursor.rowcount == 0:
                logger.warning(f"경로 업데이트 대상 사용자를 찾을 수 없음: {user_id}")
                return {"success": False, "error": "사용자를 찾을 수 없습니다"}

            if cursor.rowcount == 0:
                logger.warning(f"경로 업데이트 대상 사용자를 찾을 수 없음: {user_id}")
                return {"success": False, "error": "사용자를 찾을 수 없습니다"}

            db.commit()
            
            logger.info(f"경로(Route Only) 업데이트 완료 - 사용자: {user_id}")
            logger.info(f"출발: {departure_info['name']}, 도착: {arrival_info['name']}")

            return {
                "success": True,
                "departure": departure_info,
                "arrival": arrival_info
            }
            
        except Exception as e:
            logger.error(f"경로 정보 업데이트 실패: {str(e)}")
            return {"success": False, "error": str(e)}

    @staticmethod
    async def setup_user_profile(user_setup: InitialSetupRequest, db: sqlite3.Connection) -> Dict[str, Any]:
        """
        사용자 프로필 전체 설정 (초기 설정용)
        - 경로(출발/도착) + 개인화 설정(버스, 언어) 모두 업데이트
        
        Args:
            user_setup: 설정 요청 객체
            db: 데이터베이스 연결
        """
        try:
            cursor = db.cursor()

            # 1. 지오코딩 (경로 정보가 있는 경우)
            dep_info = None
            arr_info = None
            
            if user_setup.departure:
                dep_info = await get_location_info(user_setup.departure)
                if not dep_info:
                    return {"success": False, "error": "출발지를 찾을 수 없습니다"}
            
            if user_setup.arrival:
                arr_info = await get_location_info(user_setup.arrival)
                if not arr_info:
                    return {"success": False, "error": "도착지를 찾을 수 없습니다"}

            # 2. 전체 필드 업데이트 쿼리 구성
            # 주의: 값이 없는 필드는 NULL로 하거나, 기존 값을 유지해야 하는데
            # Initial Setup의 목적상 입력된 값으로 덮어쓰는 것이 일반적임.
            # 하지만 여기선 입력된 값만 업데이트하도록 동적 쿼리 사용 권장, 
            # 단순화를 위해 모두 업데이트 (None이면 NULL 처리될 수 있음에 유의)
            
            update_query = "UPDATE users SET route_updated_at = ?"
            params = [datetime.now()]
            
            if dep_info:
                update_query += ", departure_name=?, departure_address=?, departure_x=?, departure_y=?"
                params.extend([dep_info["name"], dep_info["address"], dep_info["x"], dep_info["y"]])
                
            if arr_info:
                update_query += ", arrival_name=?, arrival_address=?, arrival_x=?, arrival_y=?"
                params.extend([arr_info["name"], arr_info["address"], arr_info["x"], arr_info["y"]])
                
            if user_setup.marked_bus:
                update_query += ", marked_bus=?"
                params.append(user_setup.marked_bus)
                
            if user_setup.language:
                update_query += ", language=?"
                params.append(user_setup.language)
                
            update_query += " WHERE plusfriend_user_key = ?"
            params.append(user_setup.bot_user_key)
            
            cursor.execute(update_query, params)
            
            if cursor.rowcount == 0:
                logger.warning(f"프로필 업데이트 대상 사용자를 찾을 수 없음: {user_setup.bot_user_key}")
                return {"success": False, "error": "사용자를 찾을 수 없습니다"}

            db.commit()

            logger.info(f"프로필(Full Setup) 설정 완료 - 사용자: {user_setup.bot_user_key}")
            
            return {
                "success": True,
                "departure": dep_info,
                "arrival": arr_info,
                "marked_bus": user_setup.marked_bus,
                "language": user_setup.language
            }

        except Exception as e:
            logger.error(f"프로필 설정 실패: {str(e)}")
            return {"success": False, "error": str(e)}

    @staticmethod
    def update_user_preferences(user_id: str, preferences: UserPreferences, db: sqlite3.Connection) -> Dict[str, Any]:
        """
        사용자 설정 업데이트
        
        Args:
            user_id: 사용자 ID
            preferences: 사용자 설정
            db: 데이터베이스 연결
            
        Returns:
            Dict: 처리 결과
        """
        try:
            cursor = db.cursor()
            
            # 기존 사용자 확인
            cursor.execute("SELECT id FROM users WHERE bot_user_key = ?", (user_id,))
            user = cursor.fetchone()
            
            if not user:
                return {"success": False, "error": "사용자를 찾을 수 없습니다"}
            
            # 설정 업데이트
            update_fields = []
            update_values = []
            
            if preferences.marked_bus:
                update_fields.append("marked_bus = ?")
                update_values.append(preferences.marked_bus)
            
            if preferences.language:
                update_fields.append("language = ?") 
                update_values.append(preferences.language)
            
            if update_fields:
                update_values.append(user_id)
                query = f"UPDATE users SET {', '.join(update_fields)} WHERE bot_user_key = ?"
                cursor.execute(query, update_values)
                db.commit()
            
            logger.info(f"사용자 설정 업데이트 완료: {user_id}")
            return {"success": True}
            
        except Exception as e:
            logger.error(f"사용자 설정 업데이트 실패: {str(e)}")
            return {"success": False, "error": str(e)}

    @staticmethod
    def get_user_route_info(user_id: str, db: sqlite3.Connection) -> Optional[Dict[str, Any]]:
        """
        사용자의 경로 정보 조회
        
        Args:
            user_id: 사용자 ID
            db: 데이터베이스 연결
            
        Returns:
            Optional[Dict]: 사용자 경로 정보 또는 None
        """
        try:
            cursor = db.cursor()
            cursor.execute('''
                SELECT departure_name, departure_address, departure_x, departure_y,
                       arrival_name, arrival_address, arrival_x, arrival_y,
                       route_updated_at
                FROM users WHERE bot_user_key = ?
            ''', (user_id,))
            
            user_data = cursor.fetchone()
            if not user_data:
                return None
                
            # 경로 정보가 없으면 None 반환
            if not all([user_data[2], user_data[3], user_data[6], user_data[7]]):
                return None
            
            return {
                "departure": {
                    "name": user_data[0],
                    "address": user_data[1],
                    "x": user_data[2],
                    "y": user_data[3]
                },
                "arrival": {
                    "name": user_data[4],
                    "address": user_data[5],
                    "x": user_data[6],
                    "y": user_data[7]
                },
                "updated_at": user_data[8]
            }
            
        except Exception as e:
            logger.error(f"사용자 경로 정보 조회 실패: {str(e)}")
            return None