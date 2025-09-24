"""알림 상태 추적 서비스"""
import json
import sqlite3
import uuid
from datetime import datetime
from typing import Dict, Any, Optional, List
import logging

from app.database.connection import get_db_connection

logger = logging.getLogger(__name__)


class AlarmStatusService:
    """알림 상태 추적을 위한 비즈니스 로직"""

    @staticmethod
    def create_alarm_task(
        alarm_type: str,
        total_recipients: int = 0,
        event_id: Optional[int] = None,
        request_data: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        새 알림 작업 생성
        
        Args:
            alarm_type: 알림 타입 (individual, bulk, filtered)
            total_recipients: 대상 수신자 수
            event_id: 관련 이벤트 ID (optional)
            request_data: 원본 요청 데이터 (optional)
            
        Returns:
            str: 생성된 task_id
        """
        task_id = str(uuid.uuid4())
        
        with get_db_connection() as db:
            cursor = db.cursor()
            cursor.execute(
                """
                INSERT INTO alarm_tasks 
                (task_id, alarm_type, status, total_recipients, event_id, request_data, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    alarm_type,
                    "pending",
                    total_recipients,
                    event_id,
                    json.dumps(request_data) if request_data else None,
                    datetime.now().isoformat()
                )
            )
            db.commit()
        
        logger.info(f"알림 작업 생성: {task_id}, 타입: {alarm_type}, 대상자: {total_recipients}")
        return task_id

    @staticmethod
    def update_alarm_task_status(
        task_id: str,
        status: str,
        successful_sends: Optional[int] = None,
        failed_sends: Optional[int] = None,
        error_messages: Optional[List[str]] = None
    ) -> bool:
        """
        알림 작업 상태 업데이트
        
        Args:
            task_id: 작업 ID
            status: 새 상태 (pending, processing, completed, failed, partial)
            successful_sends: 성공 발송 수 (optional)
            failed_sends: 실패 발송 수 (optional)
            error_messages: 오류 메시지 목록 (optional)
            
        Returns:
            bool: 업데이트 성공 여부
        """
        try:
            with get_db_connection() as db:
                cursor = db.cursor()
                
                # 기본 업데이트 쿼리 구성
                update_fields = ["status = ?", "updated_at = ?"]
                update_values = [status, datetime.now().isoformat()]
                
                # 선택적 필드 추가
                if successful_sends is not None:
                    update_fields.append("successful_sends = ?")
                    update_values.append(successful_sends)
                
                if failed_sends is not None:
                    update_fields.append("failed_sends = ?")
                    update_values.append(failed_sends)
                
                if error_messages is not None:
                    update_fields.append("error_messages = ?")
                    update_values.append(json.dumps(error_messages))
                
                # 완료 상태인 경우 완료 시간 추가
                if status in ["completed", "failed", "partial"]:
                    update_fields.append("completed_at = ?")
                    update_values.append(datetime.now().isoformat())
                
                # 쿼리 실행
                query = f"UPDATE alarm_tasks SET {', '.join(update_fields)} WHERE task_id = ?"
                update_values.append(task_id)
                
                cursor.execute(query, update_values)
                db.commit()
                
                if cursor.rowcount == 0:
                    logger.warning(f"알림 작업 ID {task_id}를 찾을 수 없음")
                    return False
                
                logger.info(f"알림 작업 상태 업데이트: {task_id} -> {status}")
                return True
                
        except Exception as e:
            logger.error(f"알림 작업 상태 업데이트 실패: {task_id}, 오류: {e}")
            return False

    @staticmethod
    def get_alarm_task_status(task_id: str) -> Optional[Dict[str, Any]]:
        """
        알림 작업 상태 조회
        
        Args:
            task_id: 작업 ID
            
        Returns:
            Dict: 작업 상태 정보, 없으면 None
        """
        try:
            with get_db_connection() as db:
                cursor = db.cursor()
                cursor.execute(
                    """
                    SELECT 
                        task_id, alarm_type, status, total_recipients,
                        successful_sends, failed_sends, event_id,
                        request_data, error_messages,
                        created_at, updated_at, completed_at
                    FROM alarm_tasks 
                    WHERE task_id = ?
                    """,
                    (task_id,)
                )
                
                row = cursor.fetchone()
                if not row:
                    return None
                
                # 결과를 dict로 변환
                columns = [desc[0] for desc in cursor.description]
                result = dict(zip(columns, row))
                
                # JSON 필드 파싱
                if result['request_data']:
                    try:
                        result['request_data'] = json.loads(result['request_data'])
                    except json.JSONDecodeError:
                        result['request_data'] = None
                
                if result['error_messages']:
                    try:
                        result['error_messages'] = json.loads(result['error_messages'])
                    except json.JSONDecodeError:
                        result['error_messages'] = []
                else:
                    result['error_messages'] = []
                
                # 진행률 계산
                if result['total_recipients'] > 0:
                    success_rate = (result['successful_sends'] or 0) / result['total_recipients']
                    result['success_rate'] = round(success_rate * 100, 2)
                else:
                    result['success_rate'] = 0.0
                
                return result
                
        except Exception as e:
            logger.error(f"알림 작업 상태 조회 실패: {task_id}, 오류: {e}")
            return None

    @staticmethod
    def get_recent_alarm_tasks(limit: int = 50) -> List[Dict[str, Any]]:
        """
        최근 알림 작업 목록 조회
        
        Args:
            limit: 조회 제한 수
            
        Returns:
            List[Dict]: 알림 작업 목록
        """
        try:
            with get_db_connection() as db:
                cursor = db.cursor()
                cursor.execute(
                    """
                    SELECT 
                        task_id, alarm_type, status, total_recipients,
                        successful_sends, failed_sends, event_id,
                        created_at, updated_at, completed_at
                    FROM alarm_tasks 
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (limit,)
                )
                
                rows = cursor.fetchall()
                columns = [desc[0] for desc in cursor.description]
                
                results = []
                for row in rows:
                    task_data = dict(zip(columns, row))
                    
                    # 진행률 계산
                    if task_data['total_recipients'] > 0:
                        success_rate = (task_data['successful_sends'] or 0) / task_data['total_recipients']
                        task_data['success_rate'] = round(success_rate * 100, 2)
                    else:
                        task_data['success_rate'] = 0.0
                    
                    results.append(task_data)
                
                return results
                
        except Exception as e:
            logger.error(f"최근 알림 작업 목록 조회 실패: {e}")
            return []

    @staticmethod
    def cleanup_old_tasks(days: int = 30) -> int:
        """
        오래된 알림 작업 정리
        
        Args:
            days: 보관 일수
            
        Returns:
            int: 삭제된 작업 수
        """
        try:
            with get_db_connection() as db:
                cursor = db.cursor()
                cursor.execute(
                    """
                    DELETE FROM alarm_tasks 
                    WHERE created_at < datetime('now', '-' || ? || ' days')
                    """,
                    (days,)
                )
                db.commit()
                deleted_count = cursor.rowcount
                
                logger.info(f"오래된 알림 작업 {deleted_count}개 정리 완료 ({days}일 이전)")
                return deleted_count
                
        except Exception as e:
            logger.error(f"오래된 알림 작업 정리 실패: {e}")
            return 0