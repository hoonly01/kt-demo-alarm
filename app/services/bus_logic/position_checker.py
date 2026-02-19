import requests
import xml.etree.ElementTree as ET


def get_stations_by_position(service_key, tm_x, tm_y, radius=500):
    """좌표 기준 반경 내 정류소 조회"""
    url = 'http://ws.bus.go.kr/api/rest/stationinfo/getStationByPos'
    params = {
        'serviceKey': service_key, 
        'tmX': tm_x, 
        'tmY': tm_y, 
        'radius': radius
    }
    
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        root = ET.fromstring(response.content.decode('utf-8'))
        
        stations = []
        for item in root.findall('.//itemList'):
            station_nm = item.find('stationNm')
            station_id = item.find('stationId')
            ars_id = item.find('arsId')
            
            if station_nm is not None and station_id is not None:
                stations.append({
                    'name': station_nm.text,
                    'id': station_id.text,
                    'ars_id': ars_id.text if ars_id is not None else ''
                })
        
        return stations
            
    except Exception as e:
        print(f"좌표 기반 정류소 조회 실패: {e}")
        return []


def check_control_by_position(crawler, notices, tm_x, tm_y, radius=500, target_date=None):
    """좌표 기준 반경 내 통제 정류소 확인"""
    # 해당 날짜의 공지사항 필터링
    filtered_notices = crawler.filter_by_date(notices, target_date)
    
    if not filtered_notices:
        print("해당 날짜에 통제 정보가 없습니다.")
        return
    
    # 좌표 기준 정류소 조회
    nearby_stations = get_stations_by_position(crawler.service_key, tm_x, tm_y, radius)
    
    if not nearby_stations:
        print("주변 정류소를 찾을 수 없습니다.")
        return
    
    print(f"\n{'='*60}")
    print(f"좌표 ({tm_x}, {tm_y}) 반경 {radius}m 내 통제 정류소 정보")
    if target_date:
        print(f"조회 날짜: {target_date}")
    print(f"{'='*60}")
    
    # 통제 정류소 목록 수집
    controlled_stations = {}
    notice_by_station = {}
    
    for notice in filtered_notices:
        station_info = notice.get('station_info', {})
        detour_routes = notice.get('detour_routes', {})
        
        for station_id, info in station_info.items():
            controlled_stations[station_id] = {
                'name': info.get('name', ''),
                'periods': info.get('periods', []),
                'affected_routes': info.get('affected_routes', [])
            }
            notice_by_station[station_id] = {
                'title': notice['title'],
                'detour_routes': detour_routes
            }
    
    # 주변 정류소와 통제 정류소 매칭
    found_controlled = False
    
    for nearby_station in nearby_stations:
        station_name = nearby_station['name']
        station_id = nearby_station['id']
        ars_id = nearby_station['ars_id']
        
        matched_control = None
        matched_key = None
        
        # ARS ID로 매칭 시도
        if ars_id and ars_id in controlled_stations:
            matched_control = controlled_stations[ars_id]
            matched_key = ars_id
        
        # 정류소 ID로 매칭 시도
        elif station_id in controlled_stations:
            matched_control = controlled_stations[station_id]
            matched_key = station_id
        
        # 이름으로 매칭 시도
        else:
            for ctrl_id, ctrl_info in controlled_stations.items():
                ctrl_name = ctrl_info['name']
                if ctrl_name and (station_name in ctrl_name or ctrl_name in station_name):
                    matched_control = ctrl_info
                    matched_key = ctrl_id
                    break
        
        # 매칭된 통제 정류소가 있으면 출력
        if matched_control and matched_key:
            found_controlled = True
            notice_info = notice_by_station[matched_key]
            
            print(f"\n🚨 통제 정류장: {station_name}")
            
            # 통제 노선
            if matched_control['affected_routes']:
                print(f"통제 노선: {', '.join(matched_control['affected_routes'])}")
            
            # 통제 기간
            if matched_control['periods']:
                periods_str = ', '.join(matched_control['periods'])
                print(f"통제 기간: {periods_str}")
            
            # 우회 경로 (각 노선별로)
            detour_routes = notice_info['detour_routes']
            if detour_routes and matched_control['affected_routes']:
                print(f"우회 경로:")
                for route in matched_control['affected_routes']:
                    if route in detour_routes:
                        print(f"  {route}: {detour_routes[route]}")
                    else:
                        print(f"  {route}: 정보 없음")
            
            # 관련 공지
            print(f"관련 공지: {notice_info['title']}")
            
            print("-" * 40)
    
    if not found_controlled:
        print("\n✅ 주변에 통제되는 정류소가 없습니다.")
        print(f"\n주변 정류소 목록 ({len(nearby_stations)}개):")
        for station in nearby_stations:
            ars_info = f" (ARS: {station['ars_id']})" if station['ars_id'] else ""
            print(f"  - {station['name']}{ars_info}")
