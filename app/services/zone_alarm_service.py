"""구역 기반 알람 서비스"""
import logging
from typing import Dict, Any

from app.database.connection import get_db_connection
from app.utils.geo_utils import haversine_distance, FAVORITE_ZONES
from app.services.notification_service import NotificationService
from app.services.alarm_status_service import AlarmStatusService

logger = logging.getLogger(__name__)


class ZoneAlarmService:

    @staticmethod
    async def scheduled_zone_check() -> Dict[str, Any]:
        """
        구역 기반 정기 집회 확인 및 알람 발송.
        경로 알람(EventService.scheduled_route_check)과 완전 독립적으로 동작.
        favorite_zone이 설정된 사용자에게 해당 구역 내 집회 알람을 발송한다.
        """
        logger.info("=== 구역 기반 집회 확인 시작 ===")

        task_id = None
        try:
            task_id = AlarmStatusService.create_alarm_task(
                alarm_type="zone_scheduled", total_recipients=0
            )
            AlarmStatusService.update_alarm_task_status(task_id, "processing")

            with get_db_connection() as db:
                cursor = db.cursor()

                # 1. favorite_zone이 설정된 활성 사용자 조회
                cursor.execute('''
                    SELECT plusfriend_user_key, favorite_zone
                    FROM users
                    WHERE active = 1
                      AND is_alarm_on = 1
                      AND favorite_zone IS NOT NULL
                      AND plusfriend_user_key IS NOT NULL
                ''')
                users = cursor.fetchall()
                logger.info(f"구역 설정된 사용자 {len(users)}명 확인 중...")

                # 2. 활성 집회 전체 조회
                cursor.execute('''
                    SELECT id, title, location_name, location_address,
                           latitude, longitude, start_date, category, severity_level
                    FROM events
                    WHERE status = 'active'
                      AND latitude IS NOT NULL
                      AND longitude IS NOT NULL
                      AND start_date > datetime('now', '+9 hours')
                    ORDER BY start_date
                ''')
                events = cursor.fetchall()

                if not events:
                    logger.info("활성 집회 없음 — 구역 알람 발송 생략")
                    AlarmStatusService.update_alarm_task_status(task_id, "completed", total_recipients=0)
                    return {"success": True, "task_id": task_id, "total_users": len(users), "notifications_sent": 0}

                # 3. 각 사용자의 구역과 집회 좌표를 haversine_distance로 비교
                #    (zone_id, frozenset(event_ids)) 기준으로 그룹화
                grouped: Dict[tuple, Dict] = {}

                for user_row in users:
                    plusfriend_key = user_row["plusfriend_user_key"]
                    zone_id = user_row["favorite_zone"]

                    if zone_id not in FAVORITE_ZONES:
                        continue

                    zone = FAVORITE_ZONES[zone_id]
                    matched_events = []

                    for event_row in events:
                        dist = haversine_distance(
                            zone["lat"], zone["lon"],
                            event_row["latitude"], event_row["longitude"]
                        )
                        if dist <= zone["radius_m"]:
                            matched_events.append(event_row)

                    if not matched_events:
                        continue

                    group_key = (zone_id, tuple(sorted(e["id"] for e in matched_events)))

                    if group_key not in grouped:
                        grouped[group_key] = {
                            "zone_name": zone["name"],
                            "user_ids": [],
                            "events_data": [
                                {
                                    "id": e["id"],
                                    "title": e["title"],
                                    "location": e["location_name"],
                                    "latitude": e["latitude"],
                                    "longitude": e["longitude"],
                                    "start_date": e["start_date"],
                                    "category": e["category"],
                                    "severity_level": e["severity_level"],
                                }
                                for e in matched_events
                            ],
                        }
                    grouped[group_key]["user_ids"].append(plusfriend_key)

            # 4. 그룹별 일괄 발송
            actual_recipients = sum(len(g["user_ids"]) for g in grouped.values())
            AlarmStatusService.update_alarm_task_status(task_id, "processing", total_recipients=actual_recipients)

            total_success = 0
            total_fail = 0

            for group_data in grouped.values():
                zone_name = group_data["zone_name"]
                user_ids = group_data["user_ids"]
                events_data = group_data["events_data"]
                message_text = NotificationService._format_zone_message(zone_name, events_data)

                logger.info(f"📢 [{zone_name}] {len(user_ids)}명에게 집회 {len(events_data)}건 알림 전송")

                send_result = await NotificationService.send_bulk_alarm(
                    user_ids=user_ids,
                    event_name="morning_demo_alarm",
                    data={"message": message_text},
                    id_type="plusfriendUserKey",
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
                f"=== 구역 집회 확인 완료: 대상 {actual_recipients}명, 성공 {total_success}명, 실패 {total_fail}명 ==="
            )
            return {
                "success": True,
                "task_id": task_id,
                "total_users": len(users),
                "notifications_sent": total_success,
            }

        except Exception as e:
            logger.error(f"구역 집회 확인 중 오류 발생: {str(e)}")
            if task_id:
                AlarmStatusService.update_alarm_task_status(task_id, "failed", error_messages=[str(e)])
            return {"success": False, "task_id": task_id, "error": str(e)}
