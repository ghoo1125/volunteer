#!/usr/bin/env python3
"""
台灣（台北/新北）週末志工活動爬蟲
- 環境部海岸淨灘平台（淨灘）
- 中華民國保護動物協會 APATW（動物志工）
"""

import json
import logging
import re
from datetime import datetime
from pathlib import Path

import urllib3
import requests
from bs4 import BeautifulSoup

# 台灣政府網站 SSL 憑證常有 Missing Subject Key Identifier 問題，關閉驗證
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

TARGET_COUNTIES = {"台北市", "新北市", "臺北市", "臺新北市"}
DATA_FILE = Path(__file__).parent / "data" / "events.json"

SESSION = requests.Session()
SESSION.verify = False  # 政府網站 SSL 憑證問題
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
})


# ── 工具函式 ──────────────────────────────────────────────────

def is_weekend(date_str: str) -> bool:
    """判斷日期字串（YYYY-MM-DD 或含時間）是否為週六/週日"""
    try:
        dt = datetime.fromisoformat(date_str[:10])
        return dt.weekday() in (5, 6)  # 5=Saturday, 6=Sunday
    except (ValueError, TypeError):
        return False


def weekday_label(date_str: str) -> str:
    labels = ["週一", "週二", "週三", "週四", "週五", "週六", "週日"]
    try:
        dt = datetime.fromisoformat(date_str[:10])
        return labels[dt.weekday()]
    except (ValueError, TypeError):
        return ""


