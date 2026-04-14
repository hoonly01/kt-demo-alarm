import sys
import io
import logging

logger = logging.getLogger(__name__)

# 터미널 출력 한글 깨짐 방지 (UTF-8 강제 설정)
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
    except Exception:
        pass
import requests
import urllib3

import json
import time
import os
import re
import tempfile
import base64
try:
    import defusedxml.ElementTree as ET
except ImportError:
    import xml.etree.ElementTree as ET  # fallback: defusedxml 설치 권장
import pandas as pd
import shutil
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
import google.generativeai as genai
from app.config.settings import settings

try:
    import fitz  # PyMuPDF for PDF processing
    PDF_PROCESSING_AVAILABLE = True
except ImportError:
    PDF_PROCESSING_AVAILABLE = False
    print("PyMuPDF를 찾을 수 없습니다. PDF 이미지 추출 기능이 제한됩니다.")

try:
    from PIL import Image
    import matplotlib.pyplot as plt
    import matplotlib.image as mpimg
    IMAGE_DISPLAY_AVAILABLE = True
except ImportError:
    IMAGE_DISPLAY_AVAILABLE = False
    print("PIL 또는 matplotlib를 찾을 수 없습니다. 이미지 팝업 기능이 제한됩니다.")

# hwp 변환 모듈 임포트 (상대 경로로 수정)
try:
    from .hwpx2pdf import convert_hwpx_to_pdf_simple
    HWP_CONVERTER_AVAILABLE = True
except ImportError:
    try:
        from app.services.bus_logic.hwpx2pdf import convert_hwpx_to_pdf_simple
        HWP_CONVERTER_AVAILABLE = True
    except ImportError:
        HWP_CONVERTER_AVAILABLE = False
        print("HWP 변환 모듈을 찾을 수 없습니다. HWP/HWPX 파일은 원본 그대로 처리됩니다.")


