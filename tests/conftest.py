"""Test configuration and fixtures"""
import pytest
import os
import sqlite3
import tempfile
from fastapi.testclient import TestClient
from app.database.connection import init_db, DATABASE_PATH


@pytest.fixture(scope="session")
def test_db():
    """Create a test database for the session"""
    from unittest.mock import patch
    
    # Use a temporary database for testing
    test_db_path = tempfile.mktemp(suffix=".db")
    
    # Patch settings
    with patch("app.config.settings.settings.DATABASE_PATH", test_db_path), \
         patch("app.config.settings.settings.API_KEY", "test-api-key"):
        
        # Also need to patch the variable in connection module if it was already imported
        import app.database.connection as db_module
        original_db_path = db_module.DATABASE_PATH
        db_module.DATABASE_PATH = test_db_path
        
        # Initialize test database
        init_db()
        
        yield test_db_path
        
        # Cleanup
        try:
            os.remove(test_db_path)
        except FileNotFoundError:
            pass
        
        # Restore original database path (although patch handles settings, module var needs manual restore)
        db_module.DATABASE_PATH = original_db_path


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