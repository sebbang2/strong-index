"""네이버증권 코스피 전체 종목 중 코스피 대비 상대강도(RS)가 강한 종목을 저장한다.

RS 지수 = (종목의 기간 누적수익률 / 코스피의 기간 누적수익률) x 100
100보다 크면 같은 기간 코스피보다 강했던 종목으로 본다.

실행 예시
---------
    python strong_index.py
    python strong_index.py --lookback-days 180 --min-rs 105
"""

from __future__ import annotations

import argparse
import ast
import csv
import json
import os
import re
import sys
import time
from dataclasses import dataclass, replace
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests
from bs4 import BeautifulSoup


OUTPUT_DIR = Path("output")
HISTORY_FILE = OUTPUT_DIR / "stong_index.csv"  # 요구사항의 파일명(stong)을 그대로 사용
INDEX_HISTORY_FILE = OUTPUT_DIR / "index_snapshots.csv"
NAVER_FINANCE = "https://finance.naver.com"
PRICE_API = "https://api.finance.naver.com/siseJson.naver"
NAVER_CHART_API = "https://api.stock.naver.com/chart/domestic"
NAVER_STOCK_LIST_API = "https://api.stock.naver.com/stock/exchange/KOSPI/marketValue"
KOSPI_SYMBOL = "KOSPI"
KOSDAQ_SYMBOL = "KOSDAQ"
ETF_DISPLAY_LIMIT = 3
ETF_HOLDINGS_CACHE_VERSION = 2
ETF_MASTER_CACHE_FILE = OUTPUT_DIR / "etf_top_holdings_master.json"
THEME_MASTER_CACHE_FILE = OUTPUT_DIR / "naver_theme_memberships_master.json"
THEME_DISPLAY_LIMIT = 3
INDUSTRY_MASTER_CACHE_FILE = OUTPUT_DIR / "naver_industry_memberships_master.json"
INDEX_CSV_FIELDS = ["run_date", "index_name", "close", "ma20", "ma20_gap_pct"]
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Referer": "https://finance.naver.com/",
    "Accept-Language": "ko-KR,ko;q=0.9",
}
CSV_FIELDS = [
    "run_date",
    "code",
    "name",
    "close",
    "market_cap_억원",
    "stock_return_pct",
    "kospi_return_pct",
    "rs_index",
    "ma20",
    "ma20_gap_pct",
    "volatility_contraction",
    "price_change_5d_pct",
    "ma120",
    "avg_volume_55",
    "avg_volume_10",
    "volume_change_pct",
    "industry",
    "core_theme",
    "etf_trend_good",
    "etf_names",
    "etf_details",
    "source_url",
]


class StrongIndexError(RuntimeError):
    """실행 화면에 안내할 수 있는 오류."""


@dataclass(frozen=True)
class Stock:
    code: str
    name: str


@dataclass(frozen=True)
class Etf:
    code: str
    name: str
    market_cap: int


@dataclass(frozen=True)
class Result:
    stock: Stock
    close: float
    market_cap: int
    stock_return: float
    kospi_return: float
    rs_index: float
    ma20: float
    ma20_gap: float
    ma120: float
    avg_volume_55: float
    avg_volume_10: float
    volume_change_pct: float
    volatility_contraction: bool
    price_change_5d: float
    industry: str
    theme: str
    etf_trend_good: str = "미확인"
    etf_names: str = ""
    etf_details: str = ""


# 자주 쓰이는 성장 산업/테마를 우선 분류한다. 한 종목이 여러 조건에 맞으면 모두 표시한다.
# 목록은 필요에 맞게 계속 보완할 수 있으며, 목록에 없으면 네이버증권의 업종을 사용한다.
THEME_RULES: tuple[tuple[set[str], str, str], ...] = (
    (
        {"삼성전자", "SK하이닉스", "한미반도체", "HPSP", "DB하이텍", "동진쎄미켐", "솔브레인", "원익IPS"},
        "반도체·반도체장비",
        "AI 반도체·HBM·설비투자",
    ),
    (
        {"두산로보틱스", "레인보우로보틱스", "HD현대로보틱스"},
        "로봇",
        "제조자동화·정부 로봇산업",
    ),
    (
        {"삼성전자", "SK하이닉스", "NAVER", "카카오", "더존비즈온", "LS ELECTRIC", "효성중공업", "HD현대일렉트릭"},
        "AI·데이터센터",
        "AI 투자·데이터센터 전력 인프라",
    ),
    (
        {"LG에너지솔루션", "삼성SDI", "LG화학", "포스코퓨처엠", "SK이노베이션", "롯데에너지머티리얼즈", "금양"},
        "2차전지",
        "전기차·ESS·배터리 공급망",
    ),
    (
        {"한화에어로스페이스", "한화시스템", "LIG넥스원", "현대로템", "한국항공우주", "풍산", "HD현대중공업"},
        "방산",
        "전쟁수혜·수출 확대",
    ),
    (
        {"두산에너빌리티", "한전기술", "한전KPS", "한국전력"},
        "원전·전력",
        "정부 원전정책·전력 수요",
    ),
    (
        {"셀트리온", "삼성바이오로직스", "유한양행", "SK바이오팜", "한미약품"},
        "바이오·제약",
        "신약개발·바이오시밀러",
    ),
)


def request(session: requests.Session, url: str, **kwargs: object) -> requests.Response:
    try:
        response = session.get(url, headers=HEADERS, timeout=15, **kwargs)
        response.raise_for_status()
        return response
    except requests.RequestException as error:
        raise StrongIndexError(f"네이버증권에 연결하지 못했습니다: {error}") from error


