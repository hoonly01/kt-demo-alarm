-- 테스트 집회 데이터 삽입 SQL
-- 영통역-광화문역 경로 상에 있을 만한 종로구 집회 데이터

-- 기존 테스트 데이터 삭제 (선택사항)
-- DELETE FROM events WHERE title LIKE '%테스트%';

-- 1. 광화문역 근처 집회 (높은 심각도)
INSERT INTO events (
    title, description, location_name, location_address,
    latitude, longitude, start_date, end_date,
    category, severity_level, status
) VALUES (
    '민주노총 총파업 집회 [테스트]',
    '대규모 집회가 예정되어 있습니다. 교통 통제가 있을 수 있습니다.',
    '광화문광장',
    '서울특별시 종로구 세종대로 172',
    37.5720164,
    126.9769814,
    datetime('now', '+1 day', '14:00:00'),
    datetime('now', '+1 day', '18:00:00'),
    '노동',
    3,  -- 높음
    'active'
);

-- 2. 경복궁 근처 집회 (보통 심각도)
INSERT INTO events (
    title, description, location_name, location_address,
    latitude, longitude, start_date, end_date,
    category, severity_level, status
) VALUES (
    '환경보호 캠페인 [테스트]',
    '기후변화 대응을 촉구하는 평화적 시위입니다.',
    '경복궁역 3번 출구',
    '서울특별시 종로구 사직로 161',
    37.5759124,
    126.9731171,
    datetime('now', '+2 days', '10:00:00'),
    datetime('now', '+2 days', '16:00:00'),
    '환경',
    2,  -- 보통
    'active'
);

-- 3. 종로3가 집회 (낮은 심각도)
INSERT INTO events (
    title, description, location_name, location_address,
    latitude, longitude, start_date, end_date,
    category, severity_level, status
) VALUES (
    '소상공인 권익 보호 집회 [테스트]',
    '소상공인 지원 정책을 요구하는 소규모 집회입니다.',
    '종로3가역 광장',
    '서울특별시 종로구 종로 136',
    37.5710719,
    126.9910199,
    datetime('now', '+3 days', '15:00:00'),
    datetime('now', '+3 days', '17:00:00'),
    '경제',
    1,  -- 낮음
    'active'
);

-- 4. 청와대 앞 집회 (높은 심각도)
INSERT INTO events (
    title, description, location_name, location_address,
    latitude, longitude, start_date, end_date,
    category, severity_level, status
) VALUES (
    '정치개혁 촉구 대규모 집회 [테스트]',
    '전국 단위 대규모 집회가 예정되어 있습니다.',
    '청와대 사랑채 앞',
    '서울특별시 종로구 효자로 13-45',
    37.5833333,
    126.9752778,
    datetime('now', '+1 day', '13:00:00'),
    datetime('now', '+1 day', '19:00:00'),
    '정치',
    3,  -- 높음
    'active'
);

-- 5. 오늘 진행 중인 집회
INSERT INTO events (
    title, description, location_name, location_address,
    latitude, longitude, start_date, end_date,
    category, severity_level, status
) VALUES (
    '문화예술인 처우 개선 집회 [테스트]',
    '문화예술인의 권리 보호를 위한 집회입니다.',
    '인사동 쌈지길',
    '서울특별시 종로구 인사동길 44',
    37.5748889,
    126.9854444,
    datetime('now', '-2 hours'),
    datetime('now', '+3 hours'),
    '문화',
    2,  -- 보통
    'active'
);

-- 6. 시청광장 집회 (경로에서 약간 벗어남)
INSERT INTO events (
    title, description, location_name, location_address,
    latitude, longitude, start_date, end_date,
    category, severity_level, status
) VALUES (
    '청년 일자리 창출 촉구 집회 [테스트]',
    '청년 고용 문제 해결을 요구하는 집회입니다.',
    '서울시청 광장',
    '서울특별시 중구 세종대로 110',
    37.5663889,
    126.9779444,
    datetime('now', '+4 days', '11:00:00'),
    datetime('now', '+4 days', '15:00:00'),
    '청년',
    2,  -- 보통
    'active'
);

-- 7. 광화문역 바로 앞 (매우 근접)
INSERT INTO events (
    title, description, location_name, location_address,
    latitude, longitude, start_date, end_date,
    category, severity_level, status
) VALUES (
    '교육개혁 촉구 집회 [테스트]',
    '교육 정책 개선을 요구하는 집회입니다.',
    '광화문역 5번 출구',
    '서울특별시 종로구 세종대로 지하 172',
    37.5716453,
    126.9764274,
    datetime('now', '+5 days', '16:00:00'),
    datetime('now', '+5 days', '18:00:00'),
    '교육',
    1,  -- 낮음
    'active'
);

-- 8. 종료된 집회 (참고용)
INSERT INTO events (
    title, description, location_name, location_address,
    latitude, longitude, start_date, end_date,
    category, severity_level, status
) VALUES (
    '과거 집회 [테스트 - 종료됨]',
    '이미 종료된 과거 집회입니다.',
    '광화문광장',
    '서울특별시 종로구 세종대로 172',
    37.5720164,
    126.9769814,
    datetime('now', '-3 days', '14:00:00'),
    datetime('now', '-3 days', '18:00:00'),
    '기타',
    2,
    'ended'
);

-- 9. 취소된 집회 (참고용)
INSERT INTO events (
    title, description, location_name, location_address,
    latitude, longitude, start_date, end_date,
    category, severity_level, status
) VALUES (
    '취소된 집회 [테스트 - 취소됨]',
    '사전에 취소된 집회입니다.',
    '종각역 광장',
    '서울특별시 종로구 종로 69',
    37.5703911,
    126.9826654,
    datetime('now', '+7 days', '13:00:00'),
    datetime('now', '+7 days', '17:00:00'),
    '기타',
    1,
    'cancelled'
);

-- 10. 세종로공원 집회
INSERT INTO events (
    title, description, location_name, location_address,
    latitude, longitude, start_date, end_date,
    category, severity_level, status
) VALUES (
    '의료개혁 요구 집회 [테스트]',
    '의료 정책 개선을 요구하는 집회입니다.',
    '세종로공원',
    '서울특별시 종로구 세종대로 189',
    37.5735556,
    126.9769722,
    datetime('now', '+6 days', '12:00:00'),
    datetime('now', '+6 days', '16:00:00'),
    '의료',
    3,  -- 높음
    'active'
);

-- 삽입된 데이터 확인
SELECT
    id,
    title,
    location_name,
    start_date,
    severity_level,
    status
FROM events
WHERE title LIKE '%테스트%'
ORDER BY start_date;
