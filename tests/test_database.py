"""Test database models and connections"""
import pytest
import sqlite3
from app.database.connection import init_db, get_db_connection


def test_database_initialization(test_db):
    """Test database initialization creates all required tables"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Check that all tables exist
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' 
            ORDER BY name
        """)
        tables = [row[0] for row in cursor.fetchall()]
        
        expected_tables = ['alarm_tasks', 'events', 'users']
        for table in expected_tables:
            assert table in tables, f"Table '{table}' not found"


def test_users_table_schema(clean_test_db):
    """Test users table has correct schema"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Insert a test user
        cursor.execute("""
            INSERT INTO users (bot_user_key, active, departure_name)
            VALUES (?, ?, ?)
        """, ("test_user", True, "Test Station"))
        
        # Verify insertion worked
        cursor.execute("SELECT * FROM users WHERE bot_user_key = ?", ("test_user",))
        row = cursor.fetchone()
        assert row is not None


def test_events_table_schema(clean_test_db):
    """Test events table has correct schema"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Insert a test event
        cursor.execute("""
            INSERT INTO events (title, location_name, latitude, longitude, start_date)
            VALUES (?, ?, ?, ?, ?)
        """, ("Test Event", "Test Location", 37.5665, 126.9780, "2025-01-01 10:00:00"))
        
        # Verify insertion worked
        cursor.execute("SELECT * FROM events WHERE title = ?", ("Test Event",))
        row = cursor.fetchone()
        assert row is not None


def test_alarm_tasks_table_schema(clean_test_db):
    """Test alarm_tasks table has correct schema"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Insert a test alarm task
        cursor.execute("""
            INSERT INTO alarm_tasks (task_id, alarm_type, status)
            VALUES (?, ?, ?)
        """, ("test-task-123", "individual", "pending"))
        
        # Verify insertion worked
        cursor.execute("SELECT * FROM alarm_tasks WHERE task_id = ?", ("test-task-123",))
        row = cursor.fetchone()
        assert row is not None


def test_database_connection_context_manager(clean_test_db):
    """Test database connection context manager works correctly"""
    # Test successful connection
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        result = cursor.fetchone()
        assert result[0] == 1
    
    # Connection should be closed after context manager
    # (We can't easily test this without accessing private attributes)


def test_database_foreign_key_constraint(clean_test_db):
    """Test foreign key relationships work correctly"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # First create an event
        cursor.execute("""
            INSERT INTO events (id, title, location_name, latitude, longitude, start_date)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (1, "Test Event", "Test Location", 37.5665, 126.9780, "2025-01-01 10:00:00"))
        
        # Now create an alarm task referencing the event
        cursor.execute("""
            INSERT INTO alarm_tasks (task_id, alarm_type, status, event_id)
            VALUES (?, ?, ?, ?)
        """, ("test-task-123", "individual", "pending", 1))
        
        # Verify the relationship
        cursor.execute("""
            SELECT at.task_id, e.title 
            FROM alarm_tasks at
            JOIN events e ON at.event_id = e.id
            WHERE at.task_id = ?
        """, ("test-task-123",))
        
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == "test-task-123"
        assert row[1] == "Test Event"