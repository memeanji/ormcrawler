
import io
import re
import time
import queue
import random
import threading
from dataclasses import dataclass, asdict
from typing import List, Optional, Dict, Any
from urllib.parse import quote, urlparse

import pandas as pd
import streamlit as st
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


APP_TITLE = "네이버 통검 키워드 순위 크롤러"
APP_FOOTER = "© ORM.CO.KR 내부 운영툴"
MAX_CONCURRENT_WORKERS = 2
DEFAULT_NAVER_PC = "https://search.naver.com/search.naver?query={query}"
DEFAULT_NAVER_MO = "https://m.search.naver.com/search.naver?query={query}"


# -----------------------------
# Models
# -----------------------------
@dataclass
class TargetRule:
    label: str
    match_type: str   # domain | text | regex
    match_value: str

@dataclass
class CrawlTask:
    keyword: str
    device: str       # PC | MO
    target_rules: List[TargetRule]
    request_id: str

@dataclass
class CrawlResult:
    request_id: str
    keyword: str
    device: str
    search_url: str
    rank: Optional[int]
    matched_label: Optional[str]
    matched_href: Optional[str]
    matched_text: Optional[str]
    total_links_seen: int
    status: str
    error: Optional[str] = None


# -----------------------------
# Shared state
# -----------------------------
if "task_queue" not in st.session_state:
    st.session_state.task_queue = queue.Queue()

if "results_store" not in st.session_state:
    st.session_state.results_store = {}

if "status_store" not in st.session_state:
    st.session_state.status_store = {}

if "workers_started" not in st.session_state:
    st.session_state.workers_started = False


# -----------------------------
# Helpers
# -----------------------------
def normalize_domain(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"^https?://", "", value)
    value = value.split("/")[0]
    return value.replace("www.", "")

def extract_domain(href: str) -> str:
    try:
        parsed = urlparse(href)
        host = parsed.netloc.lower().replace("www.", "")
        return host
    except Exception:
        return ""

def matches_rule(href: str, text: str, rule: TargetRule) -> bool:
    href_norm = href.strip()
    text_norm = (text or "").strip()

    if rule.match_type == "domain":
        domain = normalize_domain(rule.match_value)
        href_domain = extract_domain(href_norm)
        return href_domain == domain or href_domain.endswith("." + domain)

    if rule.match_type == "text":
        return rule.match_value.lower() in text_norm.lower() or rule.match_value.lower() in href_norm.lower()

    if rule.match_type == "regex":
        try:
            return re.search(rule.match_value, href_norm, flags=re.I) is not None or \
                   re.search(rule.match_value, text_norm, flags=re.I) is not None
        except re.error:
            return False

    return False

def parse_target_rules(df: pd.DataFrame) -> List[TargetRule]:
    rules = []
    for _, row in df.iterrows():
        label = str(row.get("label", "")).strip()
        match_type = str(row.get("match_type", "")).strip().lower()
        match_value = str(row.get("match_value", "")).strip()
        if not label or not match_type or not match_value:
            continue
        if match_type not in {"domain", "text", "regex"}:
            continue
        rules.append(TargetRule(label=label, match_type=match_type, match_value=match_value))
    return rules

def default_target_df() -> pd.DataFrame:
    return pd.DataFrame([
        {"label": "해커스소방", "match_type": "domain", "match_value": "efire.hackers.com"},
        {"label": "해커스공무원", "match_type": "domain", "match_value": "gosi.hackers.com"},
        {"label": "브랜드명 포함", "match_type": "text", "match_value": "해커스소방"},
    ])

def default_keyword_df() -> pd.DataFrame:
    return pd.DataFrame({
        "keyword": ["소방공무원", "소방학개론", "소방 모의고사"]
    })

def build_search_url(keyword: str, device: str) -> str:
    tmpl = DEFAULT_NAVER_PC if device == "PC" else DEFAULT_NAVER_MO
    return tmpl.format(query=quote(keyword))

def collect_rank_from_page(page, target_rules: List[TargetRule], search_url: str, request_id: str, keyword: str, device: str) -> CrawlResult:
    links = page.locator("a[href]")
    count = links.count()

    seen = []
    rank_counter = 0

    for idx in range(count):
        try:
            item = links.nth(idx)
            href = item.get_attribute("href") or ""
            text = item.inner_text(timeout=1000).strip()
        except Exception:
            continue

        href = href.strip()
        if not href or href.startswith("javascript:"):
            continue

        # 광고/네이버 내부링크/스크립트성 링크 제외를 너무 강하게 하지 않고,
        # 실제 외부 도메인 링크 위주로 보되 텍스트/정규식 매칭도 허용
        rank_counter += 1
        seen.append((href, text))

        for rule in target_rules:
            if matches_rule(href, text, rule):
                return CrawlResult(
                    request_id=request_id,
                    keyword=keyword,
                    device=device,
                    search_url=search_url,
                    rank=rank_counter,
                    matched_label=rule.label,
                    matched_href=href,
                    matched_text=text,
                    total_links_seen=len(seen),
                    status="완료",
                    error=None,
                )

    return CrawlResult(
        request_id=request_id,
        keyword=keyword,
        device=device,
        search_url=search_url,
        rank=None,
        matched_label=None,
        matched_href=None,
        matched_text=None,
        total_links_seen=len(seen),
        status="완료",
        error=None,
    )

