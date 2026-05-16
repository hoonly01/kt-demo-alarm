> KT디지털인재장학생 지역사회 문제해결 프로젝트 동료평가상 🏆

# 📣 종로구 집회 알리미
[![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![KakaoTalk](https://img.shields.io/badge/KakaoTalk-FFCD00?style=flat-square&logo=kakaotalk&logoColor=black)](https://developers.kakao.com)
[![SQLite](https://img.shields.io/badge/SQLite-003B57?style=flat-square&logo=sqlite&logoColor=white)](https://sqlite.org)
[![Docker](https://img.shields.io/badge/Docker-2496ED?style=flat-square&logo=docker&logoColor=white)](https://docker.com)
[![Status](https://img.shields.io/badge/Status-ClosedBeta-orange?style=flat-square)]()

KT디지털인재장학생 지역사회 문제해결 프로젝트 - 종로구 집회 알리미 서비스의 개발 저장소입니다.
> 🔗 Link: [카카오톡 채널 추가하기](https://pf.kakao.com/_gmJNn)


<br />

## 📰 KTx종로구청 2026년 협력사업 선정 프로젝트
> [**종로구, 시위·집회 알림톡 서비스 연내 상용화 추진** | 연합뉴스](https://www.yna.co.kr/view/AKR20260212070500004)  
> [**"시위·집회 정보, 미리 알려준다” 종로구·KT 상용화 착수** | 종로구청](https://www.jongno.go.kr/mayor/bbs/selectBoardArticle.do?bbsId=BBSMSTR_000000001618&menuNo=388338&menuId=388338&nttId=250457)  


<br />

## 📑 목차
- [📮 개요](#overview)
- [✨ 서비스 소개](#service-intro)  
    - [💡 해결책](#solution)
- [💻 서비스 기능](#features)
- [🛠️ 운영 백오피스](#admin-backoffice)
- [🗂 ERD](#erd)
- [🏛️ 시스템 아키텍처](#architecture)

<br />

<a id="overview"></a>
## 📮 개요
> 등록만 하시고, 까먹으세요! 저희가 먼저 알려드릴게요.  

서울경찰청과 서울시 교통정보 시스템의 데이터를 수집해 사용자가 사전 설정한 이동경로나 관심 장소에 집회로 인한 영향이 예상되면 카카오톡으로 알림을 보내 사전에 대비할 수 있도록 돕습니다.  

<br />

<a id="service-intro"></a>
## ✨ 서비스 소개
서울 종로구는 연간 수천 건의 시위·집회가 열리는 지역입니다.  
이로 인한 도로 통제, 버스 노선 변경, 교통 혼잡이 빈번하지만 이를 한눈에 확인할 수 있는 플랫폼이 없었습니다.

종로구의 2024년 주민참여 조사에서 "집회로 인한 생활 불편 해소"가 핵심 민원으로 확인되었고 종로구가 KT와 협력해 기술적 해결책을 찾기로 했습니다.

플랫폼마다 제공하는 정보가 달라 정확한 집회 정보를 얻으려면 여러 플랫폼을 직접 찾아봐야 하는 불편함이 있었습니다.  

결정적으로 대부분의 사용자는 집회·교통 통제 정보를 능동적으로 검색하지 않기 때문에, 사전에 정보를 전달받는 **푸시 방식**이 필요했습니다.  


<a id="solution"></a>
### 💡 해결책
**별도 앱 설치 없이**, 카카오톡으로 집회 정보를 받아보는 서비스입니다.
- 서울경찰청 집회 신고 데이터, 서울시 교통정보 시스템 정보 수집
- 사용자가 등록한 **이동경로**와 **관심 장소**의 집회 탐지
- 카카오톡 기반 **개인 맞춤형 알림** 발송

<br />

<a id="features"></a>
## 💻 서비스 기능
| 기능 | 설명 |
|---|---|
| 📣 오늘의 집회 | 종로구 집회 정보 모음 안내 |
| 🚗 경로 기반 집회 감지 | 출발지·도착지 등록으로 영향 받는 집회 탐지 |
| 📍 관심 장소 등록 | 종로구 주요 장소를 거점으로 집회 탐지 |
| 🚌 버스 통제 안내 | 교통정보 시스템 데이터를 기반으로 버스 우회 노선 안내 |
| 🔔 알림 On/Off | 채널을 차단하지 않고 서비스 알람 수신 여부 설정 |
| 📲 카카오톡 알림 | Kakao Event API 기반의 개인화 푸시 알림 |

<br />

<a id="admin-backoffice"></a>
## 🛠️ 운영 백오피스
관리자 화면은 `/admin/dashboard`의 기존 FastAPI/Jinja 렌더링 경로를 유지하면서 운영 판단에 필요한 신호를 한 화면에 모으는 방향으로 관리합니다.

| 운영 계약 | 내용 |
|---|---|
| 접근 경계 | 대시보드는 Basic Auth로 보호하고, 운영 POST 액션은 기존 관리자 인증·API key·Origin/Referer 검증 경계를 유지합니다. |
| 데이터 경계 | 기존 SQLite 테이블과 컬럼을 사용하며, 백오피스 표시를 위해 DB schema나 migration을 추가하지 않습니다. |
| 액션 경계 | `/admin/trigger-crawling`, `/admin/trigger-bus-notice`, `/admin/trigger-route-check`, `/admin/trigger-zone-check`, `/admin/trigger-test-alarm-for-user`만 운영 액션 카탈로그에 노출합니다. |
| 외부 호출 경계 | 대시보드 렌더링과 검증은 SMPA·TOPIS·Kakao·외부 asset 호출에 의존하지 않아야 합니다. |
| 개인정보 경계 | 사용자 식별자는 화면에서 축약 표시하고, DB 값은 Jinja 기본 escaping을 유지해 `\|safe`로 렌더링하지 않습니다. |

| 운영 섹션 | 표시 목적 |
|---|---|
| Overview | scheduler 상태, 수집 최신성, 알림 실패, 사용자 readiness, 버스 캐시 상태를 빠르게 판단합니다. |
| 데이터 수집 상태 | 집회 데이터의 source, 원문 URL, hash, 수집·갱신 시각, parser version을 확인합니다. |
| 알림 발송 운영 | `alarm_tasks`의 status, event_id, request_data, error_messages, 완료·갱신 시각으로 실패 원인을 추적합니다. |
| 사용자 readiness | active/alarm 상태, 경로 좌표 완성도, 관심구역, 버스, 언어, 최근 활동·경로 갱신 시각을 확인합니다. |
| 수동 운영 액션 | 기존 trigger endpoint의 위험도와 외부 호출 여부를 운영자가 클릭 전 확인합니다. |
| 이벤트/집회 탐색 | 기간, 장소, 참석자, 관할서, severity/status, 원문 링크, 수집 이력을 탐색합니다. |
| 버스 공지 운영 | `BusNoticeService`의 crawler 초기화 여부, cache count, last_update를 read-only로 표시합니다. |

| 검증 항목 | 명령 |
|---|---|
| 관리자 대시보드·legacy schema 회귀 | `env -u RUN_LIVE_SMPA uv run pytest tests/test_api_admin.py tests/test_admin_dashboard_schema_compat.py` |
| Playwright smoke | `env -u RUN_LIVE_SMPA uv run pytest tests/test_admin_dashboard_playwright.py` |
| 전체 회귀 | `env -u RUN_LIVE_SMPA uv run pytest` |
| Python 구문/type boundary | `PYTHONPYCACHEPREFIX="$(mktemp -d)" uv run python -m compileall -q app tests` |
| diff lint | `git diff --check` |

<br />

<a id="erd"></a>
## 🗂 ERD
<img width="2304" height="1750" alt="ERD2" src="https://github.com/user-attachments/assets/5fc428d1-3b0c-406f-adb5-99979d817a69" />


<br />

<a id="architecture"></a>
## 🏛️ 시스템 아키텍처
<img width="2967" height="1689" alt="demo-alarm" src="https://github.com/user-attachments/assets/8c9ea30e-cdf3-4ae9-bafa-b7de277e5db1" />

<br />
