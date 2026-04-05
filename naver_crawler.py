"""
네이버 통합검색(웹문서) 영역 순위 추출 — PC / 모바일
"""
from __future__ import annotations

import time
from urllib.parse import parse_qs, quote_plus, unquote, urlparse, urlunparse

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

# 광고/내부 링크 제외용 (순위 후보에서 스킵)
_SKIP_HOST_PATTERNS = (
    "ad.search.naver.com",
    "adcr.naver.com",
    "nid.naver.com",
    "help.naver.com",
    "searchad.naver.com",
)
_SKIP_PATH_HINTS = ("/ad/", "javascript:")


def _normalize_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    if not url.lower().startswith(("http://", "https://")):
        url = "https://" + url
    p = urlparse(url)
    netloc = p.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    path = p.path or "/"
    path = path.rstrip("/") or "/"
    return urlunparse((p.scheme.lower(), netloc, path, "", p.query, ""))


def _extract_href_url(href: str) -> str:
    if not href:
        return ""
    href = href.strip()
    low = href.lower()
    if "link.naver.com" in low or "cr.naver.com" in low:
        try:
            q = parse_qs(urlparse(href).query)
            for key in ("url", "u", "target"):
                if key in q and q[key]:
                    return unquote(q[key][0])
        except Exception:
            pass
    return href


def _urls_match(target_norm: str, candidate: str) -> bool:
    if not target_norm or not candidate:
        return False
    cand = _normalize_url(_extract_href_url(candidate))
    if not cand:
        return False
    t = target_norm.rstrip("/")
    c = cand.rstrip("/")
    if t == c:
        return True
    if t in c or c in t:
        return True
    pt, pc = urlparse(t), urlparse(c)
    if pt.netloc and pc.netloc and pt.netloc == pc.netloc:
        if pt.path and (pt.path in pc.path or pc.path.startswith(pt.path.rstrip("/") + "/")):
            return True
    return False


def _should_skip_href(href: str) -> bool:
    if not href or not href.startswith("http"):
        return True
    low = href.lower()
    for p in _SKIP_PATH_HINTS:
        if p in low:
            return True
    try:
        host = urlparse(href).netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        for pat in _SKIP_HOST_PATTERNS:
            if pat in host:
                return True
    except Exception:
        return True
    return False


def build_chrome_options_pc(headless: bool) -> Options:
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    opts.add_argument("--lang=ko-KR")
    return opts


def build_chrome_options_mobile(headless: bool) -> Options:
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_experimental_option(
        "mobileEmulation",
        {
            "deviceMetrics": {"width": 390, "height": 844, "pixelRatio": 3},
            "userAgent": (
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
                "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
            ),
        },
    )
    opts.add_argument("--lang=ko-KR")
    return opts


def _create_driver(options: Options) -> webdriver.Chrome:
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=options)


def _scroll_load(driver: webdriver.Chrome, rounds: int = 6, pause: float = 0.9) -> None:
    for _ in range(rounds):
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(pause)


def _collect_organic_hrefs_pc(driver: webdriver.Chrome) -> list[str]:
    """PC 통합검색 메인팩에서 웹문서/블로그 등 외부 링크 순서대로 수집."""
    ordered: list[str] = []

    # 1) 리스트형 블록 단위 (통합검색 일반)
    selectors_blocks = [
        "#main_pack ul.lst_total > li.bx",
        "#main_pack .lst_total > li",
        "#main_pack div.total_wrap",
        "#main_pack .view_wrap",
    ]
    blocks = []
    for sel in selectors_blocks:
        blocks = driver.find_elements(By.CSS_SELECTOR, sel)
        if blocks:
            break

    if blocks:
        for block in blocks:
            try:
                links = block.find_elements(By.CSS_SELECTOR, "a[href^='http']")
                for a in links:
                    href = a.get_attribute("href") or ""
                    href = _extract_href_url(href)
                    if _should_skip_href(href):
                        continue
                    ordered.append(href)
                    break
            except Exception:
                continue

    # 2) 블록을 못 찾으면 메인팩 내 링크 순회
    if not ordered:
        try:
            main = driver.find_element(By.CSS_SELECTOR, "#main_pack")
            links = main.find_elements(By.CSS_SELECTOR, "a[href^='http']")
            for a in links:
                href = _extract_href_url(a.get_attribute("href") or "")
                if _should_skip_href(href):
                    continue
                ordered.append(href)
        except Exception:
            pass

    # 중복 제거(연속 동일 URL)
    deduped: list[str] = []
    prev = None
    for h in ordered:
        if h != prev:
            deduped.append(h)
        prev = h
    return deduped