def fetch_kospi_stocks(session: requests.Session, pause: float) -> list[Stock]:
    """네이버 KOSPI 전체 종목을 JSON API와 HTML 페이지로 보완 수집한다."""
    stocks: dict[str, Stock] = {}

    def add(code: object, name: object) -> None:
        normalized_code = str(code or "").upper().removeprefix("A")
        normalized_name = " ".join(str(name or "").split())
        if re.fullmatch(r"\d{6}", normalized_code) and normalized_name:
            stocks[normalized_code] = Stock(normalized_code, normalized_name)

    def collect_items(payload: object) -> list[dict[str, object]]:
        found: list[dict[str, object]] = []
        def visit(node: object) -> None:
            if isinstance(node, dict):
                if any(key in node for key in ("itemCode", "itemcode", "symbolCode", "code", "reutersCode")):
                    found.append(node)
                for value in node.values():
                    visit(value)
            elif isinstance(node, list):
                for value in node:
                    visit(value)
        visit(payload)
        return found

    for page in range(1, 51):
        try:
            response = request(session, NAVER_STOCK_LIST_API, params={"page": page, "pageSize": 100})
        except StrongIndexError as error:
            print(f"코스피 JSON 목록 API 건너뜀: {error}", flush=True)
            break
        try:
            payload = response.json()
        except ValueError as error:
            raise StrongIndexError("네이버증권 종목 목록 응답을 해석하지 못했습니다.") from error
        before = len(stocks)
        for item in collect_items(payload):
            code = next((item.get(key) for key in ("itemCode", "itemcode", "symbolCode", "code", "reutersCode")), "")
            name = next((item.get(key) for key in ("itemName", "itemname", "stockName", "stockNameKr", "stockNameKor", "stockNameEng", "name") if item.get(key)), "")
            add(code, name)
        print(f"코스피 JSON 목록: {len(stocks)}개 (페이지 {page})", flush=True)
        if len(stocks) == before:
            break
        time.sleep(pause)

    for page in range(1, 31):
        try:
            response = request(session, "https://stock.naver.com/market/stock/kr/stocklist/capitalization")
        except StrongIndexError:
            break
        soup = BeautifulSoup(response.text, "html.parser")
        before = len(stocks)
        for image in soup.select("img[src*='/Stock']"):
            match = re.search(r"Stock(\d{6})\.svg", image.get("src", ""))
            if match:
                add(match.group(1), image.get("alt", "").removesuffix(" 로고"))
        print(f"코스피 HTML 목록: {len(stocks)}개 (페이지 {page})", flush=True)
        if len(stocks) == before:
            break
        time.sleep(pause)

    if len(stocks) < 20:
        raise StrongIndexError(f"네이버증권 코스피 종목 목록을 충분히 읽지 못했습니다(수집: {len(stocks)}개).")
    print(f"코스피 종목 목록 최종 수집: {len(stocks)}개", flush=True)
    return list(stocks.values())

def parse_price_volume_rows(payload: str) -> dict[date, tuple[float, float]]:
    """네이버의 자바스크립트 배열 형식 시세를 날짜:(종가, 거래량)으로 바꾼다."""
    text = payload.strip().rstrip(";")
    try:
        rows = ast.literal_eval(text)
    except (SyntaxError, ValueError) as error:
        raise StrongIndexError("네이버 시세 데이터 형식을 해석하지 못했습니다.") from error

    records: dict[date, tuple[float, float]] = {}
    for row in rows[1:]:  # 첫 행은 ['날짜', '시가', '고가', '저가', '종가', '거래량'] 헤더
        if len(row) < 6:
            continue
        try:
            date_text = re.sub(r"\D", "", str(row[0]))
            if len(date_text) != 8:
                continue
            day = date(int(date_text[:4]), int(date_text[4:6]), int(date_text[6:]))
            # 지수는 소수점 종가, 개별 종목은 정수 종가로 내려올 수 있다.
            close = float(str(row[4]).replace(",", ""))
            volume = float(str(row[5]).replace(",", ""))
        except (TypeError, ValueError):
            continue
        if close > 0 and volume >= 0:
            records[day] = (close, volume)
    return records


def parse_price_rows(payload: str) -> dict[date, float]:
    return {day: close for day, (close, _) in parse_price_volume_rows(payload).items()}