class TOPISCrawler:
    def __init__(self, gemini_api_key=None, cache_file="topis_cache.json"):
        """TOPIS 크롤러 초기화"""
        self.base_url = "https://topis.seoul.go.kr"
        self.service_key = settings.SEOUL_BUS_API_KEY
        
        # 캐시 및 다운로드 폴더 경로 조정 (프로젝트 루트 기준)
        self.cache_file = cache_file
        self.download_folder = "topis_attachments"
        self.images_folder = os.path.join(self.download_folder, "route_images")
        
        # 폴더 생성
        os.makedirs(self.download_folder, exist_ok=True)
        os.makedirs(self.images_folder, exist_ok=True)
        
        self.cache_data = self._load_cache()
        
        # 세션 설정
        # 주의: TOPIS 사이트가 자체 서명 인증서를 사용하므로 SSL 검증을 비활성화합니다.
        # 네트워크 환경이 변경 시 verify=True로 전환을 검토하세요.
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'X-Requested-With': 'XMLHttpRequest',
            'Referer': 'https://topis.seoul.go.kr/notice/openNoticeList.do'
        })
        
        # Gemini 설정
        if not gemini_api_key:
            gemini_api_key = settings.GEMINI_API_KEY
            
        if not gemini_api_key:
            raise RuntimeError("Gemini API Key가 필요합니다. 환경변수 설정을 확인하세요.")
        
        genai.configure(api_key=gemini_api_key)
        self.gemini_model = genai.GenerativeModel("gemini-2.5-pro")

    def _parse_period(self, period_str):
        """기간 문자열을 datetime 객체로 파싱"""
        try:
            # 다양한 날짜 형식 정규화
            normalized = period_str.strip()
            
            # 2025-08-15 09:00~2025-08-15 18:00 형식
            if '~' in normalized:
                start_str, end_str = normalized.split('~', 1)
                start_str, end_str = start_str.strip(), end_str.strip()
                
                # 날짜 파싱
                for fmt in ['%Y-%m-%d %H:%M', '%Y-%m-%d', '%m-%d %H:%M', '%m-%d']:
                    try:
                        start_dt = datetime.strptime(start_str, fmt)
                        end_dt = datetime.strptime(end_str, fmt)
                        
                        # 연도가 없는 경우 현재 연도 사용
                        if start_dt.year == 1900:
                            start_dt = start_dt.replace(year=datetime.now().year)
                        if end_dt.year == 1900:
                            end_dt = end_dt.replace(year=datetime.now().year)
                        
                        return start_dt, end_dt
                    except ValueError:
                        continue
            
            return None, None
            
        except Exception:
            return None, None

    def _load_cache(self):
        """캐시 로드 및 오래된 데이터 정리"""
        if not os.path.exists(self.cache_file):
            return {"notices": {}}
        
        try:
            with open(self.cache_file, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)
            
            if not isinstance(cache_data, dict) or "notices" not in cache_data:
                return {"notices": {}}
            
            # 14일 이상 지난 데이터 정리 (30일로 연장)
            cutoff_date = datetime.now().date() - timedelta(days=30)
            notices_to_remove = []
            
            for seq, notice in cache_data["notices"].items():
                try:
                    # 통제 종료일 확인
                    should_remove = True
                    
                    # station_periods에서 확인
                    if notice.get('station_periods'):
                        for periods in notice['station_periods'].values():
                            for period in periods:
                                _, end_dt = self._parse_period(period)
                                if end_dt and end_dt.date() >= cutoff_date:
                                    should_remove = False
                                    break
                            if not should_remove:
                                break
                    
                    # general_periods에서 확인
                    if should_remove and notice.get('general_periods'):
                        for period in notice['general_periods']:
                            _, end_dt = self._parse_period(period)
                            if end_dt and end_dt.date() >= cutoff_date:
                                should_remove = False
                                break
                    
                    # 날짜 정보가 없으면 작성일 기준
                    if should_remove:
                        create_date_str = notice.get('create_date', '')
                        if create_date_str:
                            create_date = datetime.strptime(create_date_str.split(' ')[0], '%Y-%m-%d').date()
                            if create_date >= cutoff_date:
                                should_remove = False
                    
                    if should_remove:
                        notices_to_remove.append(seq)
                        
                except Exception as e:
                    print(f"캐시 정리 중 오류 (seq: {seq}): {e}")
            
            # 오래된 데이터 삭제
            for seq in notices_to_remove:
                del cache_data["notices"][seq]
            
            print(f"캐시 로드 완료: {len(cache_data['notices'])}개 게시물 ({len(notices_to_remove)}개 정리됨)")
            
            # 캐시 데이터 보강 (이름이 없는 정류소 확인)
            cache_updated = False
            if notices_to_remove:
                cache_updated = True
                
            print("캐시 데이터 검증 및 보강 중...")
            for seq, notice in cache_data["notices"].items():
                station_info = notice.get('station_info', {})
                if not station_info:
                    continue
                    
                notice_updated = False
                for station_id, info in station_info.items():
                    name = info.get('name', '')
                    if not name or name == "정보 없음" or name == "정보없음" or name == "정류소명 미기재":
                        if station_id and station_id.isdigit() and len(station_id) == 5:
                            # print(f"  게시물 {seq} - 정류소 '{station_id}' 이름 보강 시도...")
                            found_name = self.get_station_name_by_ars_id(station_id)
                            if found_name:
                                info['name'] = found_name
                                notice_updated = True
                                cache_updated = True
                                # print(f"  -> '{found_name}' 업데이트 완료")
                                
                if notice_updated:
                    # 변경된 정보 저장
                    notice['station_info'] = station_info
            
            if cache_updated:
                print("보강된 캐시 데이터 저장 중...")
                self._save_cache(cache_data)
            
            return cache_data
            
        except Exception as e:
            print(f"캐시 로드 실패: {e}")
            return {"notices": {}}

    def _save_cache(self, cache_data=None):
        """캐시 저장 (seq 내림차순 정렬)"""
        if cache_data is None:
            cache_data = self.cache_data
        
        try:
            # seq 기준 내림차순 정렬 (문자열을 정수로 변환하여 정렬)
            sorted_notices = dict(
                sorted(
                    cache_data["notices"].items(), 
                    key=lambda x: int(x[0]) if x[0].isdigit() else 0, 
                    reverse=True
                )
            )
            
            # 정렬된 데이터로 교체
            cache_data["notices"] = sorted_notices
            if hasattr(self, 'cache_data'):
                self.cache_data["notices"] = sorted_notices  # 메모리도 함께 업데이트
            
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)
            
            print(f"캐시 저장 완료: {len(sorted_notices)}개 게시물 (seq 내림차순 정렬됨)")
            
        except Exception as e:
            print(f"캐시 저장 실패: {e}")

    def _show_image_popup(self, image_path, route_number):
        """이미지를 팝업으로 표시"""
        if not IMAGE_DISPLAY_AVAILABLE:
            print(f"이미지 표시 라이브러리가 없습니다. 파일 경로: {image_path}")
            return
        
        if not os.path.exists(image_path):
            print(f"이미지 파일을 찾을 수 없습니다: {image_path}")
            return
        
        try:
            # matplotlib로 이미지 팝업 표시
            img = mpimg.imread(image_path)
            
            plt.figure(figsize=(12, 8))
            plt.imshow(img)
            plt.axis('off')  # 축 숨기기
            plt.title(f'Bus {route_number} Info (PDF page)', fontsize=14, pad=20)
            plt.tight_layout()
            
            # 팝업 창으로 표시
            plt.show()
            
        except Exception as e:
            print(f"이미지 표시 실패: {e}")
            print(f"이미지 파일 경로: {image_path}")

    def _clean_old_attachments(self):
        """첨부파일 폴더에서 30개 초과 파일 삭제 (가장 오래된 것부터)"""
        try:
            files = []
            for filename in os.listdir(self.download_folder):
                file_path = os.path.join(self.download_folder, filename)
                if os.path.isfile(file_path):  # 폴더 제외, 파일만
                    files.append((file_path, os.path.getctime(file_path)))
            
            if len(files) > 30:
                # 생성 시간 기준으로 정렬 (오래된 순)
                files.sort(key=lambda x: x[1])
                
                # 30개 초과하는 파일들 삭제
                files_to_delete = files[:-30]
                for file_path, _ in files_to_delete:
                    try:
                        os.remove(file_path)
                        print(f"오래된 파일 삭제: {os.path.basename(file_path)}")
                    except Exception as e:
                        print(f"파일 삭제 실패 {file_path}: {e}")
                
                print(f"총 {len(files_to_delete)}개 파일 정리 완료")
                
        except Exception as e:
            print(f"첨부파일 정리 중 오류: {e}")

    def _convert_pdf_page_to_image(self, pdf_path, page_num, route_number, notice_seq):
        """PDF의 특정 페이지를 이미지로 변환"""
        if not PDF_PROCESSING_AVAILABLE:
            return None
        
        try:
            doc = fitz.open(pdf_path)
            if page_num < 0 or page_num >= len(doc):
                doc.close()
                return None
            
            page = doc.load_page(page_num)
            pix = page.get_pixmap(dpi=200)  # 적당한 해상도
            
            # 이미지 파일명 생성
            safe_route = re.sub(r'[^\w]', '_', route_number)
            image_filename = f"route_{safe_route}_seq_{notice_seq}_page_{page_num + 1}.png"
            image_path = os.path.join(self.images_folder, image_filename)
            
            pix.save(image_path)
            doc.close()
            
            return image_path
            
        except Exception as e:
            print(f"PDF 페이지 이미지 변환 실패: {e}")
            return None

    def get_station_name_by_ars_id(self, ars_id):
        """ARS ID로 정류소명 조회"""
        if not ars_id or len(ars_id) != 5:
            return None
            
        try:
            url = 'http://ws.bus.go.kr/api/rest/stationinfo/getStationByUid'
            params = {'serviceKey': self.service_key, 'arsId': ars_id}
            
            response = requests.get(url, params=params, timeout=5, verify=False)
            if response.status_code == 200:
                try:
                    root = ET.fromstring(response.content.decode('utf-8'))
                except ET.ParseError:
                    root = ET.fromstring(response.content)
                
                st_nm = root.find('.//itemList/stNm')
                
                if st_nm is not None and st_nm.text:
                    return st_nm.text
        except Exception:
            return None
        return None

    def _get_station_coordinates(self, station_id, station_name=None):
        """정류소 좌표 조회 (ARS ID 또는 정류소명 사용)"""
        coordinates = None
        
        try:
            # 1단계: ARS ID로 좌표 조회 (gpsX, gpsY 사용)
            if station_id and station_id.isdigit() and len(station_id) == 5:
                url = 'http://ws.bus.go.kr/api/rest/stationinfo/getStationByUid'
                params = {'serviceKey': self.service_key, 'arsId': station_id}
                
                response = requests.get(url, params=params, timeout=5, verify=False)
                if response.status_code == 200:
                    try:
                        root = ET.fromstring(response.content.decode('utf-8'))
                    except ET.ParseError:
                        root = ET.fromstring(response.content)
                    
                    gps_x = root.find('.//itemList/gpsX')
                    gps_y = root.find('.//itemList/gpsY')
                    
                    if gps_x is not None and gps_y is not None and gps_x.text and gps_y.text:
                        coordinates = {
                            "gps_x": float(gps_x.text),
                            "gps_y": float(gps_y.text),
                            "coordinate_type": "gps"
                        }
                        print(f"  정류소 {station_id}: GPS 좌표 ({gps_x.text}, {gps_y.text}) 조회 성공")
                        return coordinates
            
            # 2단계: 정류소명으로 좌표 조회 (tmX, tmY 사용)
            if not coordinates and station_name:
                url = 'http://ws.bus.go.kr/api/rest/stationinfo/getStationByName'
                params = {'serviceKey': self.service_key, 'stSrch': station_name}
                
                response = requests.get(url, params=params, timeout=5, verify=False)
                if response.status_code == 200:
                    try:
                        root = ET.fromstring(response.content.decode('utf-8'))
                    except ET.ParseError:
                        root = ET.fromstring(response.content)
                    
                    # 첫 번째 매칭 결과 사용
                    tm_x = root.find('.//itemList/tmX')
                    tm_y = root.find('.//itemList/tmY')
                    
                    if tm_x is not None and tm_y is not None and tm_x.text and tm_y.text:
                        coordinates = {
                            "tm_x": float(tm_x.text),
                            "tm_y": float(tm_y.text),
                            "coordinate_type": "tm"
                        }
                        print(f"  정류소 '{station_name}': TM 좌표 ({tm_x.text}, {tm_y.text}) 조회 성공")
                        return coordinates
        
        except Exception as e:
            print(f"  정류소 좌표 조회 실패 (ID: {station_id}, 이름: {station_name}): {e}")
        
        return None

    def _get_bus_notices(self, page=1, per_page=5, max_retries=3):
        """버스 공지사항 목록 가져오기 (재시도 로직 포함)"""
        data = {
            'pageIndex': str(page),
            'recordPerPage': str(per_page),
            'pageSize': '5',
            'bdwrSeq': '',
            'blbdDivCd': '02',
            'bdwrDivCd': '0202',
            'tabGubun': 'B'
        }
        
        for attempt in range(max_retries):
            try:
                response = self.session.post(f"{self.base_url}/notice/selectNoticeList.do", data=data, verify=False)
                response.raise_for_status()
                return response.json()
            except Exception as e:
                print(f"목록 가져오기 오류 (시도 {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 2
                    print(f"{wait_time}초 후 재시도...")
                    time.sleep(wait_time)
                else:
                    print("최대 재시도 횟수 초과")
        
        return None

    def _get_notice_detail(self, blbd_div_cd, bdwr_seq, max_retries=3):
        """공지사항 상세 내용 가져오기 (재시도 로직 포함)"""
        data = {'blbdDivCd': blbd_div_cd, 'bdwrSeq': bdwr_seq}
        
        for attempt in range(max_retries):
            try:
                response = self.session.post(f"{self.base_url}/notice/selectNotice.do", data=data, verify=False)
                response.raise_for_status()
                result = response.json()
                
                if 'rows' in result and result['rows']:
                    record = result['rows'][0]
                    soup = BeautifulSoup(record.get('bdwrCts', ''), 'html.parser')
                    content = soup.get_text(separator='\n', strip=True)
                    
                    attachments = []
                    if record.get('apndFileNm'):
                        attachments.append({
                            'name': record['apndFileNm'],
                            'bdwr_seq': bdwr_seq,
                            'blbd_div_cd': blbd_div_cd
                        })
                    
                    return {
                        'content': content or "내용 없음",
                        'attachments': attachments
                    }
                
                return None
                
            except Exception as e:
                print(f"상세 내용 가져오기 오류 (seq: {bdwr_seq}, 시도 {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 2
                    print(f"{wait_time}초 후 재시도...")
                    time.sleep(wait_time)
                else:
                    print("최대 재시도 횟수 초과")
        
        return None

    def _download_attachment(self, attachment, save_to_folder=True, max_retries=3):
        """첨부파일 다운로드 (재시도 로직 포함)"""
        for attempt in range(max_retries):
            try:
                url = f"{self.base_url}/notice/selectNoticeFileDown.do"
                data = {"bdwrSeq": attachment['bdwr_seq']}
                
                response = self.session.post(url, data=data, verify=False)
                response.raise_for_status()
                
                # JSON 응답인 경우 (Base64 인코딩된 파일)
                file_bytes = None
                safe_filename = re.sub(r'[^\w가-힣\.-]', '_', attachment['name'])
                
                try:
                    result = response.json()
                    if 'rows' in result and result['rows']:
                        record = result['rows'][0]
                        file_b64 = record.get('apndFile')
                        if file_b64:
                            file_bytes = base64.b64decode(file_b64)
                except Exception:
                    # JSON 응답이 아닌 경우(예: 바이너리 응답)는 무시하고 아래에서 바이너리로 처리
                    pass
                
                # 바이너리 응답인 경우
                if file_bytes is None:
                    file_bytes = response.content
                
                if save_to_folder:
                    file_path = os.path.join(self.download_folder, safe_filename)
                else:
                    temp_dir = tempfile.mkdtemp(prefix=f"topis_{attachment['bdwr_seq']}_")
                    file_path = os.path.join(temp_dir, safe_filename)
                
                with open(file_path, 'wb') as f:
                    f.write(file_bytes)
                
                return file_path
                
            except Exception as e:
                print(f"첨부파일 다운로드 오류 ({attachment['name']}, 시도 {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 2
                    print(f"{wait_time}초 후 재시도...")
                    time.sleep(wait_time)
                else:
                    print("최대 재시도 횟수 초과")
        
        return None

    def _convert_hwp_to_pdf(self, file_path):
        """HWP/HWPX 파일을 PDF로 변환"""
        if not HWP_CONVERTER_AVAILABLE:
            return file_path
        
        file_ext = os.path.splitext(file_path)[1].lower()
        if file_ext not in ['.hwp', '.hwpx']:
            return file_path
        
        try:
            # 파일이 있는 폴더에서 변환 실행
            folder_path = os.path.dirname(file_path)
            
            # 임시로 파일 하나만 변환하기 위해 별도 함수 필요
            # 여기서는 간단히 변환 시도
            from .hwpx2pdf import convert_hwpx_to_pdf_simple
            convert_hwpx_to_pdf_simple(folder_path)
            
            # PDF 파일 경로 생성
            pdf_path = os.path.splitext(file_path)[0] + '.pdf'
            
            if os.path.exists(pdf_path):
                print(f"HWP 파일 변환 완료: {os.path.basename(pdf_path)}")
                return pdf_path
            else:
                print(f"HWP 파일 변환 실패: {os.path.basename(file_path)}")
                return file_path
                
        except Exception as e:
            print(f"HWP 변환 중 오류: {e}")
            return file_path

    def _enrich_station_info(self, station_info):
        """정류장 정보 보강 (좌표 및 이름 검색)"""
        enriched = station_info.copy()
        for station_id, info in enriched.items():
            # 이름이 불명확한 경우 검색
            if not info.get('name') or info['name'] in ["정보없음", "정보 없음", "정류소명 미기재"]:
                if station_id and station_id.isdigit() and len(station_id) == 5:
                    found_name = self.get_station_name_by_ars_id(station_id)
                    if found_name:
                        info['name'] = found_name
            
            # 좌표 정보 추가 (아직 없으면)
            if 'coordinates' not in info:
                coords = self._get_station_coordinates(station_id, info.get('name'))
                if coords:
                    info['coordinates'] = coords
        return enriched

    def _extract_with_gemini(self, content, attachments, notice_seq, save_attachments=False, max_retries=5):
        """Gemini를 사용한 정보 추출 (재시도 로직 포함)"""
        prompt = f"""서울시 버스 운행 변경 공지사항을 분석하여 다음 정보를 JSON 형식으로 추출하세요.

본문과 첨부파일에서 다음 정보를 모두 찾아주세요:

1. **통제 정류소**: 정류소 이름과 ARS ID (5자리 번호) 이름 중에는 **창덕궁.우리소리박물관**처럼 이름에 .이 들어간 이름도 있으니 유의하세요.
2. **공통 통제 기간(general_periods)**: 공지사항 상단이나 본문에 명시된 **행사 전체 통제 일시**를 반드시 찾으세요. (예: 26.4.5 06:00~11:30 -> 2026-04-05 06:00~2026-04-05 11:30)
3. **통제 기간 표준화**: 모든 날짜와 시간은 YYYY-MM-DD HH:MM ~ YYYY-MM-DD HH:MM 형식으로 표준화하세요. 단, 연도가 두 자리(예: '26', '27')로 표기된 경우 현재 시스템 연도에 맞춰 반드시 '20XX' 형식으로 변환하세요.
4. **대상 노선**: 영향받는 버스 노선 번호들 (반드시 **파일 전체**에서 언급된 모든 노선 번호를 찾으세요)
5. **통제 유형**: '우회', '폐쇄', '미정차', '단축운행' 등
6. **우회 경로**: 노선별 변경된 경로 정보 (반드시 모든 노선의 우회 경로를 찾으세요)
7. **페이지 정보**: 첨부파일에서 각 노선 정보를 찾은 페이지 번호 (1부터 시작, 매우 중요)
8. **통제 범위**: 각 정류소에서 "특정 노선만 통제" 또는 "전체 통제" 여부

통제 범위 판단 기준:
- 문서에서 "○○번 버스만", "특정 노선", "일부 노선"과 같은 표현이 있으면 "특정노선"
- "모든 버스", "전체 노선", "해당 정류소"와 같은 표현이 있으면 "전체통제"
- 명시적인 표현이 없고 여러 노선이 나열되어 있으면 "특정노선"
- 불분명한 경우 "전체통제"로 간주

날짜 표준화 규칙:
- '8.15', '8월 15일' → '{datetime.now().year}-08-15' (현재년도 기준)
- 시간 없으면 시작: 00:00, 종료: 23:59
- 종료일 없으면 시작일과 동일

통제 정류장명을 찾을 수 없으면 "정보없음"으로 기재하도록.

JSON 형식:
{{
  "control_type": "우회",
  "general_periods": ["{datetime.now().year}-08-15 09:00~{datetime.now().year}-08-15 18:00"],
  "station_info": {{
    "01126": {{
      "name": "서울역버스환승센터",
      "periods": ["{datetime.now().year}-08-10 00:00~{datetime.now().year}-08-16 18:00"],
      "affected_routes": ["7016", "262", "9401"],
      "control_scope": "특정노선"
    }},
    "01234": {{
      "name": "시청앞",
      "periods": ["{datetime.now().year}-08-15 09:00~{datetime.now().year}-08-15 18:00"],
      "affected_routes": [],
      "control_scope": "전체통제"
    }}
  }},
  "detour_routes": {{
    "7016": "서울역 → 시청앞 → 을지로입구",
    "262": "종로2가 → 안국역 → 경복궁"
  }},
  "route_pages": {{
    "7016": 1,
    "262": 2,
    "9401": 1
  }}
}}

본문:
{content}"""

        # 웍스 AI 사용 모드 (content 인자 추가)
        if self.works_ai_api_key:
            return self._extract_with_works_ai(prompt, attachments, notice_seq, content=content, save_attachments=save_attachments, max_retries=max_retries)
        
        # 기존 Gemini 사용 모드 (Fallback)
        return self._extract_with_gemini_native(prompt, attachments, notice_seq, save_attachments, max_retries)

    def _extract_with_works_ai(self, prompt, attachments, notice_seq, content=None, save_attachments=False, max_retries=3):
        """Works AI (BizRouter)를 사용한 정보 추출 (대용량 PDF 분할 분석 적용)"""
        images_b64_all = []
        pages_text_all = []
        temp_files = []
        downloaded_files = []
        
        try:
            # 0. 본문(content)에서 기본 정보(통제 기간 등) 먼저 추출 (PDF 분석 전 보강)
            pre_info = {"general_periods": [], "control_type": "우회/통제"}
            try:
                if content and len(str(content).strip()) > 10:
                    text_only_prompt = f"""다음 서울시 버스 통제 공지 본문에서 '전체 통제 기간'을 추출하세요.
1. 날짜 표준화: YYYY-MM-DD HH:MM ~ YYYY-MM-DD HH:MM
2. 연도가 '26'처럼 짧으면 '2026'으로 변환
3. 오직 JSON {{"general_periods": ["..."], "control_type": "..."}} 형식으로만 답하세요.

[본문]
{content}"""
                    # 공통 메서드로 본문 즉시 분석
                    pre_data = self._call_works_ai_api(text_only_prompt, max_retries=max_retries)
                    if pre_data and pre_data.get("general_periods"):
                        pre_info["general_periods"] = pre_data["general_periods"]
                        print(f"  - 본문에서 통제 기간 사전 추출 성공: {pre_info['general_periods']}", flush=True)
            except Exception as e:
                logger.warning(f"본문 사전 분석 중 오류(건너뜀): {e}")

            # 1. 첨부파일 전수 스캔 및 데이터 준비
            if attachments:
                for attachment in attachments:
                    file_path = self._download_attachment(attachment, save_to_folder=save_attachments)
                    if file_path:
                        downloaded_files.append(file_path)
                        converted_path = self._convert_hwp_to_pdf(file_path)
                        ext = os.path.splitext(converted_path)[1].lower()
                        
                        if ext == '.pdf':
                            # 이미지와 페이지별 텍스트를 함께 추출
                            imgs, txts = self._pdf_to_base64_images(converted_path)
                            images_b64_all.extend(imgs)
                            pages_text_all.extend(txts)
                        elif ext in ['.png', '.jpg', '.jpeg', '.webp']:
                            # 단일 이미지는 텍스트 없음으로 처리
                            with open(converted_path, "rb") as imm:
                                images_b64_all.append(base64.b64encode(imm.read()).decode('utf-8'))
                                pages_text_all.append("")
                        
                        if not save_attachments:
                            temp_files.append(file_path)
                            if converted_path != file_path:
                                temp_files.append(converted_path)

            # 2. 분할 분석 (Chunking) 실행
            # AI가 한 번에 처리할 이미지 수
            chunk_size = 10
            total_images = len(images_b64_all)
            final_data = {
                "control_type": "우회",
                "general_periods": pre_info["general_periods"],
                "station_info": {},
                "detour_routes": {},
                "route_pages": {}
            }
            
            # 이미지가 없거나 적은 경우와 많은 경우를 나눠서 처리
            chunks = []
            text_chunks = []
            if total_images == 0:
                chunks = [[]]
                text_chunks = [[""]]
            else:
                for i in range(0, total_images, chunk_size):
                    chunks.append(images_b64_all[i:i + chunk_size])
                    text_chunks.append(pages_text_all[i:i + chunk_size])
            
            print(f"  - 총 {total_images}개의 페이지를 {len(chunks)}개의 청크로 나누어 정밀 분석(이미지+텍스트 하이브리드)합니다.")

            for idx, chunk_images in enumerate(chunks):
                start_page = idx * chunk_size + 1
                end_page = min((idx + 1) * chunk_size, total_images) if total_images > 0 else 0
                
                # 하이브리드 분석 프롬프트
                chunk_prompt = f"""당신은 제공된 이미지와 시스템 텍스트 레이어를 1:1로 대조하며 서울시 버스 우회 정보를 추출하는 전문가입니다.
추출 규격은 다음과 같습니다:
{prompt}
"""
                
                # 메시지 구성
                content_parts = [{"type": "text", "text": chunk_prompt}]
                for p_idx, (p_txt, p_img) in enumerate(zip(text_chunks[idx], chunk_images)):
                    abs_page = start_page + p_idx
                    content_parts.append({
                        "type": "text", 
                        "text": f"\n\n### [전체 문서 기준 {abs_page}페이지] ###\n*텍스트 레이어 정보:\n{p_txt}"
                    })
                    content_parts.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{p_img}"}
                    })
                
                # API 호출
                print(f"    - 청크 {idx+1}/{len(chunks)} 분석 중...", flush=True)
                chunk_data = self._call_works_ai_api(content_parts, is_multimodal=True, max_retries=max_retries)
                
                if not chunk_data:
                    print(f"    ⚠️ 청크 {idx+1} 분석 실패 (결과 없음)")
                    continue
                        
                # 데이터 병합
                if idx == 0:
                    final_data["control_type"] = chunk_data.get("control_type", final_data["control_type"])
                
                new_periods = chunk_data.get("general_periods", [])
                if isinstance(new_periods, list):
                    for p in new_periods:
                        if p and p not in final_data["general_periods"]:
                            final_data["general_periods"].append(p)
                    
                if "station_info" in chunk_data:
                    final_data["station_info"].update(chunk_data["station_info"])
                if "detour_routes" in chunk_data:
                    final_data["detour_routes"].update(chunk_data["detour_routes"])
                if "route_pages" in chunk_data:
                    final_data["route_pages"].update(chunk_data["route_pages"])

            # 최종 데이터 정규화 및 보강
            enriched_station_info = self._enrich_station_info(final_data["station_info"])
            
            station_periods = {}
            for sid, info in enriched_station_info.items():
                if info.get('periods'):
                    station_periods[sid] = info['periods']

            # 이미지 생성 로직
            route_images = {}
            if save_attachments and downloaded_files:
                for route_number, page_num in final_data["route_pages"].items():
                    for file_path in downloaded_files:
                        if file_path.lower().endswith('.pdf'):
                            image_path = self._convert_pdf_page_to_image(
                                file_path, page_num - 1, route_number, notice_seq
                            )
                            if image_path:
                                route_images[route_number] = image_path
                            break
            
            return {
                "seq": notice_seq,
                "control_type": final_data["control_type"],
                "general_periods": final_data["general_periods"],
                "station_periods": station_periods,
                "station_info": enriched_station_info,
                "detour_routes": final_data["detour_routes"],
                "route_pages": final_data["route_pages"],
                "route_images": route_images
            }

        except Exception as e:
            print(f"Works AI 분석 중 치명적 오류: {e}")
            return self._get_default_extraction_result()
        finally:
            if not save_attachments:
                for temp_file in temp_files:
                    try:
                        if os.path.exists(temp_file):
                            os.remove(temp_file)
                        temp_dir = os.path.dirname(temp_file)
                        if temp_dir != self.download_folder and os.path.exists(temp_dir):
                            shutil.rmtree(temp_dir, ignore_errors=True)
                    except Exception:
                        pass

    def _call_works_ai_api(self, content, is_multimodal=False, max_retries=3):
        """Works AI API 호출 공통 메서드"""
        headers = {
            "Authorization": f"Bearer {self.works_ai_api_key}",
            "Content-Type": "application/json"
        }
        
        messages = [{"role": "user", "content": [{"type": "text", "text": str(content)}]}] if not is_multimodal else [{"role": "user", "content": content}]
        payload = {
            "model": self.works_ai_model,
            "messages": messages,
            "response_format": {"type": "json_object"},
            "temperature": 0.0,
            "thinking_level": "medium",
            "include_thoughts": False
        }

        for attempt in range(max_retries):
            try:
                response = requests.post(f"{self.works_ai_base_url}/chat/completions", headers=headers, json=payload, timeout=300)
                response.raise_for_status()
                result = response.json()
                content_str = result['choices'][0]['message']['content']
                data = json.loads(self._clean_json_response(content_str))
                return data if isinstance(data, dict) else (data[0] if isinstance(data, list) and data else {})
            except Exception as e:
                if attempt < max_retries - 1:
                    time.sleep(2)
                else:
                    logger.error(f"Works AI API 최종 호출 실패: {e}")
        return None

    def _clean_json_response(self, text):
        """JSON 응답 마크다운 제거"""
        if not text: return "{}"
        text = re.sub(r'```json\s*', '', text)
        text = re.sub(r'```\s*', '', text).strip()
        return text

    def _get_default_extraction_result(self):
        """기본 추출 결과 반환"""
        return {
            'control_type': '통제',
            'general_periods': [],
            'station_periods': {},
            'station_info': {},
            'detour_routes': {},
            'route_pages': {},
            'route_images': {}
        }

    def _extract_with_gemini_native(self, prompt, attachments, notice_seq, save_attachments=False, max_retries=5):
        """Gemini Native API Fallback용"""
        gemini_files = []
        temp_files = []
        downloaded_files = []
        
        try:
            # 첨부파일 처리
            if attachments:
                for attachment in attachments:
                    file_path = self._download_attachment(attachment, save_to_folder=save_attachments)
                    if file_path:
                        downloaded_files.append(file_path)
                        
                        # HWP/HWPX 파일이면 PDF로 변환
                        converted_path = self._convert_hwp_to_pdf(file_path)
                        
                        # Gemini가 지원하는 파일 형식인지 확인
                        ext = os.path.splitext(converted_path)[1].lower()
                        supported_exts = ['.pdf', '.png', '.jpg', '.jpeg', '.webp']
                        
                        if ext in supported_exts:
                            gemini_file = genai.upload_file(path=converted_path, display_name=attachment['name'])
                            gemini_files.append(gemini_file)
                        else:
                            print(f"  Gemini 미지원 파일 제외: {os.path.basename(converted_path)}")
                        
                        # 임시 파일 기록 (save_attachments=False인 경우만)
                        if not save_attachments:
                            temp_files.append(file_path)
                            if converted_path != file_path:
                                temp_files.append(converted_path)
            
            # Gemini API 호출 (재시도 로직)
            request_content = gemini_files + [prompt] if gemini_files else [prompt]
            
            for attempt in range(max_retries):
                try:
                    print(f"  Gemini API 호출 중... (시도 {attempt + 1}/{max_retries})")
                    response = self.gemini_model.generate_content(request_content)
                    
                    # response.text 접근 전에 응답 상태 확인
                    if hasattr(response, 'candidates') and response.candidates:
                        candidate = response.candidates[0]
                        if hasattr(candidate, 'finish_reason') and candidate.finish_reason != 1:
                            print(f"  Gemini 응답 오류: finish_reason={candidate.finish_reason}")
                            if attempt < max_retries - 1:
                                wait_time = (attempt + 1) * 2
                                print(f"  {wait_time}초 후 재시도...")
                                time.sleep(wait_time)
                                continue
                            else:
                                break
                    
                    # JSON 추출
                    response_text = response.text if hasattr(response, 'text') else ""
                    if not response_text:
                        print(f"  Gemini 응답이 비어있음")
                        if attempt < max_retries - 1:
                            wait_time = (attempt + 1) * 2
                            print(f"  {wait_time}초 후 재시도...")
                            time.sleep(wait_time)
                            continue
                        else:
                            break
                    
                    json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
                    if json_match:
                        data = json.loads(json_match.group())
                        
                        # 데이터 정규화
                        station_info = data.get('station_info', {})
                        
                        # 정류장 정보 보강 (통제 범위에 따라 조건부 실행)
                        print(f"  정류장 정보 보강 중...")
                        enriched_station_info = self._enrich_station_info(station_info)
                        
                        # station_periods 재구성
                        station_periods = {}
                        for station_id, info in enriched_station_info.items():
                            if info.get('periods'):
                                station_periods[station_id] = info['periods']
                        
                        # 노선별 페이지 이미지 생성 (첨부파일이 저장된 경우만)
                        route_images = {}
                        if save_attachments and downloaded_files:
                            route_pages = data.get('route_pages', {})
                            for route_number, page_num in route_pages.items():
                                for file_path in downloaded_files:
                                    if file_path.lower().endswith('.pdf'):
                                        image_path = self._convert_pdf_page_to_image(
                                            file_path, page_num - 1, route_number, notice_seq
                                        )
                                        if image_path:
                                            route_images[route_number] = image_path
                                        break
                        
                        print(f"  Gemini 추출 성공 (시도 {attempt + 1})")
                        return {
                            'control_type': data.get('control_type', '통제'),
                            'general_periods': data.get('general_periods', []),
                            'station_periods': station_periods,
                            'station_info': enriched_station_info,  # 보강된 정보 사용
                            'detour_routes': data.get('detour_routes', {}),
                            'route_pages': data.get('route_pages', {}),
                            'route_images': route_images
                        }
                    else:
                        print(f"  Gemini 응답에서 JSON을 찾을 수 없음")
                        if attempt < max_retries - 1:
                            wait_time = (attempt + 1) * 2
                            print(f"  {wait_time}초 후 재시도...")
                            time.sleep(wait_time)
                            continue
                
                except Exception as e:
                    print(f"  Gemini API 오류 (시도 {attempt + 1}): {e}")
                    if attempt < max_retries - 1:
                        wait_time = (attempt + 1) * 2
                        print(f"  {wait_time}초 후 재시도...")
                        time.sleep(wait_time)
                    else:
                        print(f"  최대 재시도 횟수 초과. 기본값 반환.")
                        break
            
        except Exception as e:
            print(f"Gemini 추출 실패 (seq: {notice_seq}): {e}")
        
        finally:
            # Gemini 파일 정리
            for gemini_file in gemini_files:
                try:
                    genai.delete_file(gemini_file.name)
                except Exception:
                    pass
            
            # 임시 파일 정리 (save_attachments=False인 경우만)
            if not save_attachments:
                for temp_file in temp_files:
                    try:
                        if os.path.exists(temp_file):
                            os.remove(temp_file)
                        # 임시 폴더도 삭제
                        temp_dir = os.path.dirname(temp_file)
                        if temp_dir != self.download_folder and os.path.exists(temp_dir):
                            shutil.rmtree(temp_dir, ignore_errors=True)
                    except Exception:
                        pass
        
        # 기본값 반환
        return {
            'control_type': '통제',
            'general_periods': [],
            'station_periods': {},
            'station_info': {},
            'detour_routes': {},
            'route_pages': {},
            'route_images': {}
        }

    def crawl_notices(self):
        """공지사항 크롤링 (최신 5개만, 캐시는 전체 로드)"""
        print("TOPIS 버스 공지사항 크롤링 시작...")
        
        new_count = 0
        cache_hit = False
        
        # 최신 5개 게시물만 크롤링
        notice_list = self._get_bus_notices(page=1, per_page=5)
        if not notice_list or 'rows' not in notice_list or not notice_list['rows']:
            print("새로운 게시물이 없습니다.")
        else:
            for notice in notice_list['rows']:
                seq = notice['bdwrSeq']
                
                # 캐시 확인
                if hasattr(self, 'cache_data') and str(seq) in self.cache_data["notices"]:
                    print(f"  게시물 {seq}: 캐시에서 로드")
                    cache_hit = True
                    continue
                
                print(f"  게시물 {seq}: 새로 처리 중...")
                
                # 기본 정보
                notice_data = {
                    'seq': seq,
                    'title': notice['bdwrTtlNm'],
                    'create_date': notice['createDate'],
                    'view_count': notice['iqurNcnt'],
                    'category': '버스안내'
                }
                
                # 상세 내용 가져오기
                detail = self._get_notice_detail(notice['blbdDivCd'], seq)
                if detail:
                    notice_data.update(detail)
                    
                    # Gemini로 정보 추출 (첨부파일은 임시로만 처리)
                    extracted = self._extract_with_gemini(
                        detail['content'], 
                        detail['attachments'], 
                        seq,
                        save_attachments=False  # 크롤링 시에는 저장하지 않음
                    )
                    notice_data.update(extracted)
                
                # 캐시에 저장
                if hasattr(self, 'cache_data'):
                    self.cache_data["notices"][str(seq)] = notice_data
                new_count += 1
                
                time.sleep(1)  # API 제한 고려
        
        # 변경사항 저장
        if new_count > 0:
            self._save_cache()
            
        print(f"크롤링 완료 (신규 {new_count}건, 캐시 히트 {cache_hit})")
        return self.cache_data["notices"], cache_hit

    def filter_by_date(self, notices, date_str=None):
        """특정 날짜에 유효한 공지사항 필터링"""
        # notices가 dict인지 list인지 확인
        if isinstance(notices, list):
            # 리스트면 딕셔너리로 변환 시도 (또는 그대로 사용)
            # 여기서는 편의상 리스트를 순회
            notice_list = notices
        else:
            notice_list = list(notices.values())
            
        if not date_str:
            return notice_list
            
        filtered = []
        target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        
        for notice in notice_list:
            is_valid = False
            
            # 1. station_periods 확인
            if 'station_periods' in notice:
                for periods in notice['station_periods'].values():
                    for period in periods:
                        start_dt, end_dt = self._parse_period(period)
                        if start_dt and end_dt:
                            if start_dt.date() <= target_date <= end_dt.date():
                                is_valid = True
                                break
                    if is_valid:
                        break
            
            # 2. general_periods 확인
            if not is_valid and 'general_periods' in notice:
                for period in notice['general_periods']:
                    start_dt, end_dt = self._parse_period(period)
                    if start_dt and end_dt:
                        if start_dt.date() <= target_date <= end_dt.date():
                            is_valid = True
                            break
            
            # 3. 작성일 기준 (기간 정보가 없는 경우 당일 유효)
            if not is_valid:
                create_date_str = notice.get('create_date', '')
                if create_date_str:
                    create_date = datetime.strptime(create_date_str.split(' ')[0], '%Y-%m-%d').date()
                    if create_date == target_date:
                        is_valid = True
            
            if is_valid:
                filtered.append(notice)
                
        return filtered

    def get_control_info_by_route(self, notices, date_str, route_number):
        """특정 날짜, 특정 노선의 통제 정보 조회"""
        target_notices = self.filter_by_date(notices, date_str)
        results = []
        
        normalized_route = route_number.replace("-", "").strip()
        
        for notice in target_notices:
            # 해당 노선이 포함된 페이지 정보 확인
            route_pages = notice.get('route_pages', {})
            
            # 해당 노선이 포함된 정류소 정보 확인
            station_info = notice.get('station_info', {})
            affected_stations = []
            
            for station_id, info in station_info.items():
                if normalized_route in info.get('affected_routes', []):
                    affected_stations.append({
                        "station_name": info.get('name'),
                        "station_id": station_id,
                        "control_scope": info.get('control_scope'),
                        "periods": info.get('periods', [])
                    })
            
            if normalized_route in route_pages or affected_stations:
                results.append({
                    "notice_seq": notice.get('seq'),
                    "notice_title": notice.get('title'),
                    "control_type": notice.get('control_type'),
                    "affected_stations": affected_stations,
                    "detour_route": notice.get('detour_routes', {}).get(normalized_route),
                    "page_num": route_pages.get(normalized_route),
                    "image_url": notice.get('route_images', {}).get(normalized_route)
                })
                
        return results
