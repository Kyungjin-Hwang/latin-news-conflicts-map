import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from geopy.geocoders import Nominatim
from geopy.extra.rate_limiter import RateLimiter
import openai
from openai import OpenAI
import fitz  # PyMuPDF
import os
import re
from pathlib import Path

# --- 1. 초기 설정 ---

st.set_page_config(layout="wide")
st.title("🗺️ 라틴아메리카 뉴스 기사 지도 (PDF 기반)")

try:
    # ☁️ 클라우드 배포 시 이 st.secrets에서 키를 읽어옵니다.
    openai_api_key = st.secrets["OPENAI_API_KEY"]
except:
    # 🔒 로컬 테스트용 키를 다시 placeholder로 변경!
    openai_api_key = "YOUR_OPENAI_API_KEY"

# (수정) 이 if문은 "YOUR_OPENAI_API_KEY"라는 기본 문자열과 비교해야 합니다.
if openai_api_key == "YOUR_OPENAI_API_KEY" or not openai_api_key:
    st.warning("OpenAI API 키가 설정되지 않았습니다. '더 알아보기' 기능이 작동하지 않습니다.")
    client = None
else:
    client = OpenAI(api_key=openai_api_key)

# --- 2. (수정됨) 수동 위치 캐시 ---
# 네트워크 문제로 외부 서버 접속이 안될 경우를 대비한 수동 좌표 목록
# (실패 로그에 뜨는 지역이 있다면 여기에 "지역명": (위도, 경도) 형식으로 추가하세요)
MANUAL_LOCATION_CACHE = {
    "페루, 리마, Plaza San Martín": (-12.0505, -77.0339),
    "페루, 리마": (-12.0464, -77.0428),
    "페루, 리마, Comas": (-11.9333, -77.0500),
    "페루, 리마 & Callao": (-12.0464, -77.0428),  # Callao는 리마 근처이므로 리마 좌표 사용
    "볼리비아, 라파스": (-16.4897, -68.1193),
    "아르헨티나": (-38.4161, -63.6167),
    "도미니카공화국": (18.7357, -70.1627),
    "미국, 콜로라도, Aurora": (39.7294, -104.8319),
    # 필요시 계속 추가...
}


# --- 3. PDF 파싱 및 데이터 로딩 함수 (이전과 동일) ---

def parse_pdf_text(text):
    data = {}

    def extract_field(field_name, text_block):
        pattern_csv = rf'"[^"]*"\s*,\s*"{re.escape(field_name)}"\s*,\s*"([^"]*)"'
        match_csv = re.search(pattern_csv, text_block)
        if match_csv: return match_csv.group(1).strip().strip('""')
        pattern_newline = rf'\n\d{{1,2}}\n{re.escape(field_name)}\n(.*?)(?=\n\d{{1,2}}\n)'
        match_newline = re.search(pattern_newline, text_block, re.DOTALL)
        if match_newline: return re.sub(r'\s*\n\s*', ' ', match_newline.group(1)).strip()
        return "정보 없음"

    data['대분류'] = extract_field("갈등 대분류", text)
    data['중분류'] = extract_field("갈등 중분류", text)
    data['소분류'] = extract_field("갈등 소분류", text)
    data['지역정보'] = extract_field("위치", text)
    data['기사제목'] = extract_field("제목", text)
    data['이벤트'] = extract_field("보도 일자", text)
    url = "링크 없음";
    url_key_match_csv = re.search(r'"출처\(URL\)"', text)
    if url_key_match_csv:
        text_after_key = text[url_key_match_csv.end():];
        url_match = re.search(r'(https?://[^\s)]+)', text_after_key)
        if url_match: url = url_match.group(1).strip().strip(')"')
    if url == "링크 없음":
        pattern_newline_url = r'\n12\n출처\(URL\)\n[^\n]*\n\((https?://[^\)]+)\)';
        match_newline_url = re.search(pattern_newline_url, text, re.DOTALL)
        if match_newline_url: url = match_newline_url.group(1).strip()
    data['기사링크'] = url
    summary = "요약 정보 없음";
    summary_match_peru = re.search(r'\n15\n기사 텍스트\s*\([^\)]+\)\n(.*?)(?=\n[A-ZÀ-ÿ][a-z])', text, re.DOTALL)
    if summary_match_peru: summary = re.sub(r'\s*\n\s*', ' ', summary_match_peru.group(1).strip())
    if summary == "요약 정보 없음":
        summary_match_arg = re.search(r'"관련 이벤트"\s*,\s*,(.*?)(?=\n"\d{1,2}"\s*,|\n,,"기사 텍스트")', text, re.DOTALL)
        if summary_match_arg: summary = re.sub(r'^\s*,,', '', summary_match_arg.group(1),
                                               flags=re.MULTILINE).strip().strip('"')
    data['요약'] = summary;
    data['번역'] = summary
    for key, value in data.items():
        if not value: data[key] = "정보 없음"
    return data


