import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from geopy.geocoders import Nominatim
# (★★★ 수정됨 ★★★) RateLimiter를 직접 임포트하지 않고 geocode 함수를 감싸는 방식으로 변경
from geopy.extra.rate_limiter import RateLimiter as GeopyRateLimiter  # 예전 방식을 시도해보고

try:
    from geopy.adapters import RateLimiter  # 최신 방식을 시도
except ImportError:
    RateLimiter = GeopyRateLimiter  # 예전 방식 사용 (하위 호환성)

import openai
from openai import OpenAI
import fitz  # PyMuPDF
import os
import re
from pathlib import Path
import requests
import json
import time

# --- 1. 초기 설정 (Serper 키 추가) ---

st.set_page_config(layout="wide")
st.title("🗺️ 라틴아메리카 뉴스 기사 지도 (PDF 기반)")

# API 키 불러오기
try:
    openai_api_key = st.secrets["OPENAI_API_KEY"]
except:
    # 📌 여기에 실제 OpenAI 키를 입력하세요 (배포 시에는 secrets 사용)
    openai_api_key = "YOUR OPENAI_API_KEY" # 실제 키로 교체 필요

try:
    serper_api_key = st.secrets["SERPER_API_KEY"]
except:
    # 📌 여기에 실제 Serper 키를 입력하세요 (배포 시에는 secrets 사용)
    serper_api_key = "YOUR SERPER API KEY" # 실제 키로 교체 필요

# OpenAI 클라이언트 설정
if openai_api_key == "YOUR_OPENAI_API_KEY" or not openai_api_key:
    st.warning("OpenAI API 키가 설정되지 않았습니다. '더 알아보기' 및 '좌표 검색' 기능이 작동하지 않습니다.")
    client = None
else:
    try:
        client = OpenAI(api_key=openai_api_key)
    except Exception as e:
        st.error(f"OpenAI 클라이언트 초기화 실패: {e}")
        client = None

# Serper 키 확인
if serper_api_key == "YOUR_SERPER_API_KEY" or not serper_api_key:
    st.warning("Serper (Google 검색) API 키가 설정되지 않았습니다. '더 알아보기' 기능이 작동하지 않습니다.")

# --- 2. 수동 위치 캐시 (이전과 동일) ---
MANUAL_LOCATION_CACHE = {
    "페루, 리마, Plaza San Martín": (-12.0505, -77.0339),
    "페루, 리마": (-12.0464, -77.0428),
    "페루, 리마, Comas": (-11.9333, -77.0500),
    "페루, 리마 & Callao": (-12.0464, -77.0428),
    "볼리비아, 라파스": (-16.4897, -68.1193),
    "미국, 콜로라도, Aurora": (39.7294, -104.8319),
    "아르헨티나": (-38.4161, -63.6167),
    "벨리즈": (17.1899, -88.4976),
    "볼리비아": (-16.2902, -63.5887),
    "브라질": (-14.2350, -51.9253),
    "칠레": (-35.6751, -71.5430),
    "콜롬비아": (4.5709, -74.2973),
    "코스타리카": (9.7489, -83.7534),
    "쿠바": (21.5218, -77.7812),
    "도미니카 공화국": (18.7357, -70.1627),
    "에콰도르": (-1.8312, -78.1834),
    "엘살바도르": (13.7942, -88.8965),
    "과테말라": (15.7835, -90.2308),
    "온두라스": (15.2000, -86.2419),
    "멕시코": (23.6345, -102.5528),
    "니카라과": (12.8654, -85.2072),
    "파나마": (8.5380, -80.7821),
    "파라과이": (-23.4425, -58.4438),
    "페루": (-9.1900, -75.0152),
    "우루과이": (-32.5228, -55.7658),
    "베네수엘라": (6.4238, -66.5897),
    "아이티": (18.9712, -72.2852),
    "자메이카": (18.1096, -77.2975),
    "푸에르토리코": (18.2208, -66.5901),
    "트리니다드 토바고": (10.6918, -61.2225),
    "가이아나": (4.8604, -58.9302),
    "수리남": (3.9193, -56.0278),
    "프랑스령 기아나": (3.9339, -53.1258),
}


