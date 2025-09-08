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
    ('language', 'TEXT')
]