@st.cache_data
def load_data_from_pdfs(folder_path="sampledata"):
    all_articles = [];
    data_folder = Path(folder_path);
    first_pdf_text = None
    if not data_folder.exists() or not data_folder.is_dir():
        st.error(f"'{folder_path}' 폴더를 찾을 수 없습니다.");
        return pd.DataFrame(), None
    pdf_files = list(data_folder.glob("*.pdf"))
    if not pdf_files: st.error(f"'{folder_path}' 폴더에 PDF 파일이 없습니다."); return pd.DataFrame(), None
    progress_bar = st.progress(0, text="PDF 파일 로딩 중...")
    for i, pdf_path in enumerate(pdf_files):
        try:
            doc = fitz.open(pdf_path);
            full_text = "".join(page.get_text("text", sort=False) for page in doc);
            doc.close()
            if i == 0: first_pdf_text = full_text
            article_data = parse_pdf_text(full_text);
            article_data['filename'] = pdf_path.name;
            all_articles.append(article_data)
            progress_bar.progress((i + 1) / len(pdf_files), text=f"PDF 파일 로딩 중: {pdf_path.name}")
        except Exception as e:
            st.warning(f"'{pdf_path.name}' 파일 처리 중 오류 발생: {e}")
    progress_bar.empty()
    if not all_articles: return pd.DataFrame(), first_pdf_text
    df = pd.DataFrame(all_articles);
    required_cols = ['대분류', '중분류', '소분류', '지역정보', '기사제목', '이벤트', '번역', '요약'];
    all_cols_valid = True
    for col in required_cols:
        if col not in df.columns:
            df[col] = "정보 없음"; all_cols_valid = False
        elif (df[col] == "정보 없음").all() or df[col].isnull().all():
            all_cols_valid = False
    if not all_cols_valid: return df, first_pdf_text
    return df, None


# --- 4. (수정됨) 지오코딩 설정 ---

geolocator = Nominatim(user_agent="Mozilla/5.0")
geocode = RateLimiter(geolocator.geocode, min_delay_seconds=1)


@st.cache_data
def get_lat_lon(location_str):
    if location_str == "정보 없음" or not location_str:
        return None, None

    # 1. (추가) 수동 캐시에서 먼저 찾기
    if location_str in MANUAL_LOCATION_CACHE:
        return MANUAL_LOCATION_CACHE[location_str]

    # 2. 수동 캐시에 없으면, 네트워크 접속 시도 (여전히 실패할 수 있음)
    clean_str = re.sub(r'\s*&.*', '', location_str).strip()
    try:
        location = geocode(clean_str, timeout=20)
        if location:
            return location.latitude, location.longitude
        else:
            if clean_str != location_str:
                location_original = geocode(location_str, timeout=20)
                if location_original:
                    return location_original.latitude, location_original.longitude
            print(f"Geocoding (Fallback): Location not found for '{location_str}'")
    except Exception as e:
        print(f"Geocoding (Fallback) Error for '{location_str}': {e}")

    # 3. (추가) 수동 캐시에 없는 지역이 실패할 경우, 해당 지역의 "국가명"만으로 재시도
    # 예: "페루, 리마, Cieneguilla" -> "페루"
    try:
        country_name = location_str.split(',')[0].strip()
        if country_name in MANUAL_LOCATION_CACHE:  # 국가명이 캐시에 있다면
            return MANUAL_LOCATION_CACHE[country_name]

        # 국가명으로 다시 네트워크 시도
        location_country = geocode(country_name, timeout=20)
        if location_country:
            # 국가명 좌표라도 반환
            return location_country.latitude, location_country.longitude
    except Exception as e:
        print(f"Geocoding (Country Fallback) Error for '{country_name}': {e}")

    return None, None  # 모든 시도 실패


