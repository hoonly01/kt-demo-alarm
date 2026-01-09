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
    def update_user_status(bot_user_key: str, db: sqlite3.Connection, active: bool) -> None:
        """
        사용자 활성 상태 업데이트
        
        Args:
            bot_user_key: 사용자 식별 키
            db: 데이터베이스 연결
            active: 활성 상태
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
    async def save_user_route_info(user_setup: InitialSetupRequest, db: sqlite3.Connection) -> Dict[str, Any]:
        """
        사용자의 출발지/도착지 정보를 저장
        
        Args:
            user_setup: 사용자 설정 요청 데이터
            db: 데이터베이스 연결
            
        Returns:
            Dict: 처리 결과
        """
        try:
            cursor = db.cursor()
            
            # 출발지 정보 조회
            departure_info = await get_location_info(user_setup.departure)
            if not departure_info:
                return {"success": False, "error": "출발지를 찾을 수 없습니다"}
            
            # 도착지 정보 조회
            arrival_info = await get_location_info(user_setup.arrival)
            if not arrival_info:
                return {"success": False, "error": "도착지를 찾을 수 없습니다"}
            
            # 사용자 경로 정보 및 개인화 설정 업데이트
            cursor.execute('''
                UPDATE users SET
                    departure_name = ?, departure_address = ?, departure_x = ?, departure_y = ?,
                    arrival_name = ?, arrival_address = ?, arrival_x = ?, arrival_y = ?,
                    route_updated_at = ?,
                    marked_bus = ?,
                    language = ?
                WHERE bot_user_key = ?
            ''', (
                departure_info["name"], departure_info["address"],
                departure_info["x"], departure_info["y"],
                arrival_info["name"], arrival_info["address"],
                arrival_info["x"], arrival_info["y"],
                datetime.now(),
                user_setup.marked_bus,
                user_setup.language,
                user_setup.bot_user_key
            ))
            
            db.commit()
            
            logger.info(f"경로 정보 저장 완료 - 사용자: {user_setup.bot_user_key}")
            logger.info(f"출발지: {departure_info['name']} ({departure_info['x']}, {departure_info['y']})")
            logger.info(f"도착지: {arrival_info['name']} ({arrival_info['x']}, {arrival_info['y']})")
            if user_setup.marked_bus:
                logger.info(f"즐겨찾는 버스: {user_setup.marked_bus}")
            if user_setup.language:
                logger.info(f"언어 설정: {user_setup.language}")

            return {
                "success": True,
                "departure": departure_info,
                "arrival": arrival_info,
                "marked_bus": user_setup.marked_bus,
                "language": user_setup.language
            }
            
        except Exception as e:
            logger.error(f"경로 정보 저장 실패: {str(e)}")
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