def _collect_organic_hrefs_mobile(driver: webdriver.Chrome) -> list[str]:
    ordered: list[str] = []
    selectors_blocks = [
        "#container .lst_total li.bx",
        "#container ul.lst_total > li",
        "#main_pack ul.lst_total > li",
        ".api_subject_bx",
    ]
    blocks = []
    for sel in selectors_blocks:
        blocks = driver.find_elements(By.CSS_SELECTOR, sel)
        if blocks:
            break

    if blocks:
        for i, block in enumerate(blocks):
            try:
                links = block.find_elements(By.CSS_SELECTOR, "a[href^='http']")
                for a in links:
                    href = a.get_attribute("href") or ""
                    href = _extract_href_url(href)
                    if _should_skip_href(href):
                        continue
                    ordered.append(href)
                    break
            except Exception:
                continue

    if not ordered:
        for sel in ("#container", "#main_pack", "body"):
            try:
                root = driver.find_element(By.CSS_SELECTOR, sel)
                links = root.find_elements(By.CSS_SELECTOR, "a[href^='http']")
                for a in links:
                    href = _extract_href_url(a.get_attribute("href") or "")
                    if _should_skip_href(href):
                        continue
                    ordered.append(href)
                if ordered:
                    break
            except Exception:
                continue

    deduped: list[str] = []
    prev = None
    for h in ordered:
        if h != prev:
            deduped.append(h)
        prev = h
    return deduped


def get_rank_pc(keyword: str, target_url: str, headless: bool = True, max_rank: int = 100) -> dict:
    target_norm = _normalize_url(target_url)
    if not keyword.strip() or not target_norm:
        return {"ok": False, "error": "키워드와 URL을 입력하세요.", "rank": None}

    q = quote_plus(keyword.strip())
    url = f"https://search.naver.com/search.naver?where=nexearch&sm=top_hty&fbm=0&ie=utf8&query={q}"

    driver = _create_driver(build_chrome_options_pc(headless))
    try:
        driver.get(url)
        WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.CSS_SELECTOR, "#main_pack, body")))
        time.sleep(1.2)
        _scroll_load(driver)

        hrefs = _collect_organic_hrefs_pc(driver)
        for idx, href in enumerate(hrefs[:max_rank], start=1):
            if _urls_match(target_norm, href):
                return {"ok": True, "rank": idx, "matched_href": href, "error": None}

        return {
            "ok": True,
            "rank": None,
            "matched_href": None,
            "error": f"상위 {min(len(hrefs), max_rank)}위 안에서 찾지 못했습니다. (수집 링크 수: {len(hrefs)})",
        }
    except Exception as e:
        return {"ok": False, "error": str(e), "rank": None}
    finally:
        driver.quit()


def get_rank_mobile(keyword: str, target_url: str, headless: bool = True, max_rank: int = 100) -> dict:
    target_norm = _normalize_url(target_url)
    if not keyword.strip() or not target_norm:
        return {"ok": False, "error": "키워드와 URL을 입력하세요.", "rank": None}

    q = quote_plus(keyword.strip())
    url = f"https://m.search.naver.com/search.naver?sm=mtp_hty&where=m&query={q}"

    driver = _create_driver(build_chrome_options_mobile(headless))
    try:
        driver.get(url)
        WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.CSS_SELECTOR, "#container, #main_pack, body")))
        time.sleep(1.2)
        _scroll_load(driver)

        hrefs = _collect_organic_hrefs_mobile(driver)
        for idx, href in enumerate(hrefs[:max_rank], start=1):
            if _urls_match(target_norm, href):
                return {"ok": True, "rank": idx, "matched_href": href, "error": None}

        return {
            "ok": True,
            "rank": None,
            "matched_href": None,
            "error": f"상위 {min(len(hrefs), max_rank)}위 안에서 찾지 못했습니다. (수집 링크 수: {len(hrefs)})",
        }
    except Exception as e:
        return {"ok": False, "error": str(e), "rank": None}
    finally:
        driver.quit()
