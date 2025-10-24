# 🗺️ 라틴아메리카 갈등 뉴스 시각화 지도 (Latin American Conflict News Map)

[![Streamlit App](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://YOUR-STREAMLIT-APP-LINK.streamlit.app)
본 프로젝트는 **고려대학교 스페인라틴아메리카연구원(HK+ 사업단)**에서 수집한 '라틴아메리카 갈등 관련 뉴스 데이터' PDF를 분석하여, 인터랙티브 지도 위에 시각화하는 Streamlit 웹 애플리케이션입니다.

This project is a Streamlit web application that parses and visualizes the "Latin American Conflict-Related News Database" (in PDF format), collected by the **Institute for Spanish and Latin American Studies (HK+ Program) at Korea University**, on an interactive map.


---

## ✨ 주요 기능 (Features)

* **PDF 데이터 자동 파싱**: `sampledata` 폴더 내의 모든 PDF에서 메타데이터(분류, 지역, 제목, 요약 등)를 실시간으로 추출합니다.
* **키워드 검색**: 사용자가 '대/중/소분류', '지역명', '기사 제목' 등 다양한 키워드로 관련 뉴스를 검색할 수 있습니다.
* **인터랙티브 지도 시각화 (Folium)**: 검색된 뉴스의 '지역정보'를 Geopy로 좌표 변환하여, Folium 지도 위에 마커로 표시합니다.
* **동적 마커**: 갈등의 '대분류'(예: 국내(경제), 국내(사회))에 따라 마커의 색상이 다르게 표시됩니다.
* **상세 정보 팝업**: 마커를 클릭하면 기사 제목, 시간, 분류, 원문 링크, 그리고 '요약/번역 보기' 버튼이 포함된 팝업이 나타납니다.
* **AI 기반 기사 추천 (OpenAI)**: '🤖 AI로 유사 기사 더 알아보기' 버튼을 누르면, 현재 검색된 기사들의 문맥을 바탕으로 OpenAI (GPT-4o) API가 유사한 주제의 최신 기사를 추천합니다.

---

## 💻 기술 스택 (Tech Stack)

* **Core**: Python
* **Web Framework**: `Streamlit`
* **Data Handling**: `Pandas`
* **PDF Parsing**: `PyMuPDF (fitz)`
* **Geospatial**: `Folium`, `streamlit-folium` (지도 시각화), `Geopy` (좌표 변환)
* **AI**: `OpenAI` API

---

## 📂 데이터 및 연구 지원 (Data & Funding)

### 데이터
* **출처**: 본 앱에서 사용하는 모든 데이터는 `sampledata` 폴더에 포함되어 있으며, 이는 **고려대학교 스페인라틴아메리카연구원(한국연구재단 인문사회연구소지원사업)**에서 구축한 '라틴아메리카 갈등 관련 뉴스 데이터베이스'의 일부입니다.
* **가공**: 원문 기사 발췌, 갈등 분류, 한국어 요약 등 모든 2차 가공은 본 연구원에서 직접 수행하였습니다.

### 연구 지원
* 본 데이터베이스 구축 연구는 **교육부(Ministry of Education)**와 **한국연구재단(National Research Foundation of Korea)**의 후원을 받아 진행되었습니다.

---
