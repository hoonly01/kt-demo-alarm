"""지리 계산 관련 유틸리티 함수들"""
import math
import httpx
import os
from typing import List, Tuple, Optional, Dict
import logging

logger = logging.getLogger(__name__)
KAKAO_REST_API_KEY = os.getenv("KAKAO_REST_API_KEY")


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
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    
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
    
    # 삼각부등식을 이용한 근사 계산
    # 만약 점이 경로 위에 있다면, dist_to_start + dist_to_end ≈ route_distance
    total_distance = dist_to_start + dist_to_end
    
    # 허용 오차를 고려한 경로 근처 판단
    if abs(total_distance - route_distance) <= threshold_meters:
        return True
    
    # 추가로 출발지나 도착지에서 임계거리 이내인지 확인
    if dist_to_start <= threshold_meters or dist_to_end <= threshold_meters:
        return True
    
    return False


def is_event_near_route_accurate(route_coordinates: List[Tuple[float, float]], 
                                event_lat: float, event_lon: float, 
                                threshold_meters: float = 500) -> bool:
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


async def get_location_info(query: str) -> Optional[Dict]:
    """
    카카오 지도 API를 사용하여 검색어를 장소 정보로 변환
    
    Args:
        query: 검색할 장소명
    
    Returns:
        Dict: 장소 정보 (name, address, x, y) 또는 None
    """
    if not KAKAO_REST_API_KEY:
        logger.error("KAKAO_REST_API_KEY가 설정되지 않았습니다.")
        return None
        
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
                logger.error(f"카카오 지도 API 오류: {response.status_code}")
                return None
                
    except Exception as e:
        logger.error(f"장소 정보 조회 중 오류 발생: {str(e)}")
        return None


async def get_route_coordinates(start_x: float, start_y: float, 
                              end_x: float, end_y: float) -> List[Tuple[float, float]]:
    """
    카카오 Mobility API를 사용하여 실제 보행 경로 좌표를 가져옴
    
    Args:
        start_x, start_y: 출발지 경도, 위도
        end_x, end_y: 도착지 경도, 위도
    
    Returns:
        List[Tuple[float, float]]: 경로상의 (위도, 경도) 좌표 리스트
    """
    if not KAKAO_REST_API_KEY:
        logger.error("KAKAO_REST_API_KEY가 설정되지 않았습니다.")
        return []
        
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
                
                if data.get("routes") and len(data["routes"]) > 0:
                    route = data["routes"][0]
                    
                    # 경로상의 모든 좌표 추출
                    coordinates = []
                    
                    for section in route.get("sections", []):
                        for road in section.get("roads", []):
                            vertexes = road.get("vertexes", [])
                            # vertexes는 [경도, 위도, 경도, 위도, ...] 형태의 평면 배열
                            for i in range(0, len(vertexes), 2):
                                if i + 1 < len(vertexes):
                                    lon = vertexes[i]      # 경도
                                    lat = vertexes[i + 1]  # 위도
                                    coordinates.append((lat, lon))  # (위도, 경도) 순서로 반환
                    
                    logger.info(f"경로 좌표 {len(coordinates)}개 추출됨")
                    return coordinates
                else:
                    logger.warning("경로를 찾을 수 없습니다.")
                    return []
            else:
                logger.error(f"카카오 Mobility API 오류: {response.status_code}")
                return []
                
    except Exception as e:
        logger.error(f"경로 좌표 조회 중 오류 발생: {str(e)}")
        return []