"""
네이버 통합검색 순위 확인 (PC / 모바일) — Streamlit
"""
from __future__ import annotations

import io
from datetime import datetime

import pandas as pd
import streamlit as st

from naver_crawler import get_rank_mobile, get_rank_pc


def parse_bulk_lines(text: str) -> list[tuple[str, str]]:
    """한 줄에 `키워드,URL` 형식. 빈 줄·# 주석 무시."""
    rows: list[tuple[str, str]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "," not in line:
            continue
        keyword, url = line.split(",", 1)
        keyword, url = keyword.strip(), url.strip()
        if keyword and url:
            rows.append((keyword, url))
    return rows


st.set_page_config(page_title="네이버 순위 크롤러", layout="wide")

st.title("네이버 통합검색 순위")
st.caption(
    "키워드로 검색했을 때, 입력한 URL이 통합검색 결과(웹문서 영역)에서 몇 번째로 노출되는지 확인합니다."
)

with st.sidebar:
    st.header("옵션")
    headless = st.checkbox("헤드리스 모드 (브라우저 창 숨김)", value=True)
    max_rank = st.number_input("최대 확인 순위", min_value=10, max_value=300, value=100, step=10)
    st.markdown("---")
    st.markdown(
        "**일괄 입력 형식**\n\n"
        "한 줄에 하나씩:\n\n"
        "`키워드,URL`\n\n"
        "예: `소방공무원,efire.hackers.com/`"
    )
    st.markdown("---")
    st.markdown(
        "**필요 사항**\n\n"
        "- PC에 **Google Chrome** 설치\n\n"
        "- 첫 실행 시 ChromeDriver가 자동 설치될 수 있음\n\n"
        "- 네이버 페이지 구조 변경 시 선택자 조정이 필요할 수 있음"
    )

tab_bulk, tab_pc, tab_mo = st.tabs(["일괄 입력", "네이버 PC (단건)", "네이버 MO (단건)"])

with tab_bulk:
    st.subheader("키워드·URL 일괄 검색")
    st.caption("아래에 여러 줄을 붙여 넣으세요. 각 줄은 `키워드,URL` 형식입니다. URL에 `https://`가 없어도 됩니다.")

    bulk_text = st.text_area(
        "일괄 목록",
        height=280,
        placeholder="소방공무원,efire.hackers.com/\n소방공무원시험,eduwill.net/",
        help="쉼표 앞=검색 키워드, 쉼표 뒤=노출 여부를 볼 도메인 또는 URL",
    )

    col_a, col_b = st.columns(2)
    with col_a:
        run_pc_bulk = st.checkbox("PC 통합검색", value=True, key="bulk_pc")
    with col_b:
        run_mo_bulk = st.checkbox("모바일 통합검색", value=True, key="bulk_mo")

    run_bulk = st.button("일괄 순위 확인", type="primary", key="run_bulk")

    if run_bulk:
        rows = parse_bulk_lines(bulk_text)
        if not rows:
            st.warning("유효한 `키워드,URL` 줄이 없습니다. 한 줄에 쉼표로 키워드와 URL을 구분해 주세요.")
        elif not run_pc_bulk and not run_mo_bulk:
            st.warning("PC 또는 모바일 중 하나 이상 선택해 주세요.")
        else:
            results: list[dict] = []
            total = len(rows) * (int(run_pc_bulk) + int(run_mo_bulk))
            bar = st.progress(0.0)
            status = st.empty()
            done = 0

            for i, (kw, url) in enumerate(rows):
                row: dict = {"키워드": kw, "URL": url}
                if run_pc_bulk:
                    status.text(f"[{i + 1}/{len(rows)}] PC 검색 중… {kw}")
                    r = get_rank_pc(kw, url, headless=headless, max_rank=int(max_rank))
                    row["PC_순위"] = r.get("rank") if r.get("ok") else None
                    if not r.get("ok"):
                        row["PC_비고"] = r.get("error") or "오류"
                    elif r.get("rank"):
                        row["PC_비고"] = "OK"
                    else:
                        row["PC_비고"] = r.get("error") or "미노출"
                    done += 1
                    bar.progress(min(done / total, 1.0))

                if run_mo_bulk:
                    status.text(f"[{i + 1}/{len(rows)}] MO 검색 중… {kw}")
                    r = get_rank_mobile(kw, url, headless=headless, max_rank=int(max_rank))
                    row["MO_순위"] = r.get("rank") if r.get("ok") else None
                    if not r.get("ok"):
                        row["MO_비고"] = r.get("error") or "오류"
                    elif r.get("rank"):
                        row["MO_비고"] = "OK"
                    else:
                        row["MO_비고"] = r.get("error") or "미노출"
                    done += 1
                    bar.progress(min(done / total, 1.0))

                results.append(row)

            status.text("완료")
            bar.progress(1.0)

            df = pd.DataFrame(results)
            st.dataframe(df, use_container_width=True, hide_index=True)

            csv_buf = io.StringIO()
            df.to_csv(csv_buf, index=False, encoding="utf-8-sig")
            st.download_button(
                label="결과 CSV 다운로드",
                data=csv_buf.getvalue(),
                file_name=f"naver_rank_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv",
            )

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