# --- 3. (★★★ 수정됨 ★★★) PDF 파싱 및 데이터 로딩 함수 ---
def parse_pdf_text(text):
    data = {}

    def extract_field(field_name_variations, text_block):
        """(수정) 필드 이름(키)에 줄바꿈이 있는 경우도 처리"""
        for field_name in field_name_variations:
            # 1. 쉼표/따옴표 기반 패턴
            pattern_csv = rf'"[^"]*"\s*,\s*"{re.escape(field_name)}"\s*,\s*"([^"]*)"'
            match_csv = re.search(pattern_csv, text_block)
            if match_csv: return match_csv.group(1).strip().strip('""')
            # 2. 줄바꿈 기반 패턴 (키 이름 자체의 줄바꿈 처리)
            newline_safe_field_name = re.escape(field_name).replace(r'\\\n', r'\s*\\n\s*')
            pattern_newline = rf'\n\d{{1,2}}\n{newline_safe_field_name}\n(.*?)(?=\n\d{{1,2}}\n|\n--- PAGE|\Z)'
            match_newline = re.search(pattern_newline, text_block, re.DOTALL)
            if match_newline:
                value = re.sub(r'\s*\n\s*', ' ', match_newline.group(1)).strip()
                return value
        return "정보 없음"

    data['대분류'] = extract_field(["갈등 대분류"], text)
    data['중분류'] = extract_field(["갈등 중분류"], text)
    data['소분류'] = extract_field(["갈등 소분류"], text)

    # (★★★ 수정됨 ★★★) 위치 정보 처리: 슬래시(/)로 분리하여 리스트로 저장
    location_str = extract_field(["위치"], text)
    if location_str != "정보 없음" and "/" in location_str:
        data['지역정보'] = [loc.strip() for loc in location_str.split('/') if loc.strip()]
    elif location_str != "정보 없음":
        data['지역정보'] = [location_str.strip()] # 단일 위치도 리스트로 저장
    else:
        data['지역정보'] = [] # 정보 없으면 빈 리스트

    data['기사제목'] = extract_field(["제목"], text)
    data['이벤트'] = extract_field(["보도 일자"], text)
    data['original_title'] = extract_field(["원문 기사 제목", "원문 기사 제 목", "원문 기사 제\n목"], text)

    url = "링크 없음"; found_url = False
    for field_name in ["출처(URL)"]:
        url_key_match_csv = re.search(rf'"{re.escape(field_name)}"', text)
        if url_key_match_csv:
            text_after_key = text[url_key_match_csv.end():]; url_match = re.search(r'(https?://[^\s)]+)', text_after_key)
            if url_match: url = url_match.group(1).strip().strip(')"'); found_url = True; break
    if not found_url:
        for field_name in ["출처(URL)"]:
            newline_safe_field_name = re.escape(field_name).replace(r'\\\n', r'\s*\\n\s*');
            pattern_newline_url = rf'\n12\n{newline_safe_field_name}\n[^\n]*\n\((https?://[^\)]+)\)';
            match_newline_url = re.search(pattern_newline_url, text, re.DOTALL)
            if match_newline_url: url = match_newline_url.group(1).strip(); found_url = True; break
    data['기사링크'] = url

    summary = "요약 정보 없음"; summary_key_variations = [r'기사 텍스트\s*\(\s*600자\s*이내\s*축약\s*\)', r'기사\s*텍스트\s*\(600자\s*이내\s*\n\s*축약\)', r'"관련 이벤트"']; summary_key_pattern = f'({"|".join(summary_key_variations)})'; summary_key_match = re.search(summary_key_pattern, text, re.DOTALL | re.IGNORECASE)
    if summary_key_match:
        text_after_key = text[summary_key_match.end():]
        summary_content_match = re.search(r'^\s*(.*?[\uAC00-\uD7A3]\s*다\.)\s*(?=\n[A-ZÀ-ÿa-z]|\n--- PAGE|\Z)', text_after_key, re.DOTALL | re.MULTILINE)
        if summary_content_match:
            summary_raw = summary_content_match.group(1).strip(); summary = re.sub(r'^,,', '', summary_raw.strip(), flags=re.MULTILINE); summary = re.sub(r'\s*\n\s*', ' ', summary); summary = summary.strip().strip('"')
        elif '"관련 이벤트"' in summary_key_match.group(1):
            summary_match_arg = re.search(r'^\s*,\s*,(.*?)(?=\n"\d{1,2}"\s*,|\n,,"기사 텍스트")', text_after_key, re.DOTALL)
            if summary_match_arg:
                summary_raw = summary_match_arg.group(1); summary_test = re.sub(r'^\s*,,', '', summary_raw, flags=re.MULTILINE).strip().strip('"'); summary_test = re.sub(r'\s*\n\s*', ' ', summary_test)
                if summary_test.endswith('다.'): summary = summary_test
    data['요약'] = summary; data['번역'] = summary
    for key, value in data.items():
        # 지역정보는 리스트이므로 is False 대신 not value 사용
        if key != '지역정보' and not value: data[key] = "정보 없음"
        elif key == '지역정보' and not value: data[key] = [] # 빈 리스트 유지
    return data


