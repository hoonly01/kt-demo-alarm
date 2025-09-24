"""Test alarm status service functionality"""
import pytest
from datetime import datetime
import json
from app.services.alarm_status_service import AlarmStatusService


def test_create_alarm_task_basic(clean_test_db):
    """Test basic alarm task creation"""
    task_id = AlarmStatusService.create_alarm_task(
        alarm_type="individual",
        total_recipients=1
    )
    
    assert task_id is not None
    assert len(task_id) == 36  # UUID4 format
    
    # Verify task was created
    status = AlarmStatusService.get_alarm_task_status(task_id)
    assert status is not None
    assert status["alarm_type"] == "individual"
    assert status["status"] == "pending"
    assert status["total_recipients"] == 1


def test_create_alarm_task_with_data(clean_test_db):
    """Test alarm task creation with request data"""
    request_data = {
        "user_id": "test_user_123",
        "event_name": "test_event",
        "data": {"message": "Test message"}
    }
    
    task_id = AlarmStatusService.create_alarm_task(
        alarm_type="individual",
        total_recipients=1,
        event_id=42,
        request_data=request_data
    )
    
    status = AlarmStatusService.get_alarm_task_status(task_id)
    assert status is not None
    assert status["event_id"] == 42
    assert status["request_data"] == request_data


def test_update_alarm_task_status_success(clean_test_db):
    """Test updating alarm task status to success"""
    task_id = AlarmStatusService.create_alarm_task(
        alarm_type="bulk",
        total_recipients=5
    )
    
    # Update to processing
    success = AlarmStatusService.update_alarm_task_status(
        task_id, "processing"
    )
    assert success is True
    
    status = AlarmStatusService.get_alarm_task_status(task_id)
    assert status["status"] == "processing"
    
    # Update to completed
    success = AlarmStatusService.update_alarm_task_status(
        task_id, "completed", 
        successful_sends=4, 
        failed_sends=1
    )
    assert success is True
    
    status = AlarmStatusService.get_alarm_task_status(task_id)
    assert status["status"] == "completed"
    assert status["successful_sends"] == 4
    assert status["failed_sends"] == 1
    assert status["success_rate"] == 80.0  # 4/5 = 80%
    assert status["completed_at"] is not None


def test_update_alarm_task_status_with_errors(clean_test_db):
    """Test updating alarm task status with error messages"""
    task_id = AlarmStatusService.create_alarm_task(
        alarm_type="individual",
        total_recipients=1
    )
    
    error_messages = ["Network timeout", "Invalid user ID"]
    success = AlarmStatusService.update_alarm_task_status(
        task_id, "failed",
        failed_sends=1,
        error_messages=error_messages
    )
    assert success is True
    
    status = AlarmStatusService.get_alarm_task_status(task_id)
    assert status["status"] == "failed"
    assert status["error_messages"] == error_messages


def test_update_nonexistent_task(clean_test_db):
    """Test updating non-existent task"""
    success = AlarmStatusService.update_alarm_task_status(
        "nonexistent-task-id", "completed"
    )
    assert success is False


def test_get_nonexistent_task_status(clean_test_db):
    """Test getting status for non-existent task"""
    status = AlarmStatusService.get_alarm_task_status("nonexistent-task-id")
    assert status is None


def test_get_recent_alarm_tasks_empty(clean_test_db):
    """Test getting recent tasks when none exist"""
    tasks = AlarmStatusService.get_recent_alarm_tasks()
    assert isinstance(tasks, list)
    assert len(tasks) == 0


def test_get_recent_alarm_tasks_with_data(clean_test_db):
    """Test getting recent tasks with some data"""
    # Create some tasks
    task_ids = []
    for i in range(3):
        task_id = AlarmStatusService.create_alarm_task(
            alarm_type="individual",
            total_recipients=1
        )
        task_ids.append(task_id)
    
    tasks = AlarmStatusService.get_recent_alarm_tasks(limit=10)
    assert len(tasks) == 3
    
    # Should be ordered by created_at DESC
    task_ids_from_result = [task["task_id"] for task in tasks]
    assert task_ids_from_result == list(reversed(task_ids))


def test_cleanup_old_tasks_none(clean_test_db):
    """Test cleanup when no old tasks exist"""
    deleted_count = AlarmStatusService.cleanup_old_tasks(days=1)
    assert deleted_count == 0


def test_success_rate_calculation(clean_test_db):
    """Test success rate calculation for different scenarios"""
    # Test case 1: All successful
    task_id = AlarmStatusService.create_alarm_task(
        alarm_type="bulk", total_recipients=10
    )
    AlarmStatusService.update_alarm_task_status(
        task_id, "completed", successful_sends=10, failed_sends=0
    )
    status = AlarmStatusService.get_alarm_task_status(task_id)
    assert status["success_rate"] == 100.0
    
    # Test case 2: Partial success
    task_id = AlarmStatusService.create_alarm_task(
        alarm_type="bulk", total_recipients=10
    )
    AlarmStatusService.update_alarm_task_status(
        task_id, "completed", successful_sends=7, failed_sends=3
    )
    status = AlarmStatusService.get_alarm_task_status(task_id)
    assert status["success_rate"] == 70.0
    
    # Test case 3: All failed
    task_id = AlarmStatusService.create_alarm_task(
        alarm_type="bulk", total_recipients=5
    )
    AlarmStatusService.update_alarm_task_status(
        task_id, "failed", successful_sends=0, failed_sends=5
    )
    status = AlarmStatusService.get_alarm_task_status(task_id)
    assert status["success_rate"] == 0.0
    
    # Test case 4: No recipients
    task_id = AlarmStatusService.create_alarm_task(
        alarm_type="individual", total_recipients=0
    )
    status = AlarmStatusService.get_alarm_task_status(task_id)
    assert status["success_rate"] == 0.0