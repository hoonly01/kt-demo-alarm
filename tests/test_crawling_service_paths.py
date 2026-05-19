from pathlib import Path

from app.services.crawling_service import CrawlingService, get_attachment_dir


def test_crawling_service_exposes_attachment_dir_class_api():
    attachment_dir = CrawlingService.get_attachment_dir()

    assert attachment_dir == get_attachment_dir()
    assert isinstance(attachment_dir, Path)
    assert attachment_dir.exists()
