"""사용자 관리 서비스"""
import logging
import sqlite3
from datetime import datetime
from typing import Optional, Dict, Any
from app.models.user import UserPreferences, InitialSetupRequest
from app.repositories.user_identity_repository import UserIdentityRepository
from app.repositories.user_preference_repository import UserPreferenceRepository
from app.repositories.user_profile_repository import UserProfileRepository
from app.repositories.user_read_repository import UserReadRepository
from app.repositories.user_route_repository import UserRouteRepository
from app.repositories.user_settings_repository import UserSettingsRepository
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
            now = datetime.now()
            
            # 기존 사용자 확인
            user = UserIdentityRepository.find_by_bot_user_key(db, bot_user_key)
            
            if user:
                # 기존 사용자 업데이트
                UserIdentityRepository.increment_bot_user_message(
                    db,
                    bot_user_key=bot_user_key,
                    now=now,
                )
                logger.info(f"사용자 업데이트: {bot_user_key}")
            else:
                # 새 사용자 생성
                UserIdentityRepository.insert_bot_user(
                    db,
                    bot_user_key=bot_user_key,
                    now=now,
                )
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
            now = datetime.now()
            
            if not plusfriend_key:
                # plusfriend_key가 없는 경우 기존 레거시 로직(bot_user_key 기준) 사용
                logger.warning(f"plusfriend_key 누락. bot_user_key({bot_user_key})로 대체합니다.")
                UserService.save_or_update_user(bot_user_key, db)
                return

            # plusfriend_key로 조회 (primary identifier)
            existing_plusfriend = UserIdentityRepository.find_by_plusfriend_key(db, plusfriend_key)

            # plusfriend 미연동 레거시 사용자를 bot_user_key로 조회
            existing_bot = UserIdentityRepository.find_by_bot_user_key(db, bot_user_key)

            if existing_plusfriend:
                # plusfriend_key로 이미 연결된 기존 사용자 업데이트
                logger.debug(f"✅ 기존 사용자 발견: plusfriend={plusfriend_key}")
                UserIdentityRepository.touch_plusfriend_user(
                    db,
                    plusfriend_key=plusfriend_key,
                    now=now,
                )

                existing_plusfriend_bot_user_key = existing_plusfriend["bot_user_key"]
                existing_plusfriend_id = existing_plusfriend["id"]
                existing_bot_id = existing_bot["id"] if existing_bot else None

                if existing_plusfriend_bot_user_key != bot_user_key:
                    if existing_bot and existing_bot_id != existing_plusfriend_id:
                        logger.warning(
                            "bot_user_key(%s)와 plusfriend_key(%s)가 서로 다른 사용자 행에 연결되어 있습니다. "
                            "기존 plusfriend 매핑은 유지하고 활동 시간만 갱신합니다.",
                            bot_user_key,
                            plusfriend_key,
                        )
                    else:
                        UserIdentityRepository.set_bot_user_key_for_plusfriend(
                            db,
                            plusfriend_key=plusfriend_key,
                            bot_user_key=bot_user_key,
                        )
            elif existing_bot:
                # 기존 bot_user_key 사용자에 plusfriend_key 연결
                logger.info(f"✅ 기존 bot_user_key 사용자에 plusfriend 연결: {bot_user_key} → {plusfriend_key}")
                UserIdentityRepository.link_plusfriend_to_bot(
                    db,
                    bot_user_key=bot_user_key,
                    plusfriend_key=plusfriend_key,
                    now=now,
                )
            else:
                # 웹훅 사용자 찾기 시도 (open_id만 있는 경우)
                orphan = UserIdentityRepository.find_oldest_unlinked_user(db)

                if orphan:
                    # 웹훅 사용자 연결 (Orphan Matching)
                    orphan_open_id = orphan["open_id"]
                    orphan_id = orphan["id"]
                    logger.info(f"✅ 웹훅 사용자 연결: open_id={orphan_open_id} → plusfriend={plusfriend_key}")
                    UserIdentityRepository.link_orphan_identity(
                        db,
                        user_id=orphan_id,
                        bot_user_key=bot_user_key,
                        plusfriend_key=plusfriend_key,
                        now=now,
                    )
                else:
                    # 완전 신규 사용자
                    logger.info(f"✅ 신규 사용자 생성: plusfriend={plusfriend_key}")
                    UserIdentityRepository.insert_kakao_identity(
                        db,
                        bot_user_key=bot_user_key,
                        plusfriend_key=plusfriend_key,
                        now=now,
                    )
            
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
    def update_alarm_setting(user_id: str, is_alarm_on: bool, db: sqlite3.Connection) -> Dict[str, Any]:
        """
        사용자 알람 수신 설정 (on/off) 업데이트
        
        Args:
            user_id: 사용자 ID (plusfriend_user_key 또는 bot_user_key)
            is_alarm_on: 알람 활성화 여부
            db: 데이터베이스 연결
            
        Returns:
            Dict: 처리 결과
        """
        try:
            updated_count = UserSettingsRepository.update_alarm_setting(
                db,
                user_id=user_id,
                is_alarm_on=is_alarm_on,
            )
            
            if updated_count == 0:
                logger.warning(f"알람 설정 업데이트 대상 사용자를 찾을 수 없음: {user_id}")
                return {"success": False, "error": "사용자를 찾을 수 없습니다"}
                
            db.commit()
            logger.info(f"사용자 알람 설정 업데이트 완료: {user_id} -> {'ON' if is_alarm_on else 'OFF'}")
            
            return {"success": True}
            
        except Exception as e:
            logger.error(f"사용자 알람 설정 업데이트 실패: {str(e)}")
            return {"success": False, "error": "일시적인 오류가 발생했습니다. 잠시 후 다시 시도해주세요."}

    @staticmethod
    def update_favorite_zone(user_id: str, zone: Optional[int], db: sqlite3.Connection) -> Dict[str, Any]:
        """
        사용자 관심장소 구역 설정 업데이트

        Args:
            user_id: 사용자 ID (plusfriend_user_key 또는 bot_user_key)
            zone: 구역 번호 (1, 2, 3) 또는 None (미설정/삭제)
            db: 데이터베이스 연결

        Returns:
            Dict: 처리 결과
        """
        try:
            updated_count = UserSettingsRepository.update_favorite_zone(
                db,
                user_id=user_id,
                zone=zone,
            )

            if updated_count == 0:
                logger.warning(f"관심장소 설정 업데이트 대상 사용자를 찾을 수 없음: {user_id}")
                return {"success": False, "error": "사용자를 찾을 수 없습니다"}

            db.commit()
            zone_label = f"{zone}구역" if zone else "미설정"
            logger.info(f"사용자 관심장소 설정 업데이트 완료: {user_id} -> {zone_label}")

            return {"success": True}

        except Exception as e:
            logger.error(f"사용자 관심장소 설정 업데이트 실패: {str(e)}")
            return {"success": False, "error": "일시적인 오류가 발생했습니다. 잠시 후 다시 시도해주세요."}

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
            # 1. 지오코딩
            departure_info = await get_location_info(departure)
            if not departure_info:
                return {"success": False, "error": "출발지를 찾을 수 없습니다"}

            arrival_info = await get_location_info(arrival)
            if not arrival_info:
                return {"success": False, "error": "도착지를 찾을 수 없습니다"}

            # 2. 경로 정보만 업데이트
            updated_count = UserRouteRepository.update_route(
                db,
                user_id=user_id,
                departure_info=departure_info,
                arrival_info=arrival_info,
                now=datetime.now(),
            )

            if updated_count == 0:
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
    def delete_user_route(user_id: str, db: sqlite3.Connection) -> Dict[str, Any]:
        """
        사용자 경로 정보 삭제 (route 관련 필드를 NULL로 초기화)

        Args:
            user_id: 사용자 ID (plusfriend_user_key)
            db: 데이터베이스 연결
        """
        try:
            updated_count = UserRouteRepository.clear_route(
                db,
                user_id=user_id,
                now=datetime.now(),
            )

            if updated_count == 0:
                logger.warning(f"경로 삭제 대상 사용자를 찾을 수 없음: {user_id}")
                return {"success": False, "error": "사용자를 찾을 수 없습니다"}

            db.commit()
            logger.info(f"경로 삭제 완료 - 사용자: {user_id}")
            return {"success": True}

        except Exception as e:
            logger.exception("경로 삭제 DB 처리 실패")
            return {"success": False, "error": "일시적인 오류가 발생했습니다. 잠시 후 다시 시도해주세요."}

    @staticmethod
    async def update_marked_bus(user_id: str, marked_bus: str, db: sqlite3.Connection) -> Dict[str, Any]:
        """
        사용자의 marked_bus(자주 타는 버스)만 업데이트
        - plusfriend_user_key 우선
        - 없으면 bot_user_key로 fallback
        """
        try:
            updated_count = UserSettingsRepository.update_marked_bus(
                db,
                user_id=user_id,
                marked_bus=marked_bus,
                now=datetime.now(),
            )

            if updated_count == 0:
                logger.warning(f"marked_bus 업데이트 대상 사용자를 찾을 수 없음: {user_id}")
                return {"success": False, "error": "사용자를 찾을 수 없습니다"}

            db.commit()
            logger.info(f"marked_bus 업데이트 완료 - 사용자: {user_id}, bus: {marked_bus}")
            return {"success": True, "marked_bus": marked_bus}

        except Exception as e:
            logger.error(f"marked_bus 업데이트 실패: {str(e)}")
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

            # 2. 전체 필드 업데이트
            # 주의: 값이 없는 필드는 NULL로 하거나, 기존 값을 유지해야 하는데
            # Initial Setup의 목적상 입력된 값으로 덮어쓰는 것이 일반적임.
            # 하지만 여기선 입력된 값만 업데이트하도록 동적 쿼리 사용 권장, 
            # 단순화를 위해 모두 업데이트 (None이면 NULL 처리될 수 있음에 유의)
            updated_count = UserProfileRepository.update_profile(
                db,
                plusfriend_user_key=user_setup.bot_user_key,
                departure_info=dep_info,
                arrival_info=arr_info,
                marked_bus=user_setup.marked_bus,
                language=user_setup.language,
                now=datetime.now(),
            )
            
            if updated_count == 0:
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
            return {"success": False, "error": "일시적인 오류가 발생했습니다. 잠시 후 다시 시도해주세요."}

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
            # 기존 사용자 확인
            if not UserPreferenceRepository.exists_by_bot_user_key(db, user_id):
                return {"success": False, "error": "사용자를 찾을 수 없습니다"}
            
            # 설정 업데이트
            updated_count = UserPreferenceRepository.update_preferences(
                db,
                user_id=user_id,
                marked_bus=preferences.marked_bus,
                language=preferences.language,
            )
            if updated_count:
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
            user_data = UserReadRepository.get_route_info_by_bot_user_key(db, user_id)
            if not user_data:
                return None
                
            # 경로 정보가 없으면 None 반환
            if not all([
                user_data["departure_x"],
                user_data["departure_y"],
                user_data["arrival_x"],
                user_data["arrival_y"],
            ]):
                return None
            
            return {
                "departure": {
                    "name": user_data["departure_name"],
                    "address": user_data["departure_address"],
                    "x": user_data["departure_x"],
                    "y": user_data["departure_y"]
                },
                "arrival": {
                    "name": user_data["arrival_name"],
                    "address": user_data["arrival_address"],
                    "x": user_data["arrival_x"],
                    "y": user_data["arrival_y"]
                },
                "updated_at": user_data["route_updated_at"]
            }
            
        except Exception as e:
            logger.error(f"사용자 경로 정보 조회 실패: {str(e)}")
            return None

    @staticmethod
    def get_user_info(user_id: str, db: sqlite3.Connection) -> Optional[Dict[str, Any]]:
        """
        사용자의 전체 정보 조회 (알람 설정, 관심구역, 경로, 버스 등)
        
        Args:
            user_id: 사용자 ID (plusfriend_user_key 또는 bot_user_key)
            db: 데이터베이스 연결
            
        Returns:
            Optional[Dict]: 사용자 정보 또는 None
        """
        try:
            row = UserReadRepository.get_user_info(db, user_id)
            if not row:
                return None
                
            return {
                "is_alarm_on": bool(row["is_alarm_on"]),
                "favorite_zone": row["favorite_zone"],
                "marked_bus": row["marked_bus"],
                "departure_name": row["departure_name"],
                "arrival_name": row["arrival_name"],
                "plusfriend_user_key": row["plusfriend_user_key"],
                "bot_user_key": row["bot_user_key"]
            }
            
        except Exception as e:
            logger.error(f"사용자 정보 조회 실패: {str(e)}")
            return None
