"""데이터베이스 스키마 정의"""


USERS_TABLE_SCHEMA = '''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        bot_user_key TEXT UNIQUE NOT NULL,
        first_message_at DATETIME,
        last_message_at DATETIME,
        message_count INTEGER DEFAULT 1,
        location TEXT,
        active BOOLEAN DEFAULT TRUE,
        -- 경로 정보
        departure_name TEXT, 
        departure_address TEXT, 
        departure_x REAL, 
        departure_y REAL, 
        arrival_name TEXT, 
        arrival_address TEXT, 
        arrival_x REAL, 
        arrival_y REAL, 
        route_updated_at DATETIME,
        -- 개인화 설정
        marked_bus TEXT,
        language TEXT
    )
'''

EVENTS_TABLE_SCHEMA = '''
    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        description TEXT,
        location_name TEXT NOT NULL,
        location_address TEXT,
        latitude REAL NOT NULL,
        longitude REAL NOT NULL,
        start_date DATETIME NOT NULL,
        end_date DATETIME,
        category TEXT,
        severity_level INTEGER DEFAULT 1,  -- 1: 낮음, 2: 보통, 3: 높음
        status TEXT DEFAULT 'active',     -- active, ended, cancelled
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
'''

ALARM_TASKS_TABLE_SCHEMA = '''
    CREATE TABLE IF NOT EXISTS alarm_tasks (
        task_id TEXT PRIMARY KEY,
        alarm_type TEXT NOT NULL,  -- individual, bulk, filtered
        status TEXT DEFAULT 'pending',  -- pending, processing, completed, failed, partial
        total_recipients INTEGER DEFAULT 0,
        successful_sends INTEGER DEFAULT 0,
        failed_sends INTEGER DEFAULT 0,
        event_id INTEGER,  -- FK to events table (if applicable)
        request_data TEXT,  -- JSON string of original request
        error_messages TEXT,  -- JSON array of error messages
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        completed_at DATETIME,
        FOREIGN KEY (event_id) REFERENCES events (id)
    )
'''

# 동적으로 추가할 수 있는 컬럼 정의
ROUTE_COLUMNS = [
    ('departure_name', 'TEXT'),
    ('departure_address', 'TEXT'),
    ('departure_x', 'REAL'),
    ('departure_y', 'REAL'),
    ('arrival_name', 'TEXT'),
    ('arrival_address', 'TEXT'),
    ('arrival_x', 'REAL'),
    ('arrival_y', 'REAL'),
    ('route_updated_at', 'DATETIME'),
    ('marked_bus', 'TEXT'),
    ('language', 'TEXT'),
    ('open_id', 'TEXT'),  # 웹훅에서만 제공
    ('plusfriend_user_key', 'TEXT')  # Skill Block에서 제공 (실질적 primary key)
]