# --- 5. 메인 애플리케이션 실행 ---

df, debug_text = load_data_from_pdfs("sampledata")

if debug_text:
    st.error("데이터 파싱에 실패했습니다. 파싱 로직이 PDF 구조와 맞는지 확인해주세요.")
    st.subheader("디버깅 정보: 첫 번째 PDF 추출 원본 텍스트 (일부)")
    st.text_area("Raw Text", debug_text[:2000], height=300)
    for col in ['대분류', '중분류', '소분류', '지역정보', '기사제목', '이벤트', '요약']:
        if col not in df or (df[col] == "정보 없음").all() or df[col].isnull().all():
            st.warning(f"경고: '{col}' 컬럼의 유효한 데이터를 찾지 못했습니다.")

elif df.empty or (df['지역정보'] == "정보 없음").all():
    st.error("데이터 로딩에 실패했거나 유효한 '지역정보'를 찾지 못했습니다. 앱을 실행할 수 없습니다.")
else:
    st.success(f"총 {len(df)}개의 PDF 기사를 성공적으로 로드하고 파싱했습니다.")

    keyword = st.text_input("키워드를 입력하세요 (예: 페루, 인플레이션, 리마 등)", "")

    if keyword:
        df_searchable = df[(df['대분류'] != "정보 없음") & (df['지역정보'] != "정보 없음")]
        mask = (
                df_searchable['대분류'].str.contains(keyword, case=False, na=False) |
                df_searchable['중분류'].str.contains(keyword, case=False, na=False) |
                df_searchable['소분류'].str.contains(keyword, case=False, na=False) |
                df_searchable['기사제목'].str.contains(keyword, case=False, na=False) |
                df_searchable['지역정보'].str.contains(keyword, case=False, na=False)
        )
        filtered_df = df_searchable[mask].copy()

        if filtered_df.empty:
            st.warning("검색 결과가 없습니다.")
        else:
            st.info("검색된 지역의 좌표를 변환 중입니다...")
            geocoding_placeholder = st.empty()
            log_messages = []

            unique_locations = filtered_df['지역정보'].unique()
            total_locations = len(unique_locations)
            location_cache = {}

            progress_bar = st.progress(0, text="좌표 변환 시작...")

            for i, location_str in enumerate(unique_locations):
                progress_bar.progress((i + 1) / total_locations, text=f"변환 중: {location_str}")

                lat, lon = get_lat_lon(location_str)  # 수정된 캐시 우선 함수 호출
                location_cache[location_str] = (lat, lon)

                if lat is not None:
                    log_messages.append(f"✅ **[성공]** `{location_str}` -> `({lat:.4f}, {lon:.4f})`")
                else:
                    log_messages.append(f"❌ **[실패]** `{location_str}` -> 수동 캐시에 없으며, 네트워크 접속에 실패했습니다.")

                geocoding_placeholder.expander("좌표 변환 로그 보기", expanded=True).markdown("\n".join(log_messages))

            progress_bar.empty()

            coords = filtered_df['지역정보'].map(location_cache)
            filtered_df['latitude'] = [c[0] for c in coords]
            filtered_df['longitude'] = [c[1] for c in coords]

            filtered_df.dropna(subset=['latitude', 'longitude'], inplace=True)

            if filtered_df.empty:
                st.warning("키워드에 해당하는 기사는 있으나, 지도에 표시할 위치 정보를 찾지 못했습니다. (위의 '좌표 변환 로그'를 확인하여 모든 위치가 ❌[실패]했는지 확인하세요.)")
            else:
                geocoding_placeholder.empty()

                # 6. Folium 지도 시각화
                m = folium.Map(location=[filtered_df['latitude'].mean(), filtered_df['longitude'].mean()], zoom_start=4)
                color_map = {'국내(사회)': 'red', '국내(경제)': 'green', '국내(범죄)': 'black', '국제(국제관계)': 'purple', '정치': 'blue'}
                for idx, row in filtered_df.iterrows():
                    popup_html = f"""
                    <h4>{row['기사제목']}</h4>
                    <b>시간:</b> {row['이벤트']}<br>
                    <b>분류:</b> {row['대분류']} > {row['중분류']} > {row['소분류']}<br>
                    <a href="{row['기사링크']}" target="_blank">기사 원문 보기</a>
                    <hr>
                    <div id="details_{idx}" style="display:none; max-height: 150px; overflow-y: auto;">
                        <b>요약:</b><p>{row['요약']}</p>
                    </div>
                    <button onclick="
                        var el = document.getElementById('details_{idx}');
                        if (el.style.display == 'none') {{
                            el.style.display = 'block'; this.textContent = '요약 닫기';
                        }} else {{
                            el.style.display = 'none'; this.textContent = '요약 보기';
                        }}
                    ">요약 보기</button>
                    """
                    iframe = folium.IFrame(popup_html, width=350, height=250)
                    popup = folium.Popup(iframe, max_width=350)
                    folium.Marker(
                        location=[row['latitude'], row['longitude']],
                        popup=popup,
                        icon=folium.Icon(color=color_map.get(row['대분류'], 'gray')),
                        tooltip=row['기사제목']
                    ).add_to(m)

                st.subheader(f"'{keyword}' 검색 결과: {len(filtered_df)}개")
                st_folium(m, width='100%', height=500)

                # 7. OpenAI API 연동
                st.markdown("---")
                if st.button("🤖 AI로 유사 기사 더 알아보기"):
                    if not client:
                        st.error("OpenAI API 키가 설정되지 않았습니다.")
                    else:
                        with st.spinner("AI가 유사한 기사를 찾고 있습니다..."):
                            context_articles = "\n".join(
                                [f"- 제목: {row['기사제목']}, 요약: {row['요약']}" for _, row in filtered_df.iterrows()])
                            prompt = f"""
                            당신은 라틴아메리카 전문 뉴스 큐레이터입니다.
                            아래는 사용자가 방금 '{keyword}' 키워드로 검색한 뉴스 기사 목록입니다.
                            <기존 기사 목록>
                            {context_articles}
                            </기존 기사 목록>
                            위 기사들과 주제, 지역, 내용 면에서 유사한 최신 기사 3개를 찾아서 제시해주세요.
                            각 기사마다 아래와 같은 형식으로 답변해주세요.
                            - **기사 제목:** [새로운 기사의 제목]
                            - **기사 링크:** [실제 링크가 아닌 예시 링크 (예: http://example.com/news/123)]
                            - **번역 및 요약:** [새로운 기사에 대한 간략한 '번역 및 요약]
                            ---
                            """
                            try:
                                response = client.chat.completions.create(
                                    model="gpt-4o",
                                    messages=[
                                        {"role": "system",
                                         "content": "You are a helpful assistant specializing in Latin American news."},
                                        {"role": "user", "content": prompt}
                                    ]
                                )
                                result_text = response.choices[0].message.content
                                st.subheader("AI 추천 유사 기사")
                                st.markdown(result_text)
                            except Exception as e:
                                st.error(f"API 호출 중 오류가 발생했습니다: {e}")