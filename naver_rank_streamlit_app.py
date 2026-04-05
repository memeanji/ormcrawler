"""
네이버 통합검색 순위 확인 (PC / 모바일) — Streamlit
"""
import streamlit as st

from naver_crawler import get_rank_mobile, get_rank_pc

st.set_page_config(page_title="네이버 순위 크롤러", layout="wide")

st.title("네이버 통합검색 순위")
st.caption("키워드로 검색했을 때, 입력한 URL이 통합검색 결과(웹문서 영역)에서 몇 번째로 노출되는지 확인합니다.")

with st.sidebar:
    st.header("옵션")
    headless = st.checkbox("헤드리스 모드 (브라우저 창 숨김)", value=True)
    max_rank = st.number_input("최대 확인 순위", min_value=10, max_value=300, value=100, step=10)
    st.markdown("---")
    st.markdown(
        "**필요 사항**\n\n"
        "- PC에 **Google Chrome** 설치\n\n"
        "- 첫 실행 시 ChromeDriver가 자동 설치될 수 있음\n\n"
        "- 네이버 페이지 구조 변경 시 선택자 조정이 필요할 수 있음"
    )

tab_pc, tab_mo = st.tabs(["네이버 PC (통합검색)", "네이버 MO (통합검색)"])

with tab_pc:
    st.subheader("PC 통합검색 순위")
    kw_pc = st.text_input("검색 키워드 (PC)", placeholder="예: 파이썬 강의", key="kw_pc")
    url_pc = st.text_input("확인할 URL (PC)", placeholder="https://example.com/page", key="url_pc")
    run_pc = st.button("PC 순위 확인", type="primary", key="run_pc")

    if run_pc:
        with st.spinner("PC 통합검색 결과를 불러오는 중… (브라우저 자동 실행)"):
            result = get_rank_pc(kw_pc, url_pc, headless=headless, max_rank=int(max_rank))
        if not result.get("ok"):
            st.error(result.get("error") or "알 수 없는 오류")
        elif result.get("rank"):
            st.success(f"**{result['rank']}위** 에 노출됩니다.")
            if result.get("matched_href"):
                st.caption(f"매칭된 링크: {result['matched_href']}")
        else:
            st.warning(result.get("error") or "순위를 찾지 못했습니다.")

with tab_mo:
    st.subheader("모바일 통합검색 순위")
    kw_mo = st.text_input("검색 키워드 (MO)", placeholder="예: 파이썬 강의", key="kw_mo")
    url_mo = st.text_input("확인할 URL (MO)", placeholder="https://example.com/page", key="url_mo")
    run_mo = st.button("MO 순위 확인", type="primary", key="run_mo")

    if run_mo:
        with st.spinner("모바일 통합검색 결과를 불러오는 중…"):
            result = get_rank_mobile(kw_mo, url_mo, headless=headless, max_rank=int(max_rank))
        if not result.get("ok"):
            st.error(result.get("error") or "알 수 없는 오류")
        elif result.get("rank"):
            st.success(f"**{result['rank']}위** 에 노출됩니다.")
            if result.get("matched_href"):
                st.caption(f"매칭된 링크: {result['matched_href']}")
        else:
            st.warning(result.get("error") or "순위를 찾지 못했습니다.")