def crawl_one(task: CrawlTask) -> CrawlResult:
    search_url = build_search_url(task.keyword, task.device)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1440 if task.device == "PC" else 430, "height": 1600 if task.device == "PC" else 2200},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                if task.device == "PC"
                else
                "Mozilla/5.0 (Linux; Android 14; SM-S918N) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/122.0.0.0 Mobile Safari/537.36"
            ),
            locale="ko-KR",
        )
        page = context.new_page()

        try:
            page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(random.randint(1800, 3200))
            return collect_rank_from_page(page, task.target_rules, search_url, task.request_id, task.keyword, task.device)
        except PlaywrightTimeoutError as e:
            return CrawlResult(
                request_id=task.request_id,
                keyword=task.keyword,
                device=task.device,
                search_url=search_url,
                rank=None,
                matched_label=None,
                matched_href=None,
                matched_text=None,
                total_links_seen=0,
                status="실패",
                error=f"Timeout: {e}",
            )
        except Exception as e:
            return CrawlResult(
                request_id=task.request_id,
                keyword=task.keyword,
                device=task.device,
                search_url=search_url,
                rank=None,
                matched_label=None,
                matched_href=None,
                matched_text=None,
                total_links_seen=0,
                status="실패",
                error=str(e),
            )
        finally:
            context.close()
            browser.close()

def worker_loop(worker_name: str):
    while True:
        task: CrawlTask = st.session_state.task_queue.get()
        st.session_state.status_store[task.request_id]["running"] += 1
        st.session_state.status_store[task.request_id]["queued"] -= 1

        result = crawl_one(task)
        st.session_state.results_store.setdefault(task.request_id, []).append(asdict(result))

        st.session_state.status_store[task.request_id]["running"] -= 1
        st.session_state.status_store[task.request_id]["done"] += 1

        if result["status"] if isinstance(result, dict) else result.status == "실패":
            st.session_state.status_store[task.request_id]["failed"] += 1

        st.session_state.task_queue.task_done()

def start_workers_once():
    if st.session_state.workers_started:
        return
    for i in range(MAX_CONCURRENT_WORKERS):
        th = threading.Thread(target=worker_loop, args=(f"worker-{i+1}",), daemon=True)
        th.start()
    st.session_state.workers_started = True

def results_to_dataframe(rows: List[Dict[str, Any]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=[
            "request_id","keyword","device","search_url","rank","matched_label",
            "matched_href","matched_text","total_links_seen","status","error"
        ])
    df = pd.DataFrame(rows)
    df = df.sort_values(["keyword", "device"], na_position="last").reset_index(drop=True)
    return df

def make_xlsx_bytes(df: pd.DataFrame) -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="results")
    return output.getvalue()

def make_csv_utf8sig_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")

def make_request_id() -> str:
    return time.strftime("%Y%m%d_%H%M%S")

def enqueue_tasks(keywords: List[str], devices: List[str], target_rules: List[TargetRule], request_id: str):
    total = 0
    st.session_state.results_store[request_id] = []
    st.session_state.status_store[request_id] = {
        "queued": 0,
        "running": 0,
        "done": 0,
        "failed": 0,
        "total": 0,
    }

    for keyword in keywords:
        for device in devices:
            task = CrawlTask(
                keyword=keyword,
                device=device,
                target_rules=target_rules,
                request_id=request_id,
            )
            st.session_state.task_queue.put(task)
            st.session_state.status_store[request_id]["queued"] += 1
            total += 1

    st.session_state.status_store[request_id]["total"] = total


# -----------------------------
# UI
# -----------------------------
st.set_page_config(page_title=APP_TITLE, layout="wide")
start_workers_once()

st.title(APP_TITLE)
st.caption("PC / MO 통합검색 기준으로 타겟 URL·텍스트·정규식 매칭 순위를 수집합니다.")

with st.expander("사용 방법", expanded=False):
    st.markdown("""
    1. **키워드 목록**을 넣습니다.  
    2. **타겟 규칙**을 여러 개 등록합니다.  
       - `domain`: efire.hackers.com  
       - `text`: 해커스소방  
       - `regex`: hackers|gosi  
    3. PC / MO를 선택하고 실행합니다.  
    4. 결과를 **Excel(.xlsx)** 또는 **CSV(utf-8-sig)** 로 내려받습니다.
    """)

