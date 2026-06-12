"""Test configuration and fixtures"""
import pytest
import os
import sqlite3
import tempfile
from fastapi.testclient import TestClient
from app.config.settings import settings
from app.database.connection import init_db


@pytest.fixture(scope="session")
def test_db():
    """Create a test database for the session"""
    fd, test_db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    original_database_path = settings.DATABASE_PATH
    original_api_key = settings.API_KEY

    settings.DATABASE_PATH = test_db_path
    settings.API_KEY = "test-api-key"
    init_db()

    yield test_db_path

    settings.DATABASE_PATH = original_database_path
    settings.API_KEY = original_api_key

    try:
        os.remove(test_db_path)
    except FileNotFoundError:
        pass


@pytest.fixture(scope="function")
def clean_test_db(test_db):
    """Clean the test database before each test"""
    conn = sqlite3.connect(test_db)
    cursor = conn.cursor()
    
    # Clear all tables
    cursor.execute("DELETE FROM users")
    cursor.execute("DELETE FROM events")
    cursor.execute("DELETE FROM alarm_tasks")
    
    conn.commit()
    conn.close()
    
    yield test_db


@pytest.fixture
def test_client():
    """Create a test client"""
    from main import app
    return TestClient(app)


@pytest.fixture
def sample_event_data():
    """Sample event data for testing"""
    return {
        "title": "Test Event",
        "description": "Test event description",
        "location_name": "Test Location",
        "location_address": "123 Test St",
        "latitude": 37.5665,
        "longitude": 126.9780,
        "start_date": "2025-01-01 10:00:00",
        "end_date": "2025-01-01 12:00:00",
        "category": "test",
        "severity_level": 1
    }


@pytest.fixture
def sample_user_data():
    """Sample user data for testing"""
    return {
        "bot_user_key": "test_user_123",
        "departure_name": "강남역",
        "departure_x": 127.0278,
        "departure_y": 37.4979,
        "arrival_name": "광화문역",
        "arrival_x": 126.9769,
        "arrival_y": 37.5709,
        "active": True
    }


@pytest.fixture
def settings_overrides():
    """테스트 중 settings 값을 직접 바꾸고 종료 시 복구한다."""
    originals = {}

    def apply(**overrides):
        for key, value in overrides.items():
            if key not in originals:
                originals[key] = getattr(settings, key)
            setattr(settings, key, value)

    yield apply

    for key, value in originals.items():
        setattr(settings, key, value)
