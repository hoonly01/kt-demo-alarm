"""SMPA Kakao 지오코딩 후보 생성을 위한 버전관리 ruleset."""

from __future__ import annotations

GeocodeAbbreviationRule = tuple[str, str]

# 규칙 추가/수정은 이 ruleset만 변경하고, 대표 케이스를 테스트로 함께 고정한다.
SMPA_GEOCODE_ABBREVIATION_RULES: tuple[GeocodeAbbreviationRule, ...] = (
    (r"舊\)", "구)"),
    (
        r"(?P<station>.+?역)\s*(?P<exit>\d+)\s*出",
        r"\g<station> \g<exit>번 출구",
    ),
    (r"(?P<exit>\d+)\s*出", r"\g<exit>번 출구"),
    (r"(?P<place>.*[가-힣])PB$", r"\g<place>치안센터"),
    (r"(?P<place>.*[가-힣])R$", r"\g<place>교차로"),
)