def detect_group_only(text: str) -> tuple[bool, int | None]:
    """
    從活動文字偵測是否限制團體報名。
    回傳 (group_only, min_participants)
    """
    text = text or ""
    # 找最小人數
    patterns = [
        r"最少[需須]?\s*(\d+)\s*人",
        r"(\d+)\s*人以上",
        r"限\s*(\d+)\s*人以上",
        r"最低\s*(\d+)\s*人",
        r"(\d+)\s*人[起~]",
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            n = int(m.group(1))
            return (n > 5, n)

    group_keywords = ["團體", "學校", "企業", "機關", "單位包場", "專屬包場"]
    for kw in group_keywords:
        if kw in text:
            return (True, None)

    return (False, None)


# ── 來源 1：環境部海岸淨灘平台 ──────────────────────────────

BEACH_BASE = "https://ecolife2.moenv.gov.tw/BeachCleanup"
BEACH_HOME = f"{BEACH_BASE}/Home/JoinCleanUp"
BEACH_API = f"{BEACH_BASE}/Data/GetSeaCleanEventNotExpired"
BEACH_DETAIL = f"{BEACH_BASE}/Home/EventDetail"


def fetch_beach_events() -> list[dict]:
    log.info("抓取環境部淨灘平台...")
    events = []

    # 取得 CSRF token
    try:
        resp = SESSION.get(BEACH_HOME, timeout=20)
        resp.raise_for_status()
    except Exception as e:
        log.error(f"無法存取淨灘平台首頁：{e}")
        return []

    soup = BeautifulSoup(resp.text, "lxml")
    token_tag = soup.find("input", {"name": "__RequestVerificationToken"})
    if not token_tag:
        log.error("找不到 CSRF token")
        return []

    token = token_tag["value"]

    # 呼叫 API 取得所有未過期活動
    try:
        api_resp = SESSION.post(
            BEACH_API,
            data={"__RequestVerificationToken": token},
            headers={"Referer": BEACH_HOME, "X-Requested-With": "XMLHttpRequest"},
            timeout=30,
        )
        api_resp.raise_for_status()
        data = api_resp.json()
    except Exception as e:
        log.error(f"淨灘 API 失敗：{e}")
        return []

    # API 可能回傳 list 或 dict
    items = data if isinstance(data, list) else data.get("data", data.get("Data", []))

    for item in items:
        city = item.get("slcityname", item.get("city", ""))
        if not any(c in city for c in TARGET_COUNTIES):
            continue

        start = item.get("starttime", item.get("StartTime", ""))
        if not is_weekend(start):
            continue

        event_id = item.get("eventid", item.get("EventId", ""))
        detail_text = fetch_beach_detail(event_id) if event_id else ""
        group_only, min_p = detect_group_only(detail_text or item.get("eventname", ""))

        events.append({
            "id": f"beach_{event_id}",
            "type": "beach_cleanup",
            "type_label": "淨灘",
            "title": item.get("eventname", item.get("EventName", "淨灘活動")),
            "date": start[:10] if start else "",
            "day_of_week": weekday_label(start),
            "location": item.get("location", item.get("Location", city)),
            "city": city,
            "organizer": item.get("organizer", item.get("Organizer", "")),
            "group_only": group_only,
            "min_participants": min_p,
            "official_link": f"{BEACH_DETAIL}/{event_id}" if event_id else BEACH_HOME,
            "photo_url": item.get("photourl", item.get("PhotoUrl", "")),
            "source": "環境部海岸淨灘平台",
            "source_url": BEACH_HOME,
        })

    log.info(f"淨灘平台找到 {len(events)} 筆台北/新北週末活動")
    return events


def fetch_beach_detail(event_id: str) -> str:
    """抓取活動詳細頁面文字，用於偵測人數限制"""
    try:
        resp = SESSION.get(f"{BEACH_DETAIL}/{event_id}", timeout=15)
        soup = BeautifulSoup(resp.text, "lxml")
        return soup.get_text()
    except Exception:
        return ""


# ── 來源 2：中華民國保護動物協會 APATW ────────────────────────

APATW_BASE = "https://www.apatw.org"
APATW_NEWS_URL = f"{APATW_BASE}/news/term/6"
APATW_MAX_PAGES = 5


def parse_apatw_date(text: str) -> str:
    """從文字中解析日期，支援 YYYY-MM-DD、YYYY/MM/DD 格式"""
    m = re.search(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", text)
    if m:
        return f"{m.group(1)}-{m.group(2).zfill(2)}-{m.group(3).zfill(2)}"
    return ""


def fetch_apatw_detail(url: str) -> dict:
    """抓取 APATW 文章詳細頁，回傳 {date, text}"""
    try:
        resp = SESSION.get(url, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        # 嘗試找日期
        date_str = ""
        for selector in ["time", ".date", ".post-date", ".article-date", "[class*='date']"]:
            tag = soup.select_one(selector)
            if tag:
                date_str = parse_apatw_date(tag.get_text())
                if date_str:
                    break

        # 若 meta 中有日期
        if not date_str:
            for meta in soup.find_all("meta"):
                content = meta.get("content", "")
                d = parse_apatw_date(content)
                if d:
                    date_str = d
                    break

        return {
            "date": date_str,
            "text": soup.get_text(),
        }
    except Exception:
        return {"date": "", "text": ""}


def fetch_apatw_events() -> list[dict]:
    log.info("抓取中華民國保護動物協會 APATW 志工資訊...")
    events = []
    seen_ids = set()

    for page in range(APATW_MAX_PAGES):
        url = f"{APATW_NEWS_URL}?page={page}"
        try:
            resp = SESSION.get(url, timeout=20)
            resp.raise_for_status()
        except Exception as e:
            log.warning(f"APATW 第 {page} 頁無法存取：{e}")
            break

        soup = BeautifulSoup(resp.text, "lxml")

        # 找文章列表項目（常見 selector：article、.news-item、li > a 等）
        items = (
            soup.select("article")
            or soup.select(".news-list li")
            or soup.select(".views-row")
            or soup.select("li.views-row")
        )

        if not items:
            # 備用：找所有連到 /node/ 的連結
            links = soup.select("a[href*='/node/']")
            items = links

        if not items:
            log.info(f"APATW 第 {page} 頁找不到更多項目，停止翻頁")
            break

        page_has_items = False
        for item in items:
            # 取連結
            link_tag = item if item.name == "a" else item.find("a")
            if not link_tag:
                continue
            href = link_tag.get("href", "")
            if not href:
                continue
            full_url = href if href.startswith("http") else f"{APATW_BASE}{href}"

            # 避免重複
            if full_url in seen_ids:
                continue
            seen_ids.add(full_url)

            # 取標題
            title_tag = (
                item.find(["h2", "h3", "h4"])
                or item.find(class_=re.compile(r"title", re.I))
                or link_tag
            )
            title = title_tag.get_text(strip=True) if title_tag else link_tag.get_text(strip=True)
            if not title or len(title) < 2:
                continue

            # 取列表頁日期（若有）
            date_tag = item.find(["time"]) or item.find(class_=re.compile(r"date", re.I))
            list_date = parse_apatw_date(date_tag.get_text()) if date_tag else ""

            # 抓詳細頁
            detail = fetch_apatw_detail(full_url)
            date_str = detail["date"] or list_date
            group_only, min_p = detect_group_only(detail["text"] or title)

            # 生成穩定 id
            node_id = re.search(r"/node/(\d+)", full_url)
            ev_id = f"apatw_{node_id.group(1)}" if node_id else f"apatw_{len(seen_ids)}"

            events.append({
                "id": ev_id,
                "type": "animal",
                "type_label": "動物志工",
                "title": title,
                "date": date_str,
                "day_of_week": weekday_label(date_str),
                "location": "台灣（詳見活動頁）",
                "city": "台北市",
                "organizer": "中華民國保護動物協會",
                "group_only": group_only,
                "min_participants": min_p,
                "official_link": full_url,
                "photo_url": "",
                "source": "中華民國保護動物協會 APATW",
                "source_url": APATW_NEWS_URL,
            })
            page_has_items = True

        if not page_has_items:
            break

    log.info(f"APATW 找到 {len(events)} 筆動物志工活動")
    return events


# ── 主程式 ────────────────────────────────────────────────────

def load_existing() -> dict:
    """讀取現有資料，供網路失敗時保留舊資料用"""
    if DATA_FILE.exists():
        try:
            return json.loads(DATA_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def run():
    existing = load_existing()
    existing_by_source: dict[str, list] = {}
    for ev in existing.get("events", []):
        src = ev.get("source", "")
        existing_by_source.setdefault(src, []).append(ev)

    def fetch_with_fallback(fetch_fn, source_key: str) -> list[dict]:
        """執行爬蟲；若失敗且有舊資料則保留舊資料"""
        results = fetch_fn()
        if results:
            return results
        old = existing_by_source.get(source_key, [])
        if old:
            log.warning(f"[{source_key}] 爬取失敗，保留 {len(old)} 筆舊資料")
        return old

    all_events = []
    all_events.extend(fetch_with_fallback(fetch_beach_events, "環境部海岸淨灘平台"))
    all_events.extend(fetch_with_fallback(fetch_apatw_events, "中華民國保護動物協會 APATW"))

    # 依日期排序（無日期排最後）
    all_events.sort(key=lambda e: e.get("date") or "9999")

    result = {
        "last_updated": datetime.now().isoformat(timespec="seconds"),
        "total": len(all_events),
        "events": all_events,
    }

    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info(f"已寫入 {DATA_FILE}，共 {len(all_events)} 筆活動")


if __name__ == "__main__":
    run()