@st.cache_data
def load_data_from_pdfs(folder_path="sampledata"):
    all_articles = []; data_folder = Path(folder_path); first_pdf_text = None
    if not data_folder.exists() or not data_folder.is_dir(): st.error(f"'{folder_path}' 폴더를 찾을 수 없습니다."); return pd.DataFrame(), None
    pdf_files = list(data_folder.glob("*.pdf"))
    if not pdf_files: st.error(f"'{folder_path}' 폴더에 PDF 파일이 없습니다."); return pd.DataFrame(), None
    progress_bar = st.progress(0, text="PDF 파일 로딩 중...")
    for i, pdf_path in enumerate(pdf_files):
        try:
            doc = fitz.open(pdf_path); full_text = "".join(page.get_text("text", sort=False) for page in doc); doc.close()
            if i == 0: first_pdf_text = full_text
            article_data = parse_pdf_text(full_text); article_data['filename'] = pdf_path.name; all_articles.append(article_data)
            progress_bar.progress((i + 1) / len(pdf_files), text=f"PDF 파일 로딩 중: {pdf_path.name}")
        except Exception as e: st.warning(f"'{pdf_path.name}' 파일 처리 중 오류 발생: {e}")
    progress_bar.empty()
    if not all_articles: return pd.DataFrame(), first_pdf_text
    df = pd.DataFrame(all_articles);
    # 지역정보는 리스트이므로 검사 방식 변경
    required_cols = ['대분류', '중분류', '소분류', '지역정보', '기사제목', 'original_title', '이벤트', '번역', '요약']; all_cols_valid = True
    for col in required_cols:
        if col not in df.columns: df[col] = [] if col == '지역정보' else "정보 없음"; all_cols_valid = False
        elif col != '지역정보' and ((df[col] == "정보 없음").all() or df[col].isnull().all()): all_cols_valid = False
        # 지역정보 컬럼이 존재하지만 모든 행이 빈 리스트인 경우도 실패로 간주
        elif col == '지역정보' and all(not x for x in df[col]): all_cols_valid = False

    if not all_cols_valid: return df, first_pdf_text
    return df, None


# --- 4. 지오코딩 로직 (이전과 동일) ---
geolocator = Nominatim(user_agent="Mozilla/5.0")
# RateLimiter가 import되지 않았으면 수동 지연 사용
geocode_nominatim = RateLimiter(geolocator.geocode, min_delay_seconds=1.1) if RateLimiter else geolocator.geocode

def get_coords_via_openai(location_str):
    if not client: print("OpenAI client not initialized."); return None, None
    prompt = f"다음 장소의 위도(latitude)와 경도(longitude)를 'latitude, longitude' 형식으로 소수점 4자리까지 알려주세요. 모르면 'None, None'이라고 답해주세요.\n장소: \"{location_str}\"\n좌표:"
    try:
        response = client.chat.completions.create(model="gpt-4o", messages=[{"role": "system", "content": "You provide geographical coordinates."}, {"role": "user", "content": prompt}], max_tokens=20, temperature=0.0)
        time.sleep(1.1) # OpenAI 호출 후에도 약간의 지연 추가 (API 호출 제한 방지)
        result_text = response.choices[0].message.content.strip()
        coords = result_text.split(',')
        if len(coords) == 2:
            lat_str, lon_str = coords[0].strip(), coords[1].strip()
            try:
                if lat_str.lower() != 'none' and lon_str.lower() != 'none':
                    lat, lon = float(lat_str), float(lon_str); print(f"OpenAI Geocoding SUCCESS for '{location_str}': ({lat}, {lon})"); return lat, lon
                else: print(f"OpenAI Geocoding: Could not find coordinates for '{location_str}'"); return None, None
            except ValueError: print(f"OpenAI Geocoding: Could not parse coordinates from '{result_text}' for '{location_str}'"); return None, None
        else: print(f"OpenAI Geocoding: Unexpected response format for '{location_str}': {result_text}"); return None, None
    except Exception as e: print(f"OpenAI Geocoding Error for '{location_str}': {e}"); return None, None

