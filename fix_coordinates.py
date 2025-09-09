#!/usr/bin/env python3
"""
기존 집회 데이터의 잘못된 좌표를 카카오 지도 API로 수정하는 스크립트
"""
import asyncio
import sqlite3
import logging
import sys
import os
from dotenv import load_dotenv

# 환경변수 로드
load_dotenv()

# 모듈 경로 추가
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.utils.geo_utils import get_location_info
from app.database.connection import DATABASE_PATH

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def fix_event_coordinates():
    """기존 집회 데이터의 좌표를 카카오 지도 API로 수정"""
    
    # 광화문 기본 좌표로 되어 있는 데이터들 조회
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    cursor = conn.cursor()
    
    # 광화문 좌표(37.5709, 126.9769)로 되어있는 집회들 찾기
    cursor.execute('''
        SELECT id, title, location_name, latitude, longitude 
        FROM events 
        WHERE latitude = 37.5709 AND longitude = 126.9769
        AND location_name NOT LIKE '%광화문%'
        ORDER BY id
    ''')
    
    events_to_fix = cursor.fetchall()
    logger.info(f"수정할 집회 {len(events_to_fix)}개 발견")
    
    success_count = 0
    failed_count = 0
    
    for event_id, title, location_name, current_lat, current_lon in events_to_fix:
        logger.info(f"처리 중: [{event_id}] {title} - {location_name}")
        
        try:
            # 카카오 지도 API로 정확한 좌표 조회
            location_info = await get_location_info(location_name)
            
            if location_info:
                new_lat = location_info["y"]  # 위도
                new_lon = location_info["x"]  # 경도
                
                # 좌표 업데이트
                cursor.execute('''
                    UPDATE events 
                    SET latitude = ?, longitude = ? 
                    WHERE id = ?
                ''', (new_lat, new_lon, event_id))
                
                logger.info(f"  ✅ 좌표 업데이트: ({current_lat}, {current_lon}) -> ({new_lat}, {new_lon})")
                success_count += 1
            else:
                logger.warning(f"  ❌ 장소를 찾을 수 없음: {location_name}")
                failed_count += 1
                
        except Exception as e:
            logger.error(f"  ❌ 오류 발생: {str(e)}")
            failed_count += 1
        
        # API 호출 제한 방지를 위한 짧은 대기
        await asyncio.sleep(0.1)
    
    # 변경사항 저장
    conn.commit()
    conn.close()
    
    logger.info(f"=== 좌표 수정 완료 ===")
    logger.info(f"성공: {success_count}개")
    logger.info(f"실패: {failed_count}개")
    
    return {"success": success_count, "failed": failed_count}


async def verify_coordinates():
    """수정된 좌표 검증"""
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    cursor = conn.cursor()
    
    # 광화문 좌표로 남아있는 데이터 확인
    cursor.execute('''
        SELECT COUNT(*) 
        FROM events 
        WHERE latitude = 37.5709 AND longitude = 126.9769
    ''')
    
    gwanghwamun_count = cursor.fetchone()[0]
    
    # 전체 집회 수 확인
    cursor.execute('SELECT COUNT(*) FROM events')
    total_count = cursor.fetchone()[0]
    
    # 고유 좌표 수 확인
    cursor.execute('SELECT COUNT(*) FROM (SELECT DISTINCT latitude, longitude FROM events)')
    unique_coords = cursor.fetchone()[0]
    
    conn.close()
    
    logger.info(f"=== 좌표 검증 결과 ===")
    logger.info(f"전체 집회: {total_count}개")
    logger.info(f"광화문 좌표(37.5709, 126.9769): {gwanghwamun_count}개")
    logger.info(f"고유 좌표: {unique_coords}개")


if __name__ == "__main__":
    logger.info("🔧 집회 데이터 좌표 수정 스크립트 시작")
    
    # 현재 상태 확인
    asyncio.run(verify_coordinates())
    
    # 좌표 수정 실행
    result = asyncio.run(fix_event_coordinates())
    
    # 수정 후 검증
    asyncio.run(verify_coordinates())
    
    logger.info("🎉 스크립트 완료")