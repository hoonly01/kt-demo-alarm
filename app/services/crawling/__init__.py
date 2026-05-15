"""SMPA 집회 수집 패키지의 공개 진입점."""

from app.services.crawling.smpa_event_sync import SyncResult
from app.services.crawling.smpa_pipeline import crawl_and_sync_smpa_events

__all__ = ["SyncResult", "crawl_and_sync_smpa_events"]