@st.cache_data
def get_lat_lon(location_str):
    if location_str == "정보 없음" or not location_str: return None, None
    if location_str in MANUAL_LOCATION_CACHE: return MANUAL_LOCATION_CACHE[location_str]

    clean_str = re.sub(r'\s*&.*', '', location_str).strip()
    lat_openai, lon_openai = None, None # OpenAI 결과를 저장할 변수

    try:
        # RateLimiter 적용 (import 성공 시) 또는 직접 호출 (실패 시)
        location = geocode_nominatim(clean_str, timeout=10)
        if not RateLimiter: # RateLimiter 없으면 수동 지연
            time.sleep(1.1)
        if location:
            print(f"Geopy SUCCESS for '{location_str}': ({location.latitude}, {location.longitude})"); return location.latitude, location.longitude
        else:
            print(f"Geopy: Location not found for '{location_str}'")
            lat_openai, lon_openai = get_coords_via_openai(location_str)
            if lat_openai is not None: return lat_openai, lon_openai

    except Exception as e:
        print(f"Geopy Error for '{location_str}': {e}")
        lat_openai, lon_openai = get_coords_via_openai(location_str)
        if lat_openai is not None: return lat_openai, lon_openai

    if lat_openai is None:
        try:
            country_name = location_str.split(',')[0].strip()
            if country_name in MANUAL_LOCATION_CACHE: return MANUAL_LOCATION_CACHE[country_name]
            location_country = geocode_nominatim(country_name, timeout=10)
            if not RateLimiter: # RateLimiter 없으면 수동 지연
                time.sleep(1.1)
            if location_country:
                print(f"Geopy Country Fallback SUCCESS for '{location_str}' -> '{country_name}': ({location_country.latitude}, {location_country.longitude})"); return location_country.latitude, location_country.longitude
        except Exception as e: print(f"Geopy Country Fallback Error for '{country_name}': {e}")

    print(f"All Geocoding attempts FAILED for '{location_str}'")
    return None, None


# --- 5. Serper Google 검색 함수 (이전과 동일) ---
def call_google_search(query, api_key):
    url = "https://google.serper.dev/search"; payload = json.dumps({"q": query, "gl": "us", "hl": "ko"}); headers = {'X-API-KEY': api_key, 'Content-Type': 'application/json'}
    try:
        response = requests.post(url, headers=headers, data=payload, timeout=10); response.raise_for_status(); results = response.json(); organic_results = results.get('organic', []); formatted_results = []
        for item in organic_results[:5]: formatted_results.append({"title": item.get('title'), "link": item.get('link'), "snippet": item.get('snippet')})
        return formatted_results
    except requests.exceptions.RequestException as e: st.error(f"Google 검색 API(Serper) 호출 중 오류 발생: {e}"); return None


# --- 6. (★★★ 수정됨 ★★★) 메인 애플리케이션 실행 ---

df, debug_text = load_data_from_pdfs("sampledata")

if debug_text:
    st.error("데이터 파싱에 실패했습니다. 파싱 로직이 PDF 구조와 맞는지 확인해주세요.")
    st.subheader("디버깅 정보: 첫 번째 PDF 추출 원본 텍스트 (일부)")
    st.text_area("Raw Text", debug_text[:2000], height=300)
    # 지역정보 포함하여 실패한 컬럼 표시
    for col in ['대분류', '중분류', '소분류', '지역정보', '기사제목', 'original_title', '이벤트', '요약']:
        if col not in df: st.warning(f"경고: '{col}' 컬럼 자체가 없습니다.")
        elif col != '지역정보' and ((df[col] == "정보 없음").all() or df[col].isnull().all()): st.warning(f"경고: '{col}' 컬럼의 유효한 데이터를 찾지 못했습니다.")
        elif col == '지역정보' and all(not x for x in df[col]): st.warning(f"경고: '{col}' 컬럼의 유효한 데이터를 찾지 못했습니다.")


