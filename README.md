# 종로구 집회 알리미

<div align="center">

[![Python](https://img.shields.io/badge/Python-3.13+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![KakaoTalk](https://img.shields.io/badge/KakaoTalk-FFCD00?style=flat-square&logo=kakaotalk&logoColor=black)](https://developers.kakao.com)
[![SQLite](https://img.shields.io/badge/SQLite-003B57?style=flat-square&logo=sqlite&logoColor=white)](https://sqlite.org)
[![Docker](https://img.shields.io/badge/Docker-2496ED?style=flat-square&logo=docker&logoColor=white)](https://docker.com)
[![Status](https://img.shields.io/badge/Status-ClosedBeta-orange?style=flat-square)]()

</div>

KT디지털인재장학생 지역사회 문제해결 프로젝트 - 종로구 집회 알리미 서비스의 개발 저장소입니다.



### 📰 KTx종로구청 2026년 협력사업 선정
> [**종로구, 시위·집회 알림톡 서비스 연내 상용화 추진** | 연합뉴스](https://www.yna.co.kr/view/AKR20260212070500004)  
> [**시위·집회 정보, 미리 알려준다” 종로구·KT 상용화 착수** | 종로구청](https://www.jongno.go.kr/mayor/bbs/selectBoardArticle.do?bbsId=BBSMSTR_000000001618&menuNo=388338&menuId=388338&nttId=250457)  
> 🔗 Link: [카카오톡 채널 추가하기](https://pf.kakao.com/_gmJNn)

<br />

## 목차
- [목차](#목차)
- [개요](#개요)
- [서비스 소개](#서비스-소개)
- [🧩 문제](#-문제)
- [💡 해결책](#-해결책)
- [서비스 기능](#서비스-기능)
- [ERD](#erd)
- [시스템 아키텍처](#system-architecture)

## 개요
종로구는 연간 수백 건의 시위·집회가 열리는 지역으로, 갑작스러운 도로 통제와 버스 노선 변경이 주민과 통행인의 불편으로 이어졌습니다. 이 서비스는 서울경찰청·서울교통정보센터 데이터를 자동 수집해, 사용자의 출퇴근 경로에 집회가 겹칠 경우 카카오톡으로 사전 알림을 보냅니다.

## 서비스 소개

### 🧩 문제

서울 종로구는 연간 수백 건의 시위·집회가 열리는 지역입니다.  
이로 인한 도로 통제, 버스 노선 변경, 교통 혼잡이 빈번하지만 사전에 알 방법이 없었습니다.

2024년 주민참여 리빙랩 조사에서 "집회로 인한 생활 불편 해소"가 핵심 민원으로 확인되었고,  
종로구가 KT와 협력해 기술적 해결책을 찾기로 했습니다.


### 💡 해결책

**별도 앱 설치 없이**, 카카오톡으로 집회 정보를 미리 받아보는 서비스입니다.

- 서울경찰청(SMPA) 집회 신고 데이터를 매일 자동 수집
- 사용자가 등록한 **이동경로**와 **관심 장소**의 집회 탐지
- 카카오톡 **개인 맞춤 알림** 발송


## 서비스 기능
| 기능 | 설명 |
|---|---|
| 📣 오늘의 집회 | 종로구 집회 정보 모음 |
| 📍 경로 기반 집회 감지 | 출발지·도착지 등록 → 경로상 위치하는 집회 탐지 |
| 🚌 버스 통제 안내 | TOPIS PDF 노선도를 시각적으로 분석해 우회 정보 안내 |
| 🔔 알림 On/Off | 채널을 차단하지 않고도 알람 수신 설정 |
| 📲 카카오톡 알림 | Kakao Event API 기반의 개인화 푸시 알림 |


## ERD
erd 사진

## 시스템 아키텍처
SA 사진


---
