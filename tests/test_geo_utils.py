import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.utils.geo_utils import (
    haversine_distance,
    is_point_near_route,
    is_event_near_route_accurate,
    get_location_info,
    get_route_coordinates
)
import httpx

@pytest.mark.asyncio
async def test_haversine_distance():
    # Seoul to Busan approx dist
    lat1, lon1 = 37.5665, 126.9780
    lat2, lon2 = 35.1796, 129.0756
    dist = haversine_distance(lat1, lon1, lat2, lon2)
    assert dist > 300000  # > 300km
    assert dist < 400000  # < 400km

    # Same point
    assert haversine_distance(lat1, lon1, lat1, lon1) == 0

def test_is_point_near_route():
    # Start (0,0), End (0, 10). Length approx 1110km (1 degree lat is ~111km)
    # Actually let's use small coordinates for easier mental model, but haversine works on sphere.
    # Let's use real world small distance.
    # Gangnam station
    lat1, lon1 = 37.4979, 127.0276
    # Yeoksam station
    lat2, lon2 = 37.5006, 127.0364
    
    # Validation: Point is exactly on one of the endpoints
    assert is_point_near_route(lat1, lon1, lat2, lon2, lat1, lon1) is True
    
    # Validation: Point is far away
    # Busan
    assert is_point_near_route(lat1, lon1, lat2, lon2, 35.1796, 129.0756) is False

def test_is_event_near_route_accurate():
    route = [(37.4979, 127.0276), (37.5006, 127.0364)]
    # Event at first point
    assert is_event_near_route_accurate(route, 37.4979, 127.0276) is True
    # Event far away
    assert is_event_near_route_accurate(route, 35.1796, 129.0756) is False
    # Empty route
    assert is_event_near_route_accurate([], 37.4979, 127.0276) is False

@pytest.mark.asyncio
async def test_get_location_info_mocked():
    mock_response = {
        "documents": [{
            "place_name": "Test Place",
            "road_address_name": "Test Address",
            "x": "127.0",
            "y": "37.0"
        }]
    }
    
    # Mock the API Key
    with patch("app.utils.geo_utils.KAKAO_REST_API_KEY", "test_key"):
        # Test with injected client
        client = AsyncMock(spec=httpx.AsyncClient)
        client.get.return_value = MagicMock(
            status_code=200,
            json=lambda: mock_response,
            raise_for_status=lambda: None
        )
        
        result = await get_location_info("query", client=client)
        assert result["name"] == "Test Place"
        assert result["x"] == 127.0
        
        # Test internal client creation (patch httpx.AsyncClient)
        with patch("httpx.AsyncClient") as MockClient:
            # Configure the mock client returned by the context manager
            mock_client_instance = MockClient.return_value.__aenter__.return_value
            mock_client_instance.get.return_value = MagicMock(
                status_code=200,
                json=lambda: mock_response,
                raise_for_status=lambda: None,
            )
            
            result = await get_location_info("query")
            assert result["name"] == "Test Place"

@pytest.mark.asyncio
async def test_get_route_coordinates_mocked():
    mock_response = {
        "routes": [{
            "sections": [{
                "roads": [{
                    "vertexes": [127.0, 37.0, 127.1, 37.1]
                }]
            }]
        }]
    }
    
    # Mock the API Key
    with patch("app.utils.geo_utils.KAKAO_REST_API_KEY", "test_key"):
        client = AsyncMock(spec=httpx.AsyncClient)
        client.get.return_value = MagicMock(
            status_code=200,
            json=lambda: mock_response,
            raise_for_status=lambda: None
        )
        
        result = await get_route_coordinates(127.0, 37.0, 127.1, 37.1, client=client)
        assert len(result) == 2
        assert result[0] == (37.0, 127.0) # Lat, Lon
        assert result[1] == (37.1, 127.1)
