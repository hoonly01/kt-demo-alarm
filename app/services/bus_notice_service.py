import logging
import os
import asyncio
from datetime import datetime
import pytz
from typing import List, Dict, Optional, Any

from app.config.settings import settings
from app.services.bus_logic.restricted_bus import TOPISCrawler
from app.services.bus_logic.position_checker import get_stations_by_position

logger = logging.getLogger(__name__)
KST = pytz.timezone('Asia/Seoul')

class BusNoticeService:
    crawler: Optional[TOPISCrawler] = None
    cached_notices: Dict[str, Dict] = {}
    last_update: Optional[datetime] = None
    _image_task: Optional[asyncio.Task] = None  # GC 방지를 위한 태스크 참조 보관
    
    @classmethod
    async def initialize(cls):
        """크롤러 초기화 및 데이터 로드"""
        try:
            if not settings.GEMINI_API_KEY:
                logger.warning("⚠️ GEMINI_API_KEY가 설정되지 않아 버스 알림 서비스를 사용할 수 없습니다.")
                return

            logger.info("🚌 BusNoticeService 초기화 중...")
            
            # 크롤러 인스턴스 생성
            cls.crawler = TOPISCrawler(
                gemini_api_key=settings.GEMINI_API_KEY,
                cache_file="topis_cache/topis_cache.json"  # Docker 볼륨 마운트 경로 내 저장
            )
            
            # 초기 데이터 로드 (동기 함수를 비동기로 실행)
            cls.cached_notices, _ = await asyncio.to_thread(cls.crawler.crawl_notices)
            cls.last_update = datetime.now(KST)
            
            logger.info(f"✅ BusNoticeService 초기화 완료. {len(cls.cached_notices)}개 공지사항 로드됨")
            
            # 백그라운드 이미지 생성 시작 (참조 보관 → GC 방지 + 예외 로깅)
            def _log_task_error(task: asyncio.Task):
                if not task.cancelled() and task.exception():
                    logger.error(f"이미지 생성 태스크 오류: {task.exception()}")

            cls._image_task = asyncio.create_task(cls.generate_all_route_images())
            cls._image_task.add_done_callback(_log_task_error)
            
        except Exception as e:
            logger.error(f"❌ BusNoticeService 초기화 실패: {e}")
            cls.cached_notices = {}

    @classmethod
    async def refresh(cls):
        """매일 버스 통제 공지 재크롤링 (스케줄러에서 호출)
        
        크롤러가 초기화되지 않은 경우(서버 최초 기동 후 첫 실행) 자동으로 초기화합니다.
        """
        if not settings.GEMINI_API_KEY:
            logger.warning("⚠️ GEMINI_API_KEY가 설정되지 않아 버스 알림 서비스를 사용할 수 없습니다.")
            return

        # 크롤러 미초기화 시 자동 생성 (서버 시작 후 첫 스케줄러 실행)
        if not cls.crawler:
            logger.info("🚌 BusNoticeService 크롤러 최초 초기화...")
            cls.crawler = TOPISCrawler(
                gemini_api_key=settings.GEMINI_API_KEY,
                cache_file="topis_cache/topis_cache.json"
            )

        logger.info("🔄 버스 통제 공지 재갱신 시작...")
        try:
            cls.cached_notices, _ = await asyncio.to_thread(cls.crawler.crawl_notices)
            cls.last_update = datetime.now(KST)
            logger.info(f"✅ 재갱신 완료. {len(cls.cached_notices)}개 공지사항 로드됨")

            # 이미지 재생성 (백그라운드)
            # 이전 태스크가 아직 실행 중이면 취소 후 교체
            if cls._image_task and not cls._image_task.done():
                cls._image_task.cancel()

            def _log_image_error(task: asyncio.Task):
                if not task.cancelled() and task.exception():
                    logger.error(f"이미지 재생성 오류: {task.exception()}")

            cls._image_task = asyncio.create_task(cls.generate_all_route_images())
            cls._image_task.add_done_callback(_log_image_error)
        except Exception:
            logger.exception("❌ 버스 통제 공지 재갱신 실패")

    @classmethod
    def get_korean_time(cls):
        return datetime.now(KST)

    @classmethod
    def korean_date_string(cls):
        return cls.get_korean_time().strftime("%Y-%m-%d")

    @classmethod
    async def generate_all_route_images(cls):
        """모든 노선 이미지 사전 생성 (백그라운드)"""
        if not cls.crawler:
            return
            
        try:
            logger.info("🖼️ 모든 노선 이미지 사전 생성 시작...")
            total_generated = 0
            
            notices_to_process = list(cls.cached_notices.values()) if isinstance(cls.cached_notices, dict) else cls.cached_notices
            
            for notice in notices_to_process:
                route_pages = notice.get('route_pages', {})
                route_images = notice.get('route_images', {})
                
                if not route_pages:
                    continue
                
                for route_number in route_pages.keys():
                    # 이미 이미지가 있으면 스킵
                    if route_number in route_images and os.path.exists(route_images[route_number]):
                        continue
                        
                    # 이미지 생성 시도
                    await asyncio.to_thread(
                        cls._generate_image_sync, route_number, notice
                    )
                    total_generated += 1
                    await asyncio.sleep(0.5)  # 부하 조절
            
            if total_generated > 0:
                await asyncio.to_thread(cls.crawler._save_cache)
                logger.info(f"🎉 {total_generated}개 노선 이미지 신규 생성 완료")
                
        except Exception as e:
            logger.error(f"이미지 사전 생성 중 오류: {e}")

    @classmethod
    def _generate_image_sync(cls, route_number: str, notice: Dict) -> Optional[str]:
        """단일 이미지 생성 (동기 내부 메서드)"""
        try:
            attachments = notice.get('attachments', [])
            route_pages = notice.get('route_pages', {})
            
            if not attachments or route_number not in route_pages:
                return None
                
            page_num = route_pages[route_number]
            notice_seq = notice['seq']
            
            # 첫 번째 첨부파일만 처리
            attachment = attachments[0]
            file_path = cls.crawler._download_attachment(attachment, save_to_folder=True)
            
            if file_path:
                converted_path = cls.crawler._convert_hwp_to_pdf(file_path)
                
                if converted_path.lower().endswith('.pdf'):
                    image_path = cls.crawler._convert_pdf_page_to_image(
                        converted_path, page_num - 1, route_number, notice_seq
                    )
                    
                    if image_path and os.path.exists(image_path):
                        # 캐시 업데이트
                        if 'route_images' not in notice:
                            notice['route_images'] = {}
                        notice['route_images'][route_number] = image_path
                        
                        # URL 반환
                        filename = os.path.basename(image_path)
                        # TODO: 호스트 도메인은 요청 컨텍스트나 설정에서 가져와야 함
                        return f"/static/route_images/{filename}"
            return None
        except Exception as e:
            logger.error(f"이미지 생성 실패 ({route_number}): {e}")
            return None

    @classmethod
    def get_notices(cls, date_str: Optional[str] = None) -> List[Dict]:
        """공지사항 조회"""
        if not cls.crawler:
            return []
        
        # 캐시가 딕셔너리면 리스트로 변환
        notices = cls.cached_notices
        
        if date_str:
            return cls.crawler.filter_by_date(notices, date_str)
        
        if isinstance(notices, dict):
            return list(notices.values())
        return notices

    @classmethod
    def get_route_controls(cls, route_number: str, date_str: str) -> List[Dict]:
        """노선별 통제 정보 조회"""
        if not cls.crawler:
            return []
        return cls.crawler.get_control_info_by_route(cls.cached_notices, date_str, route_number)

    @classmethod
    def get_nearby_controls(cls, tm_x: float, tm_y: float, radius: int) -> List[Dict]:
        """주변 정류소 조회"""
        if not cls.crawler:
            return []
        return get_stations_by_position(cls.crawler.service_key, tm_x, tm_y, radius)

    @classmethod
    async def generate_route_image(cls, route_number: str, date_str: str) -> Optional[str]:
        """실시간 이미지 생성 요청"""
        if not cls.crawler:
            return None
            
        notices = cls.crawler.filter_by_date(cls.cached_notices, date_str)
        if not notices:
            return None
            
        target_notice = None
        for notice in notices:
            route_pages = notice.get('route_pages', {})
            if route_number in route_pages:
                target_notice = notice
                break
        
        if not target_notice:
            return None
            
        # 이미지 생성 (캐시에 있으면 바로 리턴)
        route_images = target_notice.get('route_images', {})
        if route_number in route_images and os.path.exists(route_images[route_number]):
            filename = os.path.basename(route_images[route_number])
            return f"/static/route_images/{filename}"
            
        # 없으면 생성
        image_url = await asyncio.to_thread(cls._generate_image_sync, route_number, target_notice)
        if image_url:
            await asyncio.to_thread(cls.crawler._save_cache)
            
        return image_url

    @classmethod
    async def process_route_check_background(cls, route_number: str, params: Dict, callback_url: str):
        """백그라운드에서 노선 확인 및 콜백 전송"""
        try:
            target_date = params.get('date', '').strip()
            if not target_date:
                target_date = cls.korean_date_string()
            
            # 노선 번호 정규화 (필요시)
            normalized_route = route_number.replace("-", "").strip()
            
            if not cls.crawler:
                await cls.send_error_callback(callback_url, normalized_route, "서비스를 사용할 수 없습니다.")
                return

            notices = cls.crawler.filter_by_date(cls.cached_notices, target_date)
            if not notices:
                await cls.send_error_callback(callback_url, normalized_route, f"날짜 {target_date}에 통제 정보가 없습니다.")
                return

            # 해당 노선 찾기
            target_notice = None
            for notice in notices:
                route_pages = notice.get('route_pages', {})
                if normalized_route in route_pages:
                    target_notice = notice
                    break
            
            # 없으면 기존 이미지라도 있는지 확인 (다른 공지에서)
            if not target_notice:
                for notice in notices:
                    if normalized_route in notice.get('route_images', {}):
                        target_notice = notice
                        break
            
            if not target_notice:
                await cls.send_error_callback(callback_url, normalized_route, f"날짜 {target_date}에 노선 {normalized_route}의 통제 정보가 없습니다.")
                return

            # 이미지 생성/조회
            image_url = await cls.generate_route_image(normalized_route, target_date)
            
            if image_url:
                # 성공 콜백
                notice_title = target_notice.get('title', '제목 없음')
                detour_routes = target_notice.get('detour_routes', {})
                detour_path = detour_routes.get(normalized_route, '')
                
                # 통제기간 수집
                control_periods = []
                station_info = target_notice.get('station_info', {})
                for station_id, info in station_info.items():
                    if normalized_route in info.get('affected_routes', []):
                        control_periods.extend(info.get('periods', []))
                control_periods.extend(target_notice.get('general_periods', []))
                
                await cls.send_success_callback(
                    callback_url, normalized_route, target_date, 
                    notice_title, detour_path, image_url, control_periods
                )
            else:
                await cls.send_error_callback(callback_url, normalized_route, "이미지 생성에 실패했습니다.")

        except Exception as e:
            logger.error(f"백그라운드 처리 오류: {e}")
            await cls.send_error_callback(callback_url, route_number, f"시스템 오류: {str(e)[:50]}")

    @classmethod
    async def send_success_callback(cls, callback_url: str, route_number: str, target_date: str, 
                                  notice_title: str, detour_path: str, image_url: str, control_periods: List[str]):
        """성공 콜백 전송"""
        import aiohttp
        
        info_text = f"✅ 이미지 생성 완료!\n\n"
        info_text += f"🚌 노선 {route_number}번 우회 경로\n"
        info_text += f"📅 {target_date}\n\n"
        
        # 통제기간 표시
        if control_periods:
            unique_periods = sorted(list(set(control_periods)))
            if len(unique_periods) == 1:
                info_text += f"⏰ 통제기간: {unique_periods[0]}\n"
            else:
                main_period = unique_periods[0]
                info_text += f"⏰ 통제기간: {main_period} 외 {len(unique_periods)-1}개 구간\n"
        
        if notice_title:
            title_short = notice_title[:50] + '...' if len(notice_title) > 50 else notice_title
            info_text += f"📄 {title_short}\n"
        if detour_path:
            detour_short = detour_path[:60] + '...' if len(detour_path) > 60 else detour_path
            info_text += f"🔄 우회: {detour_short}\n"
        info_text += "\n📍 자세한 우회 경로는 아래 이미지를 확인하세요."
        
        # 도메인 추가 (이미지 URL이 상대경로인 경우)
        full_image_url = image_url
        if image_url.startswith("/"):
            base_url = settings.RENDER_EXTERNAL_URL
            full_image_url = f"{base_url}{image_url}"

        callback_message = {
            "version": "2.0",
            "template": {
                "outputs": [
                    {"simpleText": {"text": info_text}},
                    {
                        "simpleImage": {
                            "imageUrl": full_image_url,
                            "altText": f"{route_number}번 버스 우회 경로"
                        }
                    }
                ]
            }
        }
        
        await cls._send_callback_request(callback_url, callback_message)

    @classmethod
    async def send_error_callback(cls, callback_url: str, route_number: str, error_message: str):
        """오류 콜백 전송"""
        callback_message = {
            "version": "2.0",
            "template": {
                "outputs": [
                    {
                        "simpleText": {
                            "text": f"❌ 노선 {route_number}번\n\n{error_message}\n\n다시 시도해주세요."
                        }
                    }
                ]
            }
        }
        await cls._send_callback_request(callback_url, callback_message)

    @classmethod
    async def _send_callback_request(cls, url: str, data: Dict):
        """실제 콜백 요청 전송 (aiohttp 사용)"""
        import aiohttp
        try:
            timeout = aiohttp.ClientTimeout(total=5)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, json=data) as response:
                    logger.info(f"콜백 전송 결과: {response.status}")
        except Exception as e:
            logger.error(f"콜백 전송 실패: {e}")

