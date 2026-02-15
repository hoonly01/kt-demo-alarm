from fastapi import APIRouter, HTTPException, Query, BackgroundTasks, Request
from typing import Optional, Dict
import logging
from datetime import datetime

from app.services.bus_notice_service import BusNoticeService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/bus", tags=["bus-notice"])

# --- Webhook Endpoints ---

@router.post("/webhook/bus_info")
async def webhook_bus_info():
    """버스 정보 조회 (카카오톡)"""
    # 간단한 안내 메시지 반환
    return {
        "version": "2.0",
        "template": {
            "outputs": [
                {
                    "simpleText": {
                        "text": "📅 오늘 버스 정보 조회\n\n특정 노선의 통제 정보를 확인하려면\n'100' 또는 '100번'이라고 입력하세요."
                    }
                }
            ]
        }
    }

@router.post("/webhook/route_check")
async def webhook_route_check(request: Request, background_tasks: BackgroundTasks):
    """노선 통제 확인 (콜백 지원)"""
    try:
        body = await request.json()
        logger.info(f"Route Check Request: {body}")
        
        user_request = body.get('userRequest', {})
        action = body.get('action', {})
        params = action.get('params', {})
        
        callback_url = user_request.get('callbackUrl')
        route_number = params.get('route_number')
        
        if not route_number:
            return {
                "version": "2.0",
                "template": {"outputs": [{"simpleText": {"text": "버스 노선 번호를 입력해주세요."}}]}
            }
            
        # 콜백 처리가 가능한 경우
        if callback_url:
            background_tasks.add_task(
                BusNoticeService.process_route_check_background,
                route_number, params, callback_url
            )
            return {
                "version": "2.0",
                "useCallback": True,
                "data": {"text": "잠시만 기다려주세요... 이미지를 생성 중입니다."}
            }
        
        # 콜백이 없는 경우 (동기 처리 - 타임아웃 위험)
        # 간단히 텍스트 정보만 반환
        date_str = params.get('date') or BusNoticeService.korean_date_string()
        controls = BusNoticeService.get_route_controls(route_number, date_str)
        
        if not controls:
            return {
                "version": "2.0",
                "template": {"outputs": [{"simpleText": {"text": f"📅 {date_str}\n노선 {route_number}에 대한 통제 정보가 없습니다."}}]}
            }
            
        text = f"🚌 노선 {route_number} 통제 정보 ({len(controls)}건)\n📅 {date_str}\n\n"
        for c in controls[:3]:
            text += f"📄 {c['notice_title'][:20]}...\n"
            text += f"🔄 {c.get('detour_route', '정보없음')[:30]}...\n\n"
            
        return {
            "version": "2.0",
            "template": {"outputs": [{"simpleText": {"text": text}}]}
        }
            
    except Exception as e:
        logger.error(f"Route Check Error: {e}")
        return {
            "version": "2.0",
            "template": {"outputs": [{"simpleText": {"text": "오류가 발생했습니다."}}]}
        }

@router.post("/webhook/route_image")
async def webhook_route_image(request: Request, background_tasks: BackgroundTasks):
    """노선 이미지 요청 (route_check와 동일하게 처리)"""
    return await webhook_route_check(request, background_tasks)

@router.post("/webhook/help")
async def webhook_help():
    """도움말"""
    return {
        "version": "2.0",
        "template": {
            "outputs": [
                {
                    "simpleText": {
                        "text": "🆘 도움말\n\n1. '오늘 버스 정보' - 전체 통제 현황\n2. '100번 확인해줘' - 노선 텍스트 정보\n3. '100번 이미지' - 노선 우회 경로 이미지\n4. '내 주변 확인' - 주변 통제 정류소"
                    }
                }
            ]
        }
    }

# --- REST Endpoints ---

@router.get("/notices")
async def get_notices(date: Optional[str] = None):
    """공지사항 목록"""
    return BusNoticeService.get_notices(date)

@router.get("/routes/{route}/controls")
async def get_route_controls(route: str, date: str = Query(..., description="YYYY-MM-DD")):
    """노선별 통제 정보"""
    return BusNoticeService.get_route_controls(route, date)

@router.post("/position/controls")
async def get_position_controls(request: Request):
    """위치 기반 통제 조회"""
    body = await request.json()
    tm_x = body.get('tm_x')
    tm_y = body.get('tm_y')
    radius = body.get('radius', 500)

    # 좌표 존재 여부 검증 (0 / 0.0 은 허용)
    if tm_x is None or tm_y is None:
        raise HTTPException(status_code=400, detail="Coordinates required")

    # 좌표 및 반경 값 형식 검증 및 변환
    try:
        tm_x_val = float(tm_x)
        tm_y_val = float(tm_y)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid coordinate format")

    try:
        radius_val = float(radius)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid radius")

    stations = BusNoticeService.get_nearby_controls(tm_x_val, tm_y_val, radius_val)
    return {
        "success": True,
        "count": len(stations),
        "data": stations
    }
