"""집회 데이터 크롤링 서비스"""
import logging
import sqlite3
from datetime import datetime
from typing import List, Dict, Any

from app.database.connection import DATABASE_PATH

logger = logging.getLogger(__name__)

# TODO: 실제 크롤링 구현시 추가 필요한 imports:
# import os, re, urllib.parse, requests, BeautifulSoup, fitz
# from zoneinfo import ZoneInfo
# BASE_URL = "https://www.smpa.go.kr"
# LIST_URL = f"{BASE_URL}/user/nd54882.do"


class CrawlingService:
    """SMPA 집회 데이터 크롤링 비즈니스 로직"""

    @staticmethod
    async def crawl_and_sync_events() -> Dict[str, Any]:
        """
        SMPA 집회 데이터 크롤링 및 동기화
        main_old.py의 crawl_and_sync_events_to_db() 로직 기반
        
        Returns:
            Dict: 크롤링 결과
        """
        try:
            logger.info("=== SMPA 집회 데이터 크롤링 시작 ===")
            
            # 1. 오늘 집회 정보 크롤링 및 파싱
            logger.info("집회 정보 크롤링 및 파싱 시작")
            new_events = await CrawlingService._crawl_and_parse_today_events()
            
            if not new_events:
                return {
                    "success": True,
                    "status": "warning",
                    "message": "크롤링된 이벤트가 없습니다",
                    "total_crawled": 0
                }
            
            # 2. 데이터베이스 동기화
            db = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
            
            try:
                inserted_count = await CrawlingService._sync_events_to_db(new_events, db)
                
                logger.info(f"=== 크롤링 완료: {inserted_count}개 새 집회 추가 ===")
                
                return {
                    "success": True,
                    "status": "success",
                    "message": f"집회 데이터 크롤링 및 동기화 완료",
                    "total_crawled": len(new_events),
                    "inserted_count": inserted_count
                }
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"크롤링 중 오류 발생: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "total_crawled": 0
            }

    @staticmethod
    async def _crawl_and_parse_today_events() -> List[Dict[str, Any]]:
        """
        오늘 집회 정보를 크롤링하고 파싱하여 DB 형식으로 반환
        main_old.py의 crawl_and_parse_today_events() 로직 기반
        
        Returns:
            List[Dict]: DB 형식으로 변환된 집회 정보
        """
        try:
            # 실제 크롤링 로직은 복잡한 PDF 파싱과 외부 의존성을 포함하므로
            # 현재는 구조만 구현하고 실제 로직은 추후 점진적으로 추가
            logger.info("SMPA PDF 크롤링 및 파싱 (구현 예정)")
            
            # TODO: 실제 구현시 다음 단계들 필요:
            # 1. download_today_pdf_with_title() - PDF 다운로드
            # 2. extract_ymd_from_title() - 날짜 추출
            # 3. parse_pdf() - PDF 파싱  
            # 4. convert_raw_events_to_db_format() - DB 형식 변환
            
            # 현재는 빈 배열 반환
            return []
            
        except Exception as e:
            logger.error(f"크롤링 및 파싱 중 오류: {str(e)}")
            return []

    @staticmethod
    async def _sync_events_to_db(events: List[Dict[str, Any]], db: sqlite3.Connection) -> int:
        """
        크롤링된 집회 정보를 DB에 동기화
        main_old.py의 DB 동기화 로직 기반
        
        Args:
            events: 크롤링된 집회 정보 리스트
            db: 데이터베이스 연결
            
        Returns:
            int: 새로 삽입된 이벤트 수
        """
        if not events:
            return 0
            
        cursor = db.cursor()
        inserted_count = 0
        duplicate_count = 0
        error_count = 0
        
        try:
            db.execute("BEGIN TRANSACTION")
            
            for i, event in enumerate(events):
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
            logger.info(f"DB 트랜잭션 커밋 완료: {inserted_count}개 삽입, {duplicate_count}개 중복, {error_count}개 오류")
            
        except Exception as tx_error:
            db.rollback()
            logger.error(f"DB 트랜잭션 실패, 롤백: {tx_error}")
            raise
        
        return inserted_count

    # NOTE: 실제 크롤링 로직 구현을 위해 추가로 필요한 메서드들:
    # - _download_today_pdf_with_title(): PDF 다운로드
    # - _parse_pdf(): PDF 텍스트 파싱
    # - _extract_ymd_from_title(): 날짜 추출
    # - _convert_raw_events_to_db_format(): DB 형식 변환
    # - 기타 유틸리티 함수들 (main_old.py의 1292-1600라인 참조)