elif df.empty or all(not x for x in df['지역정보']): # 지역정보가 모든 행에서 빈 리스트인 경우
    st.error("데이터 로딩에 실패했거나 유효한 '지역정보'를 찾지 못했습니다. 앱을 실행할 수 없습니다.")
else:
    st.success(f"총 {len(df)}개의 PDF 기사를 성공적으로 로드하고 파싱했습니다.")
    keyword = st.text_input("키워드를 입력하세요 (예: 페루, 인플레이션, 리마 등)", "")

    if keyword:
        # (수정) 검색 가능 필터: 지역정보는 리스트가 비어있지 않은지만 확인
        df_searchable = df[
            (df['대분류'] != "정보 없음") &
            (df['기사제목'] != "정보 없음") &
            (df['original_title'] != "정보 없음") &
            (df['지역정보'].apply(lambda x: bool(x))) # 지역정보 리스트가 비어있지 않은 행만
        ]
        # (수정) 검색 조건(mask): 지역정보는 리스트 내 각 항목에 대해 검색
        mask = (
                df_searchable['대분류'].str.contains(keyword, case=False, na=False) |
                df_searchable['중분류'].str.contains(keyword, case=False, na=False) |
                df_searchable['소분류'].str.contains(keyword, case=False, na=False) |
                df_searchable['기사제목'].str.contains(keyword, case=False, na=False) |
                df_searchable['original_title'].str.contains(keyword, case=False, na=False) |
                # 지역정보 리스트 내 각 항목에 대해 keyword 포함 여부 확인
                df_searchable['지역정보'].apply(lambda loc_list: any(keyword.lower() in loc.lower() for loc in loc_list))
        )
        filtered_df = df_searchable[mask].copy()

        if filtered_df.empty:
            st.warning("검색 결과가 없습니다.")
        else:
            st.info("검색된 지역의 좌표를 변환 중입니다...")
            geocoding_placeholder = st.empty(); log_messages = []; location_cache = {}

            # (★★★ 수정됨 ★★★) 고유 위치 목록 생성: 리스트를 펼쳐서 생성
            unique_locations = set()
            for loc_list in filtered_df['지역정보']:
                unique_locations.update(loc_list) # set에 추가하여 자동 중복 제거
            unique_locations = list(unique_locations) # 다시 리스트로 변환
            total_locations = len(unique_locations)

            progress_bar = st.progress(0, text="좌표 변환 시작...")
            for i, location_str in enumerate(unique_locations):
                progress_text = f"변환 중 ({i+1}/{total_locations}): {location_str}"
                if location_str in MANUAL_LOCATION_CACHE: progress_text += " (수동 캐시 사용)"
                else: progress_text += " (Geopy/OpenAI 시도 중...)"
                progress_bar.progress((i + 1) / total_locations, text=progress_text)
                lat, lon = get_lat_lon(location_str); location_cache[location_str] = (lat, lon) # 결과를 캐시에 저장
                method_used = "수동 캐시" if location_str in MANUAL_LOCATION_CACHE else "Geopy/OpenAI"
                if lat is not None: log_messages.append(f"✅ **[성공]** `{location_str}` -> `({lat:.4f}, {lon:.4f})` (방법: {method_used})")
                else: log_messages.append(f"❌ **[실패]** `{location_str}` -> 모든 방법(수동, Geopy, OpenAI, 국가명) 실패")
            geocoding_placeholder.expander("좌표 변환 로그 보기", expanded=True).markdown("\n".join(log_messages))
            progress_bar.empty()

            # (★★★ 수정됨 ★★★) 지도 표시 로직: 각 기사의 각 위치에 마커 생성
            map_data = [] # 지도에 표시할 데이터 (마커 중복 방지용)
            has_valid_location = False # 유효한 좌표가 하나라도 있는지 확인

            for idx, row in filtered_df.iterrows():
                for location_str in row['지역정보']:
                    coords = location_cache.get(location_str)
                    if coords and coords[0] is not None:
                        has_valid_location = True
                        # 동일 기사, 동일 위치에 마커 중복 생성 방지
                        map_key = f"{idx}_{location_str}"
                        if map_key not in [d['key'] for d in map_data]:
                            map_data.append({
                                'key': map_key,
                                'latitude': coords[0],
                                'longitude': coords[1],
                                'popup_data': row # 마커 생성에 필요한 전체 행 데이터
                            })

            if not has_valid_location:
                st.warning("키워드에 해당하는 기사는 있으나, 지도에 표시할 위치 정보를 찾지 못했습니다. (위의 '좌표 변환 로그'를 확인하여 모든 위치가 ❌[실패]했는지 확인하세요.)")
            else:
                geocoding_placeholder.empty()

                # 7. Folium 지도 시각화 (마커 생성 로직 수정)
                # (수정) 지도 중심 계산: map_data에 있는 모든 유효 좌표 사용
                avg_lat = sum(d['latitude'] for d in map_data) / len(map_data)
                avg_lon = sum(d['longitude'] for d in map_data) / len(map_data)
                m = folium.Map(location=[avg_lat, avg_lon], zoom_start=4)

                color_map = {'국내(사회)': 'red', '국내(경제)': 'green', '국내(범죄)': 'black', '국제(국제관계)': 'purple', '정치': 'blue'}

                # (수정) map_data를 순회하며 마커 생성
                for data_point in map_data:
                    row_data = data_point['popup_data'] # 해당 마커의 원본 기사 데이터
                    popup_html = f"""
                    <h4>{row_data['기사제목']}</h4>
                    <i>{row_data['original_title']}</i><br><br>
                    <b>시간:</b> {row_data['이벤트']}<br>
                    <b>분류:</b> {row_data['대분류']} > {row_data['중분류']} > {row_data['소분류']}<br>
                    <a href="{row_data['기사링크']}" target="_blank">기사 원문 보기</a>
                    <hr>
                    <div id="details_{data_point['key']}" style="display:none; max-height: 150px; overflow-y: auto;">
                        <b>요약:</b><p>{row_data['요약']}</p>
                    </div>
                    <button onclick="
                        var el = document.getElementById('details_{data_point['key']}');
                        if (el.style.display == 'none') {{
                            el.style.display = 'block'; this.textContent = '요약 닫기';
                        }} else {{
                            el.style.display = 'none'; this.textContent = '요약 보기';
                        }}
                    ">요약 보기</button>
                    """
                    iframe = folium.IFrame(popup_html, width=350, height=280)
                    popup = folium.Popup(iframe, max_width=350)
                    folium.Marker(
                        location=[data_point['latitude'], data_point['longitude']],
                        popup=popup,
                        icon=folium.Icon(color=color_map.get(row_data['대분류'], 'gray')),
                        tooltip=row_data['기사제목'] # 툴팁은 한국어 제목 유지
                    ).add_to(m)

                st.subheader(f"'{keyword}' 검색 결과: {len(filtered_df)}개 기사 / {len(map_data)}개 위치") # 표시 정보 수정
                st_folium(m, width='100%', height=500)

                # 8. OpenAI + Serper 연동 (검색어 로직: 한국어/스페인어 분리)
                st.markdown("---")
                if st.button("🤖 AI로 유사 기사 더 알아보기 (실제 검색)"):
                    if not client:
                        st.error("OpenAI API 키를 설정해주세요.")
                    elif serper_api_key == "YOUR_SERPER_API_KEY" or not serper_api_key:
                        st.error("Serper (Google 검색) API 키가 설정되지 않았습니다.")
                    else:
                        with st.spinner("AI가 Google에서 유사한 기사를 검색하고 요약 중입니다..."):
                            # 1) 소분류 키워드 최대 5개 수집
                            sub_categories = set()
                            try:
                                if '소분류' in filtered_df.columns:
                                    sub_categories.update(filtered_df['소분류'].dropna().unique().tolist())
                            except Exception:
                                pass
                            sub_category_keywords_ko = [cat.strip() for cat in sub_categories if cat and cat != "정보 없음"]
                            sub_category_keywords_ko = sub_category_keywords_ko[:5]

                            # 2) 한국어 검색어
                            search_query_ko = f"라틴아메리카, 중남미, 뉴스, 기사, {keyword}".strip().strip(",")


                            # 3) 스페인어 검색용: keyword + 소분류를 간단 번역
                            def translate_to_es(text_list):
                                if not text_list:
                                    return []
                                try:
                                    msg = [
                                        {"role": "system",
                                         "content": "You are a concise translator from Korean to Spanish."},
                                        {"role": "user",
                                         "content": "다음 항목들을 스페인어로만 자연스럽게 번역해 주세요. 쉼표로 구분해서 반환: " + ", ".join(
                                             text_list)}
                                    ]
                                    tr = client.chat.completions.create(
                                        model="gpt-4o",
                                        messages=msg,
                                        temperature=0
                                    )
                                    out = tr.choices[0].message.content or ""
                                    # 쉼표 기준 분리 & 공백 트리밍
                                    return [t.strip() for t in out.split(",") if t.strip()]
                                except Exception:
                                    # 번역 실패 시 원문 사용
                                    return text_list


                            keyword_es_list = translate_to_es([str(keyword)]) if keyword else []
                            sub_category_keywords_es = translate_to_es(sub_category_keywords_ko)

                            keyword_es = keyword_es_list[0] if keyword_es_list else ""
                            base_es_terms = ["América Latina", "Latinoamérica", "noticias", "artículo"]
                            # 4) 스페인어 검색어
                            search_query_es = f"{', '.join(base_es_terms)}, {keyword_es} " + " ".join(
                                sub_category_keywords_es)


                            # 5) 공통: 검색 실행 함수
                            def run_search_and_summarize(search_query, lang_label="KO"):
                                st.markdown(f"### {'🇰🇷 한국어' if lang_label == 'KO' else '🇪🇸 스페인어'} 검색")
                                st.text(f"(검색어: {search_query})")

                                results = call_google_search(search_query, serper_api_key)
                                if not results:
                                    st.error("Google 검색 결과가 없습니다.")
                                    return

                                search_context = ""
                                for i, res in enumerate(results):
                                    title = res.get('title', '')
                                    link = res.get('link', '')
                                    snippet = res.get('snippet', '')
                                    search_context += f"--- Result {i + 1} ---\nTitle: {title}\nLink: {link}\nSnippet: {snippet}\n"

                                # 프롬프트: 출력은 한국어 요약 유지 (원하시면 스페인어 섹션만 스페인어 요약으로 바꿔도 됩니다)
                                prompt = f"""당신은 라틴아메리카 전문 뉴스 큐레이터입니다. 사용자가 '{keyword}' 키워드로 검색했으며, 아래는 Google 검색 결과입니다.
                <Google 검색 결과>
                {search_context}
                </Google 검색 결과>
                위 결과를 바탕으로 유사 기사 3개를 추천해주세요. 다음 형식을 지켜주세요.
                - **기사 제목:** [실제 제목]
                - **기사 링크:** [실제 링크]
                - **번역 및 요약:** [Snippet 바탕 AI 생성 한국어 요약]
                ---"""

                                try:
                                    response = client.chat.completions.create(
                                        model="gpt-4o",
                                        messages=[
                                            {"role": "system",
                                             "content": "You are a helpful assistant specializing in Latin American news."},
                                            {"role": "user", "content": prompt}
                                        ],
                                        temperature=0.2
                                    )
                                    result_text = response.choices[0].message.content
                                    st.subheader("AI 추천 유사 기사 (실제 검색 결과)")
                                    st.markdown(result_text)
                                except Exception as e:
                                    st.error(f"OpenAI API 호출 중 오류가 발생했습니다: {e}")


                            # 6) 두 언어 검색 각각 실행
                            run_search_and_summarize(search_query_ko, lang_label="KO")
                            run_search_and_summarize(search_query_es, lang_label="ES")

    # --- 앱 하단 저작권 정보 (이전과 동일) ---
    st.markdown("---")
    st.markdown(
        """<div style="text-align: center; color: grey; font-size: 0.8em;">
        This database and news map were created by the Institute for Spanish and Latin American Studies (HK+ Program) at Korea University.
        </div>""",
        unsafe_allow_html=True
    )