left, right = st.columns([1, 1])

with left:
    st.subheader("1) 키워드 입력")
    keyword_mode = st.radio("입력 방식", ["직접 입력", "엑셀 업로드"], horizontal=True)

    keywords = []
    if keyword_mode == "직접 입력":
        keyword_text = st.text_area(
            "키워드 (줄바꿈 구분)",
            value="소방공무원\n소방학개론\n소방 모의고사",
            height=220,
        )
        keywords = [x.strip() for x in keyword_text.splitlines() if x.strip()]
    else:
        up_keywords = st.file_uploader("키워드 엑셀/CSV 업로드", type=["xlsx", "csv"], key="keywords")
        if up_keywords:
            if up_keywords.name.lower().endswith(".csv"):
                kdf = pd.read_csv(up_keywords)
            else:
                kdf = pd.read_excel(up_keywords)
            st.dataframe(kdf, use_container_width=True)
            guess_col = "keyword" if "keyword" in kdf.columns else kdf.columns[0]
            keywords = kdf[guess_col].dropna().astype(str).str.strip().tolist()

with right:
    st.subheader("2) 타겟 규칙 입력")
    target_mode = st.radio("타겟 입력 방식", ["기본 예시 사용", "직접 입력/수정", "엑셀 업로드"], horizontal=True)

    if target_mode == "기본 예시 사용":
        target_df = default_target_df()
        st.dataframe(target_df, use_container_width=True)
    elif target_mode == "직접 입력/수정":
        target_df = st.data_editor(
            default_target_df(),
            num_rows="dynamic",
            use_container_width=True,
            key="target_editor"
        )
    else:
        up_targets = st.file_uploader("타겟 규칙 엑셀/CSV 업로드", type=["xlsx", "csv"], key="targets")
        if up_targets:
            if up_targets.name.lower().endswith(".csv"):
                target_df = pd.read_csv(up_targets)
            else:
                target_df = pd.read_excel(up_targets)
        else:
            target_df = default_target_df()
        st.dataframe(target_df, use_container_width=True)

target_rules = parse_target_rules(pd.DataFrame(target_df))

st.divider()

col1, col2, col3 = st.columns([1, 1, 1])
with col1:
    devices = st.multiselect("3) 디바이스 선택", ["PC", "MO"], default=["PC", "MO"])
with col2:
    request_name = st.text_input("4) 실행명", value=f"rank_run_{make_request_id()}")
with col3:
    st.markdown("")
    st.markdown("")

run = st.button("크롤링 실행", type="primary", use_container_width=True)

if run:
    if not keywords:
        st.error("키워드를 1개 이상 넣어주세요.")
    elif not devices:
        st.error("PC 또는 MO를 1개 이상 선택해주세요.")
    elif not target_rules:
        st.error("타겟 규칙을 1개 이상 등록해주세요.")
    else:
        request_id = request_name.strip() or make_request_id()
        enqueue_tasks(keywords, devices, target_rules, request_id)
        st.success(f"작업이 등록되었습니다. 실행명: {request_id}")

st.divider()
st.subheader("작업 현황")

status_rows = []
for req_id, info in st.session_state.status_store.items():
    status_rows.append({
        "request_id": req_id,
        "total": info["total"],
        "queued": info["queued"],
        "running": info["running"],
        "done": info["done"],
        "failed": info["failed"],
    })

status_df = pd.DataFrame(status_rows)
if not status_df.empty:
    status_df = status_df.sort_values("request_id", ascending=False)
    st.dataframe(status_df, use_container_width=True)
else:
    st.info("아직 등록된 작업이 없습니다.")

selected_request = st.selectbox(
    "결과 확인할 실행명 선택",
    options=[""] + sorted(list(st.session_state.results_store.keys()), reverse=True)
)

if selected_request:
    result_rows = st.session_state.results_store.get(selected_request, [])
    result_df = results_to_dataframe(result_rows)
    st.subheader(f"결과: {selected_request}")
    st.dataframe(result_df, use_container_width=True, height=420)

    c1, c2 = st.columns(2)
    with c1:
        st.download_button(
            "Excel 다운로드 (.xlsx)",
            data=make_xlsx_bytes(result_df),
            file_name=f"{selected_request}_naver_rank_results.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
    with c2:
        st.download_button(
            "CSV 다운로드 (utf-8-sig)",
            data=make_csv_utf8sig_bytes(result_df),
            file_name=f"{selected_request}_naver_rank_results_utf8sig.csv",
            mime="text/csv",
            use_container_width=True,
        )

st.markdown("---")
st.caption(APP_FOOTER)
