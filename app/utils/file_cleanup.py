import os
import time
import logging
import pathlib
from app.config.settings import settings

logger = logging.getLogger(__name__)

def get_attachment_dir() -> pathlib.Path:
    """첨부파일 저장 디렉토리 경로 반환"""
    # crawling_service.py의 동일한 로직 복제 또는 직접 사용
    base_dir = pathlib.Path(__file__).resolve().parent.parent.parent
    return base_dir / "attachments"

def cleanup_old_files(days: int = 30):
    """30일이 지난 집회 이미지 및 버스 경로 이미지를 안전하게 삭제합니다."""
    logger.info(f"🧹 [파일 정리] {days}일이 지난 이미지 파일 정리를 시작합니다.")
    
    # 1. 집회 이미지 폴더 (attachments/protest_images)
    protest_img_dir = get_attachment_dir() / "protest_images"
    
    # 2. 버스 경로 이미지 폴더 (topis_attachments/route_images)
    route_img_dir = pathlib.Path(settings.ATTACHMENT_FOLDER) / "route_images"
    
    now = time.time()
    cutoff = now - (days * 86400)
    
    deleted_count = 0
    errors_count = 0
    
    for folder in [protest_img_dir, route_img_dir]:
        folder_path = pathlib.Path(folder)
        if not folder_path.exists():
            logger.warning(f"[파일 정리] 폴더가 존재하지 않습니다: {folder_path}")
            continue
            
        logger.info(f"[파일 정리] 폴더 검사 중: {folder_path}")
        for file_path in folder_path.iterdir():
            if not file_path.is_file():
                continue
                
            # .gitkeep 이나 정적 필요한 파일 제외 (있다면)
            if file_path.name.startswith("."):
                continue
                
            try:
                mtime = file_path.stat().st_mtime
                if mtime < cutoff:
                    file_path.unlink()
                    deleted_count += 1
                    logger.info(f"[파일 정리] 오래된 파일 삭제 완료: {file_path.name}")
            except Exception as e:
                errors_count += 1
                logger.error(f"[파일 정리] 파일 삭제 오류 ({file_path}): {e}")
                
    logger.info(f"🧹 [파일 정리 완료] 총 {deleted_count}개 파일 삭제됨 (오류: {errors_count}건)")