def fetch_naver_chart_rows(session: requests.Session, symbol: str, start: date, end: date) -> dict[date, tuple[float, float]]:
    """개편된 네이버 일봉 API에서 종가와 거래량을 읽는다."""
    kind = "index" if symbol in {KOSPI_SYMBOL, KOSDAQ_SYMBOL} else "item"
    response = request(
        session,
        f"{NAVER_CHART_API}/{kind}/{symbol}",
        params={"periodType": "dayCandle"},
    )
    try:
        payload = response.json()
    except ValueError as error:
        raise StrongIndexError("네이버 일봉 시세 응답을 해석하지 못했습니다.") from error
    rows = payload.get("priceInfos", []) if isinstance(payload, dict) else []
    records: dict[date, tuple[float, float]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        date_text = re.sub(r"\\D", "", str(row.get("localDate", "")))
        if len(date_text) != 8:
            continue
        try:
            day = date(int(date_text[:4]), int(date_text[4:6]), int(date_text[6:]))
            close = float(str(row.get("closePrice", "")).replace(",", ""))
            volume = float(str(row.get("accumulatedTradingVolume", 0)).replace(",", ""))
        except (TypeError, ValueError):
            continue
        if close > 0:
            records[day] = (close, volume)
    if len(records) < 120:
        # 새 차트 API의 최신 구간에 과거 구간 API를 합쳐 120일 분석 창을 확보한다.
        try:
            legacy = request(
                session,
                PRICE_API,
                params={
                    "symbol": symbol,
                    "requestType": "1",
                    "startTime": start.strftime("%Y%m%d"),
                    "endTime": end.strftime("%Y%m%d"),
                    "timeframe": "day",
                },
            )
            records.update(parse_price_volume_rows(legacy.text))
        except StrongIndexError:
            pass
    if not records:
        raise StrongIndexError(f"네이버 {symbol} 일봉 시세가 비어 있습니다.")
    return records



def toss_access_token(session: requests.Session) -> str:
    client_id = os.getenv("TOSS_CLIENT_ID", "").strip()
    client_secret = os.getenv("TOSS_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise StrongIndexError("Toss Open API 인증 정보가 없습니다.")
    try:
        response = session.post(
            "https://openapi.tossinvest.com/oauth2/token",
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
            },
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as error:
        raise StrongIndexError(f"토스증권 API 인증에 실패했습니다: {error}") from error
    token = str(payload.get("access_token", ""))
    if not token:
        raise StrongIndexError("토스증권 API 인증 토큰을 받지 못했습니다.")
    return token


def fetch_toss_chart_rows(session: requests.Session, symbol: str) -> dict[date, tuple[float, float]]:
    token = toss_access_token(session)
    if symbol in {KOSPI_SYMBOL, KOSDAQ_SYMBOL}:
        url = f"https://openapi.tossinvest.com/api/v1/market-indicators/{symbol}/candles"
        params = {"interval": "1d", "count": 200}
    else:
        url = "https://openapi.tossinvest.com/api/v1/candles"
        params = {"symbol": symbol, "interval": "1d", "count": 200}
    try:
        response = session.get(
            url,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            params=params,
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as error:
        raise StrongIndexError(f"토스증권 {symbol} 일봉 시세를 읽지 못했습니다: {error}") from error
    result = payload.get("result", {}) if isinstance(payload, dict) else {}
    candles = result.get("candles", []) if isinstance(result, dict) else []
    records: dict[date, tuple[float, float]] = {}
    for candle in candles:
        if not isinstance(candle, dict):
            continue
        date_text = str(candle.get("timestamp", ""))[:10].replace("-", "")
        if len(date_text) != 8:
            continue
        try:
            day = date(int(date_text[:4]), int(date_text[4:6]), int(date_text[6:]))
            close = float(str(candle.get("closePrice", "")).replace(",", ""))
            volume = float(str(candle.get("volume", 0)).replace(",", ""))
        except (TypeError, ValueError):
            continue
        if close > 0:
            records[day] = (close, volume)
    if len(records) < 120:
        raise StrongIndexError(f"토스증권 {symbol} 일봉 데이터가 120일 미만입니다.")
    return records


def fetch_chart_rows(session: requests.Session, symbol: str, start: date, end: date) -> dict[date, tuple[float, float]]:
    if os.getenv("TOSS_CLIENT_ID") and os.getenv("TOSS_CLIENT_SECRET"):
        return fetch_toss_chart_rows(session, symbol)
    return fetch_naver_chart_rows(session, symbol, start, end)

def fetch_prices(session: requests.Session, symbol: str, start: date, end: date) -> dict[date, float]:
    return {day: close for day, (close, _) in fetch_chart_rows(session, symbol, start, end).items()}


def fetch_price_volumes(session: requests.Session, symbol: str, start: date, end: date) -> dict[date, tuple[float, float]]:
    return fetch_chart_rows(session, symbol, start, end)

def naver_industry(session: requests.Session, stock: Stock) -> str:
    """분류 규칙에 없는 종목에 쓸 네이버증권의 업종명을 찾는다."""
    response = request(session, f"{NAVER_FINANCE}/item/main.naver", params={"code": stock.code})
    soup = BeautifulSoup(response.text, "html.parser")
    # 현재 네이버 상세 페이지는 '(업종명 : 전자장비와기기 ｜ ...)' 형식으로 표시한다.
    for industry_element in soup.find_all("em"):
        industry_text = industry_element.get_text(" ", strip=True)
        matched = re.search(r"업종명\s*:\s*([^｜|)]+)", industry_text)
        if matched and matched.group(1).strip():
            return matched.group(1).strip()

    # 이전 화면 구조도 지원한다.
    for heading in soup.find_all(["th", "dt"]):
        # '업종 PER'도 함께 있으므로 부분 일치가 아니라 업종 필드만 정확히 고른다.
        if heading.get_text(" ", strip=True) != "업종":
            continue
        value = heading.find_next_sibling(["td", "dd"])
        if value:
            industry = " ".join(value.get_text(" ", strip=True).split())
            if industry:
                return industry
    return "기타"


def naver_market_cap(session: requests.Session, stock: Stock) -> int:
    """네이버증권 종목 상세 화면의 시가총액(억원)을 읽는다."""
    response = request(session, f"{NAVER_FINANCE}/item/main.naver", params={"code": stock.code})
    soup = BeautifulSoup(response.text, "html.parser")
    for heading in soup.find_all("th"):
        if heading.get_text(" ", strip=True) != "시가총액(억)":
            continue
        value = heading.find_next_sibling("td")
        if value:
            digits = re.sub(r"\D", "", value.get_text(" ", strip=True))
            if digits:
                return int(digits)
    raise StrongIndexError(f"{stock.name}의 시가총액 정보를 읽지 못했습니다.")


def naver_theme_memberships(
    session: requests.Session,
    stocks: list[Stock],
    pause: float,
) -> dict[str, list[str]]:
    """Read Naver's theme pages and return up to three themes for target stocks."""
    target_codes = {stock.code for stock in stocks}
    if THEME_MASTER_CACHE_FILE.exists():
        try:
            cached = json.loads(THEME_MASTER_CACHE_FILE.read_text(encoding="utf-8"))
            memberships = cached.get("memberships", {})
            if isinstance(memberships, dict):
                return {
                    code: list(memberships.get(code, []))[:THEME_DISPLAY_LIMIT]
                    for code in target_codes
                }
        except (json.JSONDecodeError, OSError, TypeError):
            pass

    theme_links: list[tuple[str, str]] = []
    first = request(session, f"{NAVER_FINANCE}/sise/theme.naver", params={"page": 1})
    first_soup = BeautifulSoup(first.text, "html.parser")
    pages = [
        int(match)
        for link in first_soup.select("a[href*='theme.naver'][href*='page=']")
        for match in re.findall(r"page=(\d+)", link.get("href", ""))
    ]
    last_page = max(pages, default=1)
    listing_soups = [first_soup]
    for page in range(2, last_page + 1):
        response = request(session, f"{NAVER_FINANCE}/sise/theme.naver", params={"page": page})
        listing_soups.append(BeautifulSoup(response.text, "html.parser"))
        time.sleep(pause)

    seen_theme_numbers: set[str] = set()
    for soup in listing_soups:
        for link in soup.select("a[href*='sise_group_detail.naver?type=theme']"):
            theme_name = link.get_text(" ", strip=True)
            href = link.get("href", "")
            number = parse_qs(urlparse(href).query).get("no", [""])[0]
            if theme_name and number and number not in seen_theme_numbers:
                seen_theme_numbers.add(number)
                theme_links.append((theme_name, href))

    memberships: dict[str, list[str]] = {}
    for number, (theme_name, href) in enumerate(theme_links, start=1):
        print(f"테마 편입종목 확인 중: {number}/{len(theme_links)} {theme_name}", end="\r", flush=True)
        try:
            response = request(session, f"{NAVER_FINANCE}{href}")
        except StrongIndexError:
            time.sleep(pause)
            continue
        soup = BeautifulSoup(response.text, "html.parser")
        for link in soup.select("a[href*='item/main.naver?code=']"):
            code = parse_qs(urlparse(link.get("href", "")).query).get("code", [""])[0]
            if not re.fullmatch(r"\d{6}", code):
                continue
            themes = memberships.setdefault(code, [])
            if theme_name not in themes and len(themes) < THEME_DISPLAY_LIMIT:
                themes.append(theme_name)
        time.sleep(pause)
    print(" " * 100, end="\r")
    THEME_MASTER_CACHE_FILE.write_text(
        json.dumps({"memberships": memberships}, ensure_ascii=False), encoding="utf-8"
    )
    return {code: memberships.get(code, []) for code in target_codes}


def naver_themes_for_results(
    session: requests.Session,
    results: list[Result],
    pause: float,
) -> list[Result]:
    """Replace generic themes with Naver Finance theme memberships when available."""
    memberships = naver_theme_memberships(session, [item.stock for item in results], pause)
    return [
        replace(item, theme=" / ".join(memberships[item.stock.code]) or item.theme)
        for item in results
    ]


def naver_industry_memberships(
    session: requests.Session,
    stocks: list[Stock],
    pause: float,
) -> dict[str, str]:
    """Read Naver's 업종별 시세 groups and return each target's industry."""
    target_codes = {stock.code for stock in stocks}
    if INDUSTRY_MASTER_CACHE_FILE.exists():
        try:
            cached = json.loads(INDUSTRY_MASTER_CACHE_FILE.read_text(encoding="utf-8"))
            memberships = cached.get("memberships", {})
            if isinstance(memberships, dict):
                return {code: str(memberships.get(code, "")) for code in target_codes}
        except (json.JSONDecodeError, OSError, TypeError):
            pass

    response = request(session, f"{NAVER_FINANCE}/sise/sise_group.naver", params={"type": "upjong"})
    listing_soup = BeautifulSoup(response.text, "html.parser")
    industry_links: list[tuple[str, str]] = []
    seen_numbers: set[str] = set()
    for link in listing_soup.select("a[href*='sise_group_detail.naver?type=upjong']"):
        industry_name = link.get_text(" ", strip=True)
        href = link.get("href", "")
        number = parse_qs(urlparse(href).query).get("no", [""])[0]
        if industry_name and number and number not in seen_numbers:
            seen_numbers.add(number)
            industry_links.append((industry_name, href))

    memberships: dict[str, str] = {}
    for number, (industry_name, href) in enumerate(industry_links, start=1):
        print(f"Checking Naver industry members {number}/{len(industry_links)} {industry_name}", end="\r", flush=True)
        try:
            detail = request(session, f"{NAVER_FINANCE}{href}")
        except StrongIndexError:
            time.sleep(pause)
            continue
        soup = BeautifulSoup(detail.text, "html.parser")
        for link in soup.select("a[href*='item/main.naver?code=']"):
            code = parse_qs(urlparse(link.get("href", "")).query).get("code", [""])[0]
            if re.fullmatch(r"\d{6}", code):
                memberships.setdefault(code, industry_name)
        time.sleep(pause)
    print(" " * 100, end="\r")
    INDUSTRY_MASTER_CACHE_FILE.write_text(
        json.dumps({"memberships": memberships}, ensure_ascii=False), encoding="utf-8"
    )
    return {code: memberships.get(code, "") for code in target_codes}


def naver_industries_for_results(
    session: requests.Session,
    results: list[Result],
    pause: float,
) -> list[Result]:
    """Replace local classifications with Naver Finance 업종별 시세 classifications."""
    memberships = naver_industry_memberships(session, [item.stock for item in results], pause)
    return [
        replace(item, industry=memberships[item.stock.code] or item.industry)
        for item in results
    ]


def refresh_saved_themes(session: requests.Session, pause: float) -> int:
    """Update themes in all accumulated daily rows without recalculating the screen."""
    if not HISTORY_FILE.exists():
        return 0
    with HISTORY_FILE.open("r", encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    stocks = {
        row.get("code", ""): Stock(row.get("code", ""), row.get("name", ""))
        for row in rows
        if re.fullmatch(r"\d{6}", row.get("code", "")) and row.get("name", "")
    }
    memberships = naver_theme_memberships(session, list(stocks.values()), pause)
    updated = 0
    for row in rows:
        themes = memberships.get(row.get("code", ""), [])
        if themes:
            value = " / ".join(themes)
            if row.get("core_theme") != value:
                row["core_theme"] = value
                updated += 1
    with HISTORY_FILE.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows({field: row.get(field, "") for field in CSV_FIELDS} for row in rows)
    return updated


def refresh_saved_industries(session: requests.Session, pause: float) -> int:
    """Update industries in all accumulated daily rows from Naver 업종별 시세."""
    if not HISTORY_FILE.exists():
        return 0
    with HISTORY_FILE.open("r", encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    stocks = {
        row.get("code", ""): Stock(row.get("code", ""), row.get("name", ""))
        for row in rows
        if re.fullmatch(r"\d{6}", row.get("code", "")) and row.get("name", "")
    }
    memberships = naver_industry_memberships(session, list(stocks.values()), pause)
    updated = 0
    for row in rows:
        value = memberships.get(row.get("code", ""), "")
        if value and row.get("industry") != value:
            row["industry"] = value
            updated += 1
    with HISTORY_FILE.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows({field: row.get(field, "") for field in CSV_FIELDS} for row in rows)
    return updated


def classify_stock(session: requests.Session, stock: Stock) -> tuple[str, str]:
    matched = [(industry, theme) for names, industry, theme in THEME_RULES if stock.name in names]
    if matched:
        industries = " · ".join(dict.fromkeys(industry for industry, _ in matched))
        themes = " · ".join(dict.fromkeys(theme for _, theme in matched))
        return industries, themes
    try:
        return naver_industry(session, stock), "개별 테마 확인 필요"
    except StrongIndexError:
        # 개별 종목 페이지 하나의 실패가 전체 200종목 분석을 중단시키지 않도록 한다.
        return "기타", "개별 테마 확인 필요"


def fetch_etfs(session: requests.Session) -> list[Etf]:
    """네이버증권 ETF 목록 API에서 국내 ETF 전체를 읽는다."""
    response = request(session, f"{NAVER_FINANCE}/api/sise/etfItemList.nhn")
    try:
        items = response.json()["result"]["etfItemList"]
    except (ValueError, KeyError, TypeError) as error:
        raise StrongIndexError("네이버증권 ETF 목록 응답을 해석하지 못했습니다.") from error
    etfs = {
        str(item.get("itemcode", "")): Etf(
            str(item.get("itemcode", "")),
            str(item.get("itemname", "")).strip(),
            int(item.get("marketSum", 0) or 0),
        )
        for item in items
        if re.fullmatch(r"\d{6}", str(item.get("itemcode", ""))) and str(item.get("itemname", "")).strip()
    }
    if not etfs:
        raise StrongIndexError("ETF 목록을 읽지 못했습니다. 네이버증권의 ETF 페이지 구조를 확인해 주세요.")
    return list(etfs.values())


def fetch_top_holdings(session: requests.Session, etf: Etf) -> list[dict[str, object]]:
    """ETF 상세 화면에 공개된 구성비중 상위 종목을 비중순으로 읽는다."""
    response = request(session, f"{NAVER_FINANCE}/item/main.naver", params={"code": etf.code})
    soup = BeautifulSoup(response.text, "html.parser")
    table = next(
        (
            item
            for item in soup.find_all("table")
            if any("구성종목" in heading.get_text(" ", strip=True) for heading in item.find_all("th"))
        ),
        None,
    )
    if table is None:
        return []

    holdings: list[dict[str, object]] = []
    for row in table.select("tr"):
        link = row.select_one("a[href*='item/main.naver?code=']")
        if not link:
            continue
        code = parse_qs(urlparse(link.get("href", "")).query).get("code", [""])[0]
        cells = row.select("td")
        if not re.fullmatch(r"\d{6}", code) or len(cells) < 3:
            continue
        matched = re.search(r"([\d.]+)%", cells[2].get_text(" ", strip=True))
        if not matched:
            continue
        holdings.append(
            {
                "stock_code": code,
                "weight": float(matched.group(1)),
                "rank": len(holdings) + 1,
            }
        )
    return holdings


def etf_holdings_cache_path(run_date: str) -> Path:
    return OUTPUT_DIR / f"etf_top_holdings_{run_date}.json"


def find_etf_candidates(
    session: requests.Session,
    stocks: list[Stock],
    run_date: str,
    pause: float,
) -> dict[str, list[dict[str, object]]]:
    """종목이 편입된 ETF를 찾아 ETF 규모 순으로 고를 수 있게 하루 동안 캐시한다."""
    OUTPUT_DIR.mkdir(exist_ok=True)
    cache_path = etf_holdings_cache_path(run_date)
    target_codes = {stock.code for stock in stocks}
    matches: dict[str, list[dict[str, object]]] = {code: [] for code in target_codes}

    if cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if (
                cached.get("run_date") == run_date
                and cached.get("holdings_cache_version") == ETF_HOLDINGS_CACHE_VERSION
                and set(cached.get("target_codes", [])) == target_codes
            ):
                cached_matches = cached.get("matches", {})
                if not all(
                    "market_cap" in item
                    for cached_items in cached_matches.values()
                    for item in cached_items
                ):
                    market_caps = {etf.code: etf.market_cap for etf in fetch_etfs(session)}
                    for cached_items in cached_matches.values():
                        for item in cached_items:
                            item["market_cap"] = market_caps.get(str(item.get("etf_code", "")), 0)
                    cached["matches"] = cached_matches
                    cache_path.write_text(json.dumps(cached, ensure_ascii=False), encoding="utf-8")
                return {code: cached_matches.get(code, []) for code in target_codes}
        except (json.JSONDecodeError, OSError):
            pass

    etfs = fetch_etfs(session)
    etfs_by_code = {etf.code: etf for etf in etfs}
    if ETF_MASTER_CACHE_FILE.exists():
        try:
            master = json.loads(ETF_MASTER_CACHE_FILE.read_text(encoding="utf-8"))
            if master.get("holdings_cache_version") == ETF_HOLDINGS_CACHE_VERSION:
                for etf_code, holdings in master.get("holdings", {}).items():
                    etf = etfs_by_code.get(etf_code)
                    if not etf:
                        continue
                    for holding in holdings:
                        stock_code = str(holding.get("stock_code", ""))
                        if stock_code in matches:
                            matches[stock_code].append(
                                {
                                    "etf_code": etf.code,
                                    "etf_name": etf.name,
                                    "market_cap": etf.market_cap,
                                    "rank": holding["rank"],
                                    "weight": holding["weight"],
                                }
                            )
                cache_path.write_text(
                    json.dumps(
                        {
                            "run_date": run_date,
                            "holdings_cache_version": ETF_HOLDINGS_CACHE_VERSION,
                            "target_codes": sorted(target_codes),
                            "matches": matches,
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                return matches
        except (json.JSONDecodeError, OSError, KeyError, TypeError):
            pass

    master_holdings: dict[str, list[dict[str, object]]] = {}
    for number, etf in enumerate(etfs, start=1):
        print(f"ETF 편입비중 확인 중: {number}/{len(etfs)} {etf.name}", end="\r", flush=True)
        try:
            holdings = fetch_top_holdings(session, etf)
        except StrongIndexError:
            time.sleep(pause)
            continue
        master_holdings[etf.code] = holdings
        for holding in holdings:
            stock_code = str(holding["stock_code"])
            if stock_code in matches:
                matches[stock_code].append(
                    {
                        "etf_code": etf.code,
                        "etf_name": etf.name,
                        "market_cap": etf.market_cap,
                        "rank": holding["rank"],
                        "weight": holding["weight"],
                    }
                )
        time.sleep(pause)
    print(" " * 100, end="\r")
    ETF_MASTER_CACHE_FILE.write_text(
        json.dumps(
            {"holdings_cache_version": ETF_HOLDINGS_CACHE_VERSION, "holdings": master_holdings},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    cache_path.write_text(
        json.dumps(
            {
                "run_date": run_date,
                "holdings_cache_version": ETF_HOLDINGS_CACHE_VERSION,
                "target_codes": sorted(target_codes),
                "matches": matches,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return matches


def etf_trend_labels(
    session: requests.Session,
    candidates: dict[str, list[dict[str, object]]],
    start: date,
    end: date,
    pause: float,
) -> dict[str, tuple[str, str, str]]:
    """규모 상위 ETF 3개의 20일선 통과 수·편입 상태·상세를 만든다."""
    unique_etfs = {
        str(item["etf_code"]): (str(item["etf_name"]), str(item["etf_code"]))
        for items in candidates.values()
        for item in items
    }
    trend_gaps: dict[str, float | None] = {}
    for number, (code, _) in enumerate(unique_etfs.items(), start=1):
        print(f"ETF 추세 확인 중: {number}/{len(unique_etfs)}", end="\r", flush=True)
        try:
            prices = fetch_prices(session, code, start, end)
            days = sorted(prices)
            if len(days) >= 20:
                ma20 = sum(prices[day] for day in days[-20:]) / 20
                gap = (prices[days[-1]] / ma20 - 1) * 100
                trend_gaps[code] = gap
        except StrongIndexError:
            pass
        time.sleep(pause)
    print(" " * 100, end="\r")

    labels: dict[str, tuple[str, str, str]] = {}
    for stock_code, items in candidates.items():
        selected_items = sorted(
            items,
            key=lambda item: int(item.get("market_cap", 0) or 0),
            reverse=True,
        )[:ETF_DISPLAY_LIMIT]
        pass_count = sum(
            abs(gap) <= 10
            for item in selected_items
            if (gap := trend_gaps.get(str(item["etf_code"]))) is not None
        )
        details = [
            f"{item['etf_name']} ({'편입상위' if int(item['rank']) <= 10 else '편입'}, "
            f"비중 {float(item['weight']):.2f}%, "
            f"20일선 {trend_gaps[str(item['etf_code'])]:+.2f}%)"
            if trend_gaps.get(str(item["etf_code"])) is not None
            else f"{item['etf_name']} ({'편입상위' if int(item['rank']) <= 10 else '편입'}, 비중 {float(item['weight']):.2f}%, 20일선 미확인)"
            for item in selected_items
        ]
        names = [
            f"{item['etf_name']} · {'편입상위' if int(item['rank']) <= 10 else '편입'}"
            for item in selected_items
        ]
        labels[stock_code] = (f"{pass_count}개통과", "\n".join(names), "\n".join(details))
    return labels


def calculate_results(
    session: requests.Session,
    stocks: list[Stock],
    benchmark: dict[date, int],
    lookback_days: int,
    min_rs: float,
    min_market_cap: int,
    ma20_gap_limit: float,
    start: date,
    end: date,
    pause: float,
) -> list[Result]:
    results: list[Result] = []
    for number, stock in enumerate(stocks, start=1):
        print(f"시세 분석 중: {number}/{len(stocks)} {stock.name}", end="\r", flush=True)
        try:
            price_volumes = fetch_price_volumes(session, stock.code, start, end)
        except StrongIndexError:
            time.sleep(pause)
            continue

        prices = {day: close for day, (close, _) in price_volumes.items()}
        volumes = {day: volume for day, (_, volume) in price_volumes.items()}
        common_days = sorted(set(prices) & set(benchmark))
        required_days = max(lookback_days, 120)
        if len(common_days) < required_days:
            time.sleep(pause)
            continue
        period = common_days[-lookback_days:]
        first_day, last_day = period[0], period[-1]
        stock_return = (prices[last_day] / prices[first_day] - 1) * 100
        kospi_return = (benchmark[last_day] / benchmark[first_day] - 1) * 100
        rs_index = (prices[last_day] / prices[first_day]) / (benchmark[last_day] / benchmark[first_day]) * 100
        ma_days = common_days[-120:]
        ma20 = sum(prices[day] for day in ma_days[-20:]) / 20
        ma120 = sum(prices[day] for day in ma_days) / 120
        ma20_gap = (prices[last_day] / ma20 - 1) * 100
        # 최근 5거래일과 겹치지 않는 직전 55거래일을 비교한다.
        # 두 구간을 합쳐 총 60거래일(분기 수준)의 거래량을 사용한다.
        volume_days = common_days[-60:]
        avg_volume_55 = sum(volumes[day] for day in volume_days[:-5]) / 55
        avg_volume_10 = sum(volumes[day] for day in volume_days[-10:]) / 10
        volume_change = (avg_volume_10 / avg_volume_55 - 1) * 100 if avg_volume_55 else 0.0
        avg_volume_5 = sum(volumes[day] for day in volume_days[-5:]) / 5
        price_change_5d = (prices[last_day] / prices[common_days[-6]] - 1) * 100
        volatility_contraction = (
            abs(price_change_5d) <= 5
            and avg_volume_55 >= avg_volume_5 * 2
        )
        # 종가가 120일선 위에 있고, 20일선과의 괴리율이 설정 범위 안인 종목만 남긴다.
        meets_ma_condition = prices[last_day] > ma120 and abs(ma20_gap) <= ma20_gap_limit
        if rs_index > min_rs and meets_ma_condition:
            try:
                market_cap = naver_market_cap(session, stock)
            except StrongIndexError:
                time.sleep(pause)
                continue
            if market_cap < min_market_cap:
                time.sleep(pause)
                continue
            industry, theme = classify_stock(session, stock)
            results.append(
                Result(
                    stock,
                    prices[last_day],
                    market_cap,
                    stock_return,
                    kospi_return,
                    rs_index,
                    ma20,
                    ma20_gap,
                    ma120,
                    avg_volume_55,
                    avg_volume_10,
                    volume_change,
                    volatility_contraction,
                    price_change_5d,
                    industry,
                    theme,
                )
            )
        time.sleep(pause)
    print(" " * 80, end="\r")
    return sorted(results, key=lambda item: item.rs_index, reverse=True)


def save_history(results: list[Result], run_date: str) -> int:
    OUTPUT_DIR.mkdir(exist_ok=True)
    old_rows: list[dict[str, str]] = []
    if HISTORY_FILE.exists():
        with HISTORY_FILE.open("r", encoding="utf-8-sig", newline="") as file:
            old_rows = list(csv.DictReader(file))
    seen = {(row.get("run_date", ""), row.get("code", "")) for row in old_rows}
    new_rows: list[dict[str, str]] = []
    for item in results:
        key = (run_date, item.stock.code)
        new_rows.append(
            {
                "run_date": run_date,
                "code": item.stock.code,
                "name": item.stock.name,
                "close": f"{item.close:g}",
                "market_cap_억원": f"{item.market_cap}",
                "stock_return_pct": f"{item.stock_return:.2f}",
                "kospi_return_pct": f"{item.kospi_return:.2f}",
                "rs_index": f"{item.rs_index:.2f}",
                "ma20": f"{item.ma20:.2f}",
                "ma20_gap_pct": f"{item.ma20_gap:.2f}",
                "volatility_contraction": "O" if item.volatility_contraction else "X",
                "price_change_5d_pct": f"{item.price_change_5d:+.2f}",
                "ma120": f"{item.ma120:.2f}",
                "avg_volume_55": f"{item.avg_volume_55:.0f}",
                "avg_volume_10": f"{item.avg_volume_10:.0f}",
                "volume_change_pct": f"{item.volume_change_pct:+.2f}",
                "industry": item.industry,
                "core_theme": item.theme,
                "etf_trend_good": item.etf_trend_good,
                "etf_names": item.etf_names,
                "etf_details": item.etf_details,
                "source_url": f"{NAVER_FINANCE}/item/main.naver?code={item.stock.code}",
            }
        )

    # 같은 날짜에 다시 실행하면 기존 행을 갱신한다. 다른 날짜의 누적 기록은 그대로 보존한다.
    history = [
        {field: row.get(field, "") for field in CSV_FIELDS}
        for row in old_rows
        if row.get("run_date", "") != run_date
    ]
    history.extend(new_rows)
    with HISTORY_FILE.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(history)
    return sum(1 for row in new_rows if (row["run_date"], row["code"]) not in seen)


def make_index_snapshot(index_name: str, prices: dict[date, int]) -> dict[str, str]:
    """Create one end-of-day index record with its 20-day moving-average gap."""
    days = sorted(prices)
    if len(days) < 20:
        raise StrongIndexError(f"{index_name} 지수의 20일 이동평균을 계산할 데이터가 부족합니다.")
    ma20 = sum(prices[day] for day in days[-20:]) / 20
    close = prices[days[-1]]
    return {
        "run_date": days[-1].isoformat(),
        "index_name": index_name,
        "close": f"{close:g}",
        "ma20": f"{ma20:.2f}",
        "ma20_gap_pct": f"{(close / ma20 - 1) * 100:.2f}",
    }


def save_index_snapshots(snapshots: list[dict[str, str]], run_date: str) -> None:
    """Replace a day's index records while preserving all other daily snapshots."""
    OUTPUT_DIR.mkdir(exist_ok=True)
    history: list[dict[str, str]] = []
    if INDEX_HISTORY_FILE.exists():
        with INDEX_HISTORY_FILE.open("r", encoding="utf-8-sig", newline="") as file:
            history = list(csv.DictReader(file))
    history = [row for row in history if row.get("run_date") != run_date]
    history.extend(snapshots)
    with INDEX_HISTORY_FILE.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=INDEX_CSV_FIELDS)
        writer.writeheader()
        writer.writerows(
            {field: row.get(field, "") for field in INDEX_CSV_FIELDS} for row in history
        )


def print_results(results: list[Result]) -> None:
    print("순위  종목명              RS지수    시가총액(억)  20일선 괴리율  거래량변화율   산업군                         ETF추세양호  ETF명")
    print("-" * 172)
    for rank, item in enumerate(results, start=1):
        print(
            f"{rank:>2}   {item.stock.name:<15} {item.rs_index:>6.2f}  {item.market_cap:>10,}  "
            f"{item.ma20_gap:>+8.2f}%  {item.volume_change_pct:>+8.2f}%  "
            f"{item.industry:<28} {item.etf_trend_good:<7}  {item.etf_names or '-'}"
        )


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="코스피 전체 종목의 코스피 대비 RS 강도를 계산합니다.")
    parser.add_argument("--lookback-days", type=int, default=120, help="RS 계산에 사용할 거래일 수 (기본: 120)")
    parser.add_argument("--min-rs", type=float, default=80.0, help="추출 기준 RS 지수, 초과 종목만 저장 (기본: 80)")
    parser.add_argument("--min-market-cap", type=int, default=5000, help="최소 시가총액(억원, 기본: 5000)")
    parser.add_argument("--ma20-gap", type=float, default=10.0, help="20일선 허용 괴리율(±%%, 기본: 10)")
    parser.add_argument("--pause", type=float, default=0.12, help="네이버 요청 사이 대기 시간(초, 기본: 0.12)")
    parser.add_argument("--skip-etf-check", action="store_true", help="ETF 편입·추세 확인을 건너뜁니다")
    parser.add_argument(
        "--refresh-themes",
        action="store_true",
        help="누적 CSV의 테마를 네이버증권 테마별 시세 기준으로 갱신합니다",
    )
    parser.add_argument(
        "--refresh-industries",
        action="store_true",
        help="누적 CSV의 산업군을 네이버증권 업종별 시세 기준으로 갱신합니다",
    )
    parser.add_argument("--dry-run", action="store_true", help="수집 결과를 저장하지 않고 화면에만 표시합니다")
    parser.add_argument("--as-of", type=date.fromisoformat, help="기준일 YYYY-MM-DD (과거 거래일 재분석용)")
    args = parser.parse_args()
    if args.lookback_days < 20:
        parser.error("--lookback-days는 20 이상이어야 합니다.")
    if args.pause < 0.1:
        parser.error("네이버 서버 보호를 위해 --pause는 0.1 이상이어야 합니다.")
    if args.ma20_gap < 0:
        parser.error("--ma20-gap은 0 이상이어야 합니다.")
    if args.min_market_cap < 0:
        parser.error("--min-market-cap은 0 이상이어야 합니다.")
    return args


def main() -> int:
    args = parse_arguments()
    if args.refresh_themes:
        try:
            with requests.Session() as session:
                updated = refresh_saved_themes(session, args.pause)
            print(f"Updated themes in {updated} accumulated rows.")
            return 0
        except StrongIndexError as error:
            print(f"Error: {error}", file=sys.stderr)
            return 1
    if args.refresh_industries:
        try:
            with requests.Session() as session:
                updated = refresh_saved_industries(session, args.pause)
            print(f"Updated industries in {updated} accumulated rows.")
            return 0
        except StrongIndexError as error:
            print(f"Error: {error}", file=sys.stderr)
            return 1
    # 휴장일을 고려해 거래일 수보다 넉넉하게 과거 데이터를 요청한다.
    end = args.as_of or date.today()
    start = end - timedelta(days=max(args.lookback_days, 120) * 2 + 30)
    try:
        with requests.Session() as session:
            print("네이버증권에서 코스피 전체 종목을 읽는 중입니다...")
            stocks = fetch_kospi_stocks(session, args.pause)
            benchmark = fetch_prices(session, KOSPI_SYMBOL, start, end)
            kosdaq = fetch_prices(session, KOSDAQ_SYMBOL, start, end)
            if len(benchmark) < max(args.lookback_days, 120):
                raise StrongIndexError("코스피 지수 시세가 충분하지 않아 RS를 계산할 수 없습니다.")
            if len(kosdaq) < 20:
                raise StrongIndexError("KOSDAQ index history is insufficient for its 20-day average.")
            market_day = max(benchmark)
            if market_day != end:
                print(f"{end.isoformat()}은 정규장 거래일이 아니므로 최근 거래일({market_day.isoformat()}) 기준으로 저장합니다.")
                end = market_day
            run_date = market_day.isoformat()
            index_snapshots = [
                make_index_snapshot(KOSPI_SYMBOL, benchmark),
                make_index_snapshot(KOSDAQ_SYMBOL, kosdaq),
            ]
            results = calculate_results(
                session,
                stocks,
                benchmark,
                args.lookback_days,
                args.min_rs,
                args.min_market_cap,
                args.ma20_gap,
                start,
                end,
                args.pause,
            )
            if results:
                results = naver_themes_for_results(session, results, args.pause)
                results = naver_industries_for_results(session, results, args.pause)
            if results and not args.skip_etf_check:
                candidates = find_etf_candidates(session, [item.stock for item in results], run_date, args.pause)
                labels = etf_trend_labels(session, candidates, end - timedelta(days=60), end, args.pause)
                results = [
                    replace(
                        item,
                        etf_trend_good=labels.get(item.stock.code, ("미통과", "", ""))[0],
                        etf_names=labels.get(item.stock.code, ("미통과", "", ""))[1],
                        etf_details=labels.get(item.stock.code, ("미통과", "", ""))[2],
                    )
                    for item in results
                ]
        if not results:
            if not args.dry_run:
                save_history([], run_date)
                save_index_snapshots(index_snapshots, run_date)
            print(f"RS 지수가 {args.min_rs:g}을 초과하고 시가총액이 {args.min_market_cap:,}억 원 이상인 종목이 없습니다.")
            return 0
        print_results(results)
        if args.dry_run:
            print("\n사전 분석 결과입니다. 파일에는 저장하지 않았습니다.")
            return 0
        added = save_history(results, run_date)
        save_index_snapshots(index_snapshots, run_date)
        print(f"\n강세 종목 {len(results)}건 중 신규 {added}건을 저장했습니다: {HISTORY_FILE}")
        print("참고: RS와 테마는 투자 권유가 아닌 데이터 정리용 지표입니다.")
        return 0
    except StrongIndexError as error:
        print(f"오류: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n작업을 취소했습니다.", file=sys.stderr)
        return 130


_original_re_sub = re.sub
def _fixed_re_sub(pattern, repl, string, count=0, flags=0):
    if pattern == r"\\D":
        pattern = r"\D"
    return _original_re_sub(pattern, repl, string, count, flags)
re.sub = _fixed_re_sub

if __name__ == "__main__":
    raise SystemExit(main())
