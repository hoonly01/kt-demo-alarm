"""지리 계산 관련 유틸리티 함수들"""
import math
import os
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)
KAKAO_REST_API_KEY = os.getenv("KAKAO_REST_API_KEY")
TMAP_APP_KEY = os.getenv("TMAP_APP_KEY")

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
    한 점이 두 지점을 잇는 직선 경로 근처에 있는지 확인 (단순 직선 거리 근사)
    
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


def is_event_near_route_accurate(route_coordinates: list[tuple[float, float]], 
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


def parse_linestring(linestring: str) -> list[tuple[float, float]]:
    """
    TMAP linestring 문자열을 [(lat, lon), ...] 형태로 변환
    예:
    "126.97834,37.566467 126.9785,37.56643"
    -> [(37.566467, 126.97834), (37.56643, 126.9785)]
    """
    coordinates = []

    if not linestring:
        return coordinates

    for point in linestring.strip().split():
        try:
            lon_str, lat_str = point.split(",")
            lon = float(lon_str)
            lat = float(lat_str)
            coordinates.append((lat, lon))
        except ValueError:
            continue

    return coordinates


async def get_location_info(query: str, client: Optional[httpx.AsyncClient] = None) -> Optional[dict]:
    """
    카카오 지도 API를 사용하여 검색어를 장소 정보로 변환
    
    Args:
        query: 검색할 장소명
        client: 재사용할 HTTP 클라이언트 (Optional)
    
    Returns:
        dict: 장소 정보 (name, address, x, y) 또는 None
    """
    if not KAKAO_REST_API_KEY:
        logger.error("KAKAO_REST_API_KEY가 설정되지 않았습니다.")
        return None
        
    url = "https://dapi.kakao.com/v2/local/search/keyword.json"
    headers = {"Authorization": f"KakaoAK {KAKAO_REST_API_KEY}"}
    params = {"query": query}

    try:
        if client:
            response = await client.get(url, headers=headers, params=params)
        else:
            async with httpx.AsyncClient() as new_client:
                response = await new_client.get(url, headers=headers, params=params)
            
        response.raise_for_status()
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

    except httpx.HTTPStatusError as e:
        logger.error(f"카카오 지도 API HTTP 오류: {e.response.status_code} - {e.response.text}")
        return None
    except httpx.RequestError as e:
        logger.error(f"카카오 지도 API 요청 오류: {str(e)}")
        return None
    except Exception as e:
        logger.error(f"장소 정보 조회 중 예기치 못한 오류 발생: {str(e)}")
        return None


async def get_route_coordinates_tmap_transit(
    start_x: float,
    start_y: float,
    end_x: float,
    end_y: float,
    client: Optional[httpx.AsyncClient] = None
) -> list[tuple[float, float]]:
    """
    TMAP 대중교통 API를 사용하여 실제 경로 좌표를 가져옴

    Args:
        start_x, start_y: 출발지 경도, 위도
        end_x, end_y: 도착지 경도, 위도
        client: 재사용할 HTTP 클라이언트 (Optional)

    Returns:
        list[tuple[float, float]]: 경로상의 (위도, 경도) 좌표 리스트
    """

    if not TMAP_APP_KEY:
        logger.error("TMAP_APP_KEY가 설정되지 않았습니다.")
        return []

    url = "https://apis.openapi.sk.com/transit/routes"
    headers = {
        "accept": "application/json",
        "appKey": TMAP_APP_KEY,
        "content-type": "application/json",
    }
    payload = {
        "startX": str(start_x),
        "startY": str(start_y),
        "endX": str(end_x),
        "endY": str(end_y),
        "count": 1,
        "lang": 0,
        "format": "json",
    }

    try:
        if client:
            response = await client.post(url, headers=headers, json=payload)
        else:
            async with httpx.AsyncClient(timeout=20.0) as new_client:
                response = await new_client.post(url, headers=headers, json=payload)

        response.raise_for_status()
        data = response.json()

        itineraries = data.get("metaData", {}).get("plan", {}).get("itineraries", [])
        if not itineraries:
            logger.warning("TMAP 대중교통 경로를 찾을 수 없습니다.")
            return []

        route = itineraries[0]
        coordinates = []

        for leg in route.get("legs", []):
            mode = leg.get("mode")

            # 1) 버스/지하철 등 passShape.linestring 사용
            pass_shape = leg.get("passShape", {})
            if isinstance(pass_shape, dict):
                linestring = pass_shape.get("linestring")
                if linestring:
                    coordinates.extend(parse_linestring(linestring))

            # 2) 도보 구간은 steps[].linestring 사용
            if mode == "WALK":
                for step in leg.get("steps", []):
                    linestring = step.get("linestring")
                    if linestring:
                        coordinates.extend(parse_linestring(linestring))

        # 중복 제거
        deduped = []
        seen = set()
        for lat, lon in coordinates:
            key = (round(lat, 7), round(lon, 7))
            if key not in seen:
                seen.add(key)
                deduped.append((lat, lon))

        logger.info(f"TMAP 경로 좌표 {len(deduped)}개 추출됨")
        return deduped

    except httpx.HTTPStatusError as e:
        logger.error(f"TMAP API HTTP 오류: {e.response.status_code} - {e.response.text}")
        return []
    except httpx.RequestError as e:
        logger.error(f"TMAP API 요청 오류: {str(e)}")
        return []
    except Exception as e:
        logger.error(f"TMAP 경로 좌표 조회 중 예기치 못한 오류 발생: {str(e)}")
        return []


async def get_route_coordinates_kakao(start_x: float, start_y: float, 
                              end_x: float, end_y: float,
                              client: Optional[httpx.AsyncClient] = None) -> list[tuple[float, float]]:
    """
    카카오 Mobility API를 사용하여 실제 보행 경로 좌표를 가져옴
    
    Args:
        start_x, start_y: 출발지 경도, 위도
        end_x, end_y: 도착지 경도, 위도
        client: 재사용할 HTTP 클라이언트 (Optional)
    
    Returns:
        list[tuple[float, float]]: 경로상의 (위도, 경도) 좌표 리스트
    """
    if not KAKAO_REST_API_KEY:
        logger.error("KAKAO_REST_API_KEY가 설정되지 않았습니다.")
        return []
        
    url = "https://apis-navi.kakaomobility.com/v1/directions"
    headers = {"Authorization": f"KakaoAK {KAKAO_REST_API_KEY}"}
    params = {
        "origin": f"{start_x},{start_y}",
        "destination": f"{end_x},{end_y}",
        "priority": "RECOMMEND"  # 추천 경로
    }
    
    try:
        if client:
            response = await client.get(url, headers=headers, params=params)
        else:
            async with httpx.AsyncClient() as new_client:
                response = await new_client.get(url, headers=headers, params=params)
            
        response.raise_for_status()
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
            
            logger.info(f"Kakao 경로 좌표 {len(coordinates)}개 추출됨")
            return coordinates
        else:
            logger.warning("경로를 찾을 수 없습니다.")
            return []

    except httpx.HTTPStatusError as e:
        logger.error(f"카카오 Mobility API HTTP 오류: {e.response.status_code} - {e.response.text}")
        return []
    except httpx.RequestError as e:
        logger.error(f"카카오 Mobility API 요청 오류: {str(e)}")
        return []
    except Exception as e:
        logger.error(f"경로 좌표 조회 중 예기치 못한 오류 발생: {str(e)}")
        return []


async def get_route_coordinates(
    start_x: float,
    start_y: float,
    end_x: float,
    end_y: float,
    client: Optional[httpx.AsyncClient] = None
) -> list[tuple[float, float]]:

    # 기본은 TMAP 사용
    coords = await get_route_coordinates_tmap_transit(
        start_x, start_y, end_x, end_y, client
    )

    # TMAP 실패 시 Kakao fallback
    if not coords:
        logger.warning("TMAP 경로 조회 실패 → Kakao fallback 사용")
        coords = await get_route_coordinates_kakao(
            start_x, start_y, end_x, end_y, client
        )

    return coords
