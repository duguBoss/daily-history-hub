from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import mimetypes
import os
import re
import shutil
import random
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

import pytz
import requests
import opencc


SHANGHAI_TZ = pytz.timezone("Asia/Shanghai")
REQUEST_TIMEOUT = 30
DEFAULT_WIKIPEDIA_LANG = os.environ.get("WIKIPEDIA_LANG", "zh")
DEFAULT_LIMIT = int(os.environ.get("HISTORY_TODAY_LIMIT", "8"))
DEFAULT_OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", "output"))
ASSET_ROOT = Path("assets") / "generated" / "history_today"
PRIMARY_GEMINI_MODEL = "gemini-3-flash-preview"
FALLBACK_GEMINI_MODEL = "gemini-3.1-flash-lite-preview"
SOURCE_BRITANNICA = "britannica"
SOURCE_WIKIMEDIA = "wikimedia"
SOURCE_DAYINHISTORY = "dayinhistory"
SOURCE_API_NINJAS = "api_ninjas"
SOURCE_HISTORY_DOT_COM = "history_dot_com"
UNSPLASH_SEARCH_URL = "https://api.unsplash.com/search/photos"
OPENVERSE_IMAGES_URL = "https://api.openverse.org/v1/images/"
COMMONS_API_URL = "https://commons.wikimedia.org/w/api.php"
Z_IMAGE_TURBO_BASE_URL = "https://mrfakename-z-image-turbo.hf.space"
MONTH_NAMES = {
    1: "january",
    2: "february",
    3: "march",
    4: "april",
    5: "may",
    6: "june",
    7: "july",
    8: "august",
    9: "september",
    10: "october",
    11: "november",
    12: "december",
}
CHINA_RELATED_PATTERNS = [
    "china",
    "chinese",
    "中国",
    "中华人民共和国",
    "中华民国",
    "中共",
    "中国共产党",
    "北京",
    "上海",
    "广州",
    "深圳",
    "武汉",
    "香港",
    "澳门",
    "台湾",
    "台北",
    "西藏",
    "新疆",
    "内蒙古",
    "满洲",
    "清朝",
    "明朝",
    "元朝",
    "汉朝",
    "唐朝",
    "宋朝",
    "people's republic of china",
    "republic of china",
    "prc",
    "roc",
    "communist party of china",
    "chinese communist party",
    "ccp",
    "cpc",
    "mao zedong",
    "xi jinping",
    "deng xiaoping",
    "chiang kai-shek",
    "sun yat-sen",
    "beijing",
    "peking",
    "shanghai",
    "guangzhou",
    "shenzhen",
    "wuhan",
    "hong kong",
    "macau",
    "taiwan",
    "taipei",
    "tibet",
    "xinjiang",
    "inner mongolia",
    "manchuria",
    "uyghur",
    "uygur",
    "tiananmen",
    "south china sea",
    "pla",
    "kuomintang",
    "nationalist china",
    "qing dynasty",
    "ming dynasty",
    "yuan dynasty",
    "han dynasty",
    "tang dynasty",
    "song dynasty",
    "taiwan strait",
    "formosa",
    "taiwanese",
    "chiang ching-kuo",
    "lee teng-hui",
    "chen shui-bian",
    "ma ying-jeou",
    "tsai ing-wen",
    "democratic progressive party",
    "nationalist government",
    "warlord era",
    "first sino-japanese war",
    "second sino-japanese war",
    "boxer rebellion",
    "xinhai revolution",
    "beiyang",
    "qing empire",
    "puyi",
    "yuan shikai",
]

SENSITIVE_TOPIC_PATTERNS = [
    "politics",
    "political",
    "territorial dispute",
    "territorial disputes",
    "border dispute",
    "border conflicts",
    "sovereignty",
    "sovereign claim",
    "annexation",
    "cession",
    "secession",
    "independence movement",
    "independence referendum",
    "separatist",
    "self-determination",
    "civil war",
    "coup",
    "military junta",
    "regime",
    "party congress",
    "communist party",
    "nationalist party",
    "election",
    "referendum",
    "protest movement",
    "occupation of",
    "occupied territory",
    "disputed territory",
    "uprising",
    "rebellion",
    "revolution",
    "martial law",
    "colonial rule",
    "colonial government",
    "geopolitical",
    "sanction",
    "diplomatic crisis",
    "ethnic conflict",
]


def build_user_agent() -> str:
    repository = os.environ.get("GITHUB_REPOSITORY", "duguBoss/daily-history-hub")
    contact = os.environ.get("WIKIMEDIA_CONTACT", "https://github.com/duguBoss/daily-history-hub")
    return f"daily-history-hub/1.0 ({contact}; repo={repository})"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Aggregate on-this-day data and produce a WeChat HTML article.")
    parser.add_argument("--date", help="Target date in YYYY-MM-DD format.")
    parser.add_argument("--month", type=int, help="Target month, used with --day.")
    parser.add_argument("--day", type=int, help="Target day, used with --month.")
    parser.add_argument("--lang", default=DEFAULT_WIKIPEDIA_LANG, help="Wikipedia language edition. Default: zh")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="Maximum number of merged events.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Directory for generated files.")
    return parser.parse_args()


def resolve_target_date(date_arg: str | None, month_arg: int | None, day_arg: int | None) -> dt.date:
    today = dt.datetime.now(SHANGHAI_TZ).date()
    if date_arg:
        return dt.date.fromisoformat(date_arg)
    if month_arg is not None or day_arg is not None:
        if month_arg is None or day_arg is None:
            raise ValueError("--month and --day must be provided together.")
        return dt.date(today.year, month_arg, day_arg)
    return today


def normalize_text(text: str) -> str:
    return " ".join((text or "").replace("\n", " ").split())


def to_simplified(text: str) -> str:
    if not text:
        return text
    converter = opencc.OpenCC("t2s")
    return converter.convert(text)


def log(message: str) -> None:
    print(f"[history_today] {message}")


def make_event_key(year: Any, text: str) -> str:
    lowered = normalize_text(text).lower()
    simplified = "".join(ch for ch in lowered if ch.isalnum() or ch.isspace())
    return f"{year}|{simplified}"


def canonical_event_text(item: dict[str, Any]) -> str:
    detail = item.get("detail") or {}
    candidates = [
        item.get("text", ""),
        detail.get("title", ""),
        detail.get("description", ""),
        detail.get("extract", ""),
    ]
    for page in item.get("pages", []):
        candidates.extend([page.get("title", ""), page.get("description", ""), page.get("extract", "")])
    text = normalize_text(" ".join(part for part in candidates if part)).lower()
    return "".join(ch for ch in text if ch.isalnum() or ch.isspace())


def is_duplicate_event(candidate: dict[str, Any], existing: dict[str, Any]) -> bool:
    if str(candidate.get("year", "")) != str(existing.get("year", "")):
        return False
    left = canonical_event_text(candidate)
    right = canonical_event_text(existing)
    if not left or not right:
        return False
    if left == right:
        return True
    short, long_ = (left, right) if len(left) <= len(right) else (right, left)
    if len(short) >= 24 and short in long_:
        return True
    short_words = set(short.split())
    long_words = set(long_.split())
    if short_words and len(short_words) >= 4:
        overlap = len(short_words & long_words) / len(short_words)
        if overlap >= 0.85:
            return True
    return False


def dedupe_final_items(items: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for item in items:
        if any(is_duplicate_event(item, existing) for existing in results):
            continue
        results.append(item)
        if len(results) >= limit:
            break
    return results


def is_china_related_text(text: str) -> bool:
    lowered = normalize_text(text).lower()
    return any(pattern in lowered for pattern in CHINA_RELATED_PATTERNS)


def is_sensitive_topic_text(text: str) -> bool:
    lowered = normalize_text(text).lower()
    return any(pattern in lowered for pattern in SENSITIVE_TOPIC_PATTERNS)


def normalize_page(page: dict[str, Any]) -> dict[str, str]:
    content_urls = page.get("content_urls") or {}
    desktop = content_urls.get("desktop") or {}
    mobile = content_urls.get("mobile") or {}
    titles = page.get("titles") or {}
    thumbnail = page.get("thumbnail") or {}
    originalimage = page.get("originalimage") or {}
    return {
        "title": page.get("normalizedtitle") or titles.get("normalized") or page.get("title", ""),
        "url": desktop.get("page") or mobile.get("page", ""),
        "description": page.get("description", ""),
        "extract": page.get("extract", ""),
        "thumbnail": thumbnail.get("source", "") or originalimage.get("source", ""),
        "wikidata_id": page.get("wikibase_item", ""),
    }


def is_china_related_item(item: dict[str, Any]) -> bool:
    fields = [str(item.get("year", "")), item.get("text", ""), item.get("category", "")]
    for page in item.get("pages", []):
        fields.extend(
            [
                page.get("title", ""),
                page.get("url", ""),
                page.get("description", ""),
                page.get("extract", ""),
            ]
        )
    return any(is_china_related_text(field) for field in fields if field)


def is_sensitive_item(item: dict[str, Any]) -> bool:
    fields = [str(item.get("year", "")), item.get("text", ""), item.get("category", "")]
    detail = item.get("detail") or {}
    fields.extend(
        [
            detail.get("title", ""),
            detail.get("url", ""),
            detail.get("description", ""),
            detail.get("extract", ""),
        ]
    )
    for page in item.get("pages", []):
        fields.extend(
            [
                page.get("title", ""),
                page.get("url", ""),
                page.get("description", ""),
                page.get("extract", ""),
            ]
        )
    return any(is_sensitive_topic_text(field) for field in fields if field)


def filter_safe_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    filtered = [item for item in items if not is_china_related_item(item) and not is_sensitive_item(item)]
    removed = len(items) - len(filtered)
    if removed:
        log(f"Filtered China-related or sensitive items after enrichment: {removed}")
    return filtered


def britannica_date_url(target_date: dt.date) -> str:
    month_name = MONTH_NAMES[target_date.month].title()
    return f"https://www.britannica.com/on-this-day/{month_name}-{target_date.day}"


def replace_img_with_markers(html_text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        tag = match.group(0)
        alt_match = re.search(r'alt="([^"]*)"', tag, flags=re.IGNORECASE)
        src_match = re.search(r'src="([^"]*)"', tag, flags=re.IGNORECASE)
        alt_text = html.unescape(alt_match.group(1)) if alt_match else ""
        src = src_match.group(1) if src_match else ""
        if src.startswith("//"):
            src = f"https:{src}"
        if src.startswith("/"):
            src = f"https://www.britannica.com{src}"
        marker = f"Image: {normalize_text(alt_text)} || {src}".strip()
        return f"\n{marker}\n" if src or alt_text else "\n"

    return re.sub(r"<img\b[^>]*>", repl, html_text, flags=re.IGNORECASE)


def html_to_lines(html_text: str) -> list[str]:
    text = replace_img_with_markers(html_text)
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"</?(?:p|div|section|article|li|ul|ol|h1|h2|h3|h4|h5|h6|br)\b[^>]*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = text.replace("\xa0", " ")
    return [normalize_text(line) for line in text.splitlines() if normalize_text(line)]


def parse_britannica_item(year: str, text_parts: list[str], image_url: str, detail_url: str) -> dict[str, Any]:
    text = normalize_text(" ".join(text_parts))
    description = ""
    extract = text
    if " ." in text:
        text = text.replace(" .", ".")
    if "." in text:
        first_sentence, remainder = text.split(".", 1)
        description = normalize_text(first_sentence)
        extract = normalize_text(remainder)
        if extract:
            text = f"{description}. {extract}"
        else:
            text = description
    return {
        "source": SOURCE_BRITANNICA,
        "category": "events",
        "year": year,
        "text": text,
        "source_url": detail_url,
        "pages": [
            {
                "title": description or text[:80],
                "url": detail_url,
                "description": description,
                "extract": extract,
                "thumbnail": image_url,
                "wikidata_id": "",
            }
        ]
        if text
        else [],
        "detail": {
            "title": description or text[:80],
            "url": detail_url,
            "description": description,
            "extract": extract,
            "thumbnail": image_url,
            "wikidata_id": "",
        },
        "image_url": image_url,
    }


def fetch_britannica(target_date: dt.date) -> dict[str, Any]:
    url = britannica_date_url(target_date)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Referer": "https://www.britannica.com/",
    }
    try:
        response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
    except Exception as exc:
        return {"ok": False, "items": [], "endpoint": url, "error": str(exc)}
    lines = html_to_lines(response.text)
    items: list[dict[str, Any]] = []
    in_events = False
    featured_taken = False
    current_year = ""
    current_image = ""
    current_parts: list[str] = []
    stop_markers = {"More Events On This Day", "This Day in History"}

    def flush() -> None:
        nonlocal current_year, current_image, current_parts
        if current_year and current_parts:
            item = parse_britannica_item(current_year, current_parts, current_image, url)
            if item["text"] and not is_china_related_item(item):
                items.append(item)
        current_year = ""
        current_image = ""
        current_parts = []

    for line in lines:
        if line == "Featured Event":
            in_events = True
            featured_taken = False
            flush()
            continue
        if line in stop_markers and items:
            flush()
            if line == "This Day in History":
                break
            in_events = line == "More Events On This Day"
            continue
        if line == "More Events On This Day":
            flush()
            in_events = True
            continue
        if not in_events:
            continue
        if line.startswith("Image: "):
            _, _, payload = line.partition("Image: ")
            _, _, src = payload.partition(" || ")
            current_image = src.strip()
            continue
        year_match = re.fullmatch(r"\d{1,4}(?:\s*BCE)?", line)
        if year_match:
            if current_year:
                flush()
            current_year = line
            continue
        if line.startswith("By signing up"):
            flush()
            break
        if current_year:
            current_parts.append(line)
            if not featured_taken:
                featured_taken = True
    flush()
    return {"ok": bool(items), "items": items[:5], "endpoint": url, "error": "" if items else "No Britannica items parsed"}


def wikimedia_candidates(lang: str, target_date: dt.date) -> list[tuple[str, dict[str, str]]]:
    month = f"{target_date.month:02d}"
    day = f"{target_date.day:02d}"
    headers = {
        "User-Agent": build_user_agent(),
        "Api-User-Agent": build_user_agent(),
        "Accept": "application/json",
    }
    token = os.environ.get("WIKIMEDIA_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
        return [(f"https://api.wikimedia.org/feed/v1/wikipedia/{lang}/onthisday/all/{month}/{day}", headers)]
    return [
        (f"https://{lang}.wikipedia.org/api/rest_v1/feed/onthisday/all/{month}/{day}", headers),
        (f"https://api.wikimedia.org/feed/v1/wikipedia/{lang}/onthisday/all/{month}/{day}", headers),
    ]


def fetch_wikimedia(lang: str, target_date: dt.date) -> dict[str, Any]:
    last_error: Exception | None = None
    for url, headers in wikimedia_candidates(lang, target_date):
        try:
            response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            payload = response.json()
            items: list[dict[str, Any]] = []
            for category in ("selected", "events", "births", "deaths", "holidays"):
                for entry in payload.get(category) or []:
                    pages = [normalize_page(page) for page in entry.get("pages") or []]
                    item = {
                        "source": SOURCE_WIKIMEDIA,
                        "category": category,
                        "year": entry.get("year"),
                        "text": normalize_text(entry.get("text", "")),
                        "source_url": url,
                        "pages": [page for page in pages if page["title"] or page["url"]],
                    }
                    if item["text"] and not is_china_related_item(item):
                        items.append(item)
            return {"ok": True, "items": items, "endpoint": url}
        except Exception as exc:
            last_error = exc
    return {"ok": False, "items": [], "endpoint": "", "error": str(last_error) if last_error else "unknown"}


def fetch_dayinhistory(target_date: dt.date) -> dict[str, Any]:
    month_name = MONTH_NAMES[target_date.month]
    headers = {"Accept": "application/json", "User-Agent": build_user_agent()}
    items: list[dict[str, Any]] = []
    failures: list[str] = []
    for category in ("events", "births", "deaths"):
        for base_url in ("https://api.dayinhistory.com/v1", "https://api.dayinhistory.dev/v1"):
            url = f"{base_url}/{category}/{month_name}/{target_date.day}/"
            try:
                response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
                response.raise_for_status()
                payload = response.json()
                results = payload if isinstance(payload, list) else []
                if isinstance(payload, dict):
                    for key in ("data", "results", "events", "births", "deaths"):
                        if isinstance(payload.get(key), list):
                            results = payload[key]
                            break
                for entry in results:
                    item = {
                        "source": SOURCE_DAYINHISTORY,
                        "category": category,
                        "year": entry.get("year") or entry.get("date") or entry.get("birth_year") or entry.get("death_year"),
                        "text": normalize_text(
                            entry.get("event")
                            or entry.get("description")
                            or entry.get("content")
                            or entry.get("text")
                            or entry.get("title")
                            or ""
                        ),
                        "source_url": url,
                        "pages": [],
                    }
                    if item["text"] and not is_china_related_item(item):
                        items.append(item)
                break
            except Exception as exc:
                failures.append(f"{category} via {base_url}: {exc}")
    return {
        "ok": bool(items),
        "items": items,
        "endpoint": "https://api.dayinhistory.com/v1/ or https://api.dayinhistory.dev/v1/",
        "error": "; ".join(failures),
    }


def fetch_api_ninjas(target_date: dt.date) -> dict[str, Any]:
    api_key = os.environ.get("API_NINJAS_API_KEY")
    if not api_key:
        return {"ok": False, "items": [], "endpoint": "", "error": "Missing API_NINJAS_API_KEY"}
    url = f"https://api.api-ninjas.com/v1/historicalevents?month={target_date.month}&day={target_date.day}"
    response = requests.get(
        url,
        headers={"X-Api-Key": api_key, "User-Agent": build_user_agent()},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    items = []
    for entry in response.json():
        item = {
            "source": SOURCE_API_NINJAS,
            "category": "events",
            "year": entry.get("year"),
            "text": normalize_text(entry.get("event", "")),
            "source_url": url,
            "pages": [],
        }
        if item["text"] and not is_china_related_item(item):
            items.append(item)
    log(f"\n================ API Ninjas Extracted Items ================")
    for idx, item in enumerate(items):
        log(f"Item {idx}: year={item['year']}, text={item['text'][:80]}..., image_url={item.get('image_url', 'N/A')}")
    log(f"Total items: {len(items)}")
    log(f"===========================================================\n")
    return {"ok": True, "items": items, "endpoint": url}


def fetch_history_dot_com(target_date: dt.date) -> dict[str, Any]:
    month_name = MONTH_NAMES[target_date.month].lower()
    url = f"https://r.jina.ai/https://www.history.com/this-day-in-history/{month_name}-{target_date.day}"
    headers = {
        "Accept": "text/plain",
        "User-Agent": build_user_agent(),
        "x-target-url": f"https://www.history.com/this-day-in-history/{month_name}-{target_date.day}",
    }
    try:
        response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        raw_text = response.text.strip()
        if not raw_text:
            return {"ok": False, "items": [], "endpoint": url, "error": "Empty response from jina.ai"}

        log(f"\n================ History.com Raw Fetched Text (first 500 chars) ================\n{raw_text[:500]}\n...\n================================================================================\n")

        try:
            items = extract_history_dot_com_with_gemini(raw_text, target_date)
            return {"ok": bool(items), "items": items, "endpoint": url, "error": "" if items else "No items parsed"}
        except Exception as exc:
            log(f"Error extracting history.com items: {exc}")
            return {"ok": False, "items": [], "endpoint": url, "error": str(exc)}
    except Exception as exc:
        return {"ok": False, "items": [], "endpoint": url, "error": str(exc)}


EXTRACT_HISTORY_DOT_COM_PROMPT = """You are a data extraction assistant. Extract historical events from the provided text collected from history.com this-day-in-history page via jina.ai.

The raw text has a section called "Also on This Day in History" near the bottom. Extract events from this section ONLY.

Each event line looks like this:
- [1865 Battle of Bentonville begins in North Carolina On March 19, 1865...] (URL) 1:46 m read
- [1916 First U.S. air combat mission begins Eight Curtiss "Jenny" planes...] (URL) 1:26 m read ![Image 13](https://res.cloudinary.com/aenetworks/image/upload/...)
- [1931 Nevada legalizes gambling In an attempt...] (URL) 1:10 m read ![Image 14](https://res.cloudinary.com/aenetworks/image/upload/...)

Pattern: [YEAR + description text] (URL) duration m read [OPTIONAL: ![Image N](cloudinary_url)]

For each event:
- year: the 4-digit number at the very start (e.g., "1865", "1916", "1931")
- text: the description text between the year and the closing bracket, before the URL
- image_url: if there is ![Image N](...) after "m read", extract the cloudinary.com URL from inside the parentheses; otherwise use empty string ""

Return a JSON array where each element has exactly this structure:
[
  {
    "year": "year string",
    "text": "event description",
    "image_url": "direct image URL or empty string"
  }
]

Rules:
1. Focus ONLY on the "Also on This Day in History" section
2. Extract the YEAR (4-digit number at start of each event)
3. Extract the event description (text after year, before the URL link)
4. If there is ![Image N](cloudinary_url) after the event, extract that URL; otherwise use ""
5. Do NOT randomly assign images - only use the image that directly follows an event
6. Only extract events (skip "Born on This Day" section)
7. Filter out China-related content, political events, wars, conflicts
8. Return ONLY valid JSON array, no markdown, no explanation

Target date: {target_date}

Raw content to extract from:
{raw_text}"""


def extract_history_dot_com_with_gemini(raw_text: str, target_date: dt.date) -> list[dict[str, Any]]:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("Missing GEMINI_API_KEY")

    prompt = EXTRACT_HISTORY_DOT_COM_PROMPT.format(target_date=target_date.isoformat(), raw_text=raw_text)

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{PRIMARY_GEMINI_MODEL}:generateContent"
    response = requests.post(
        url,
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.3, "responseMimeType": "application/json"},
        },
        timeout=REQUEST_TIMEOUT * 3,
    )
    response.raise_for_status()
    payload = response.json()
    candidates = payload.get("candidates") or []
    if not candidates:
        raise RuntimeError(f"Gemini returned no candidates: {payload}")
    parts = ((candidates[0].get("content") or {}).get("parts")) or []
    text = "".join(part.get("text", "") for part in parts).strip()
    if not text:
        raise RuntimeError(f"Gemini returned empty text: {payload}")

    log(f"\n================ History.com Gemini Extraction Raw Output ================\n{text}\n==================================================================\n")

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        log(f"JSON parse error: {e}, attempting to extract JSON from text...")
        json_match = re.search(r'\[.*\]', text, re.DOTALL)
        if json_match:
            try:
                parsed = json.loads(json_match.group(0))
            except Exception as inner_e:
                log(f"Failed to extract JSON array: {inner_e}, trying to find JSON objects...")
                objects = re.findall(r'\{[^{}]*"year"[^{}]*"text"[^{}]*"image_url"[^{}]*\}', text, re.DOTALL)
                if objects:
                    parsed = []
                    for obj in objects:
                        try:
                            parsed.append(json.loads(obj))
                        except:
                            pass
                    if parsed:
                        log(f"Successfully extracted {len(parsed)} objects from text")
                    else:
                        raise RuntimeError(f"Gemini output is not valid JSON and could not extract JSON array: {e}")
                else:
                    raise RuntimeError(f"Gemini output is not valid JSON and could not extract JSON array: {e}")
        else:
            raise RuntimeError(f"Gemini output is not valid JSON: {e}")

    if not isinstance(parsed, list):
        raise RuntimeError(f"Expected JSON array from Gemini, got {type(parsed)}")

    items: list[dict[str, Any]] = []
    for entry in parsed:
        if not isinstance(entry, dict):
            continue
        year = entry.get("year", "")
        text_val = entry.get("text", "")
        image_url = entry.get("image_url", "") or ""

        if not text_val or not year:
            continue
        if is_china_related_text(text_val):
            continue

        items.append({
            "source": SOURCE_HISTORY_DOT_COM,
            "category": "events",
            "year": year,
            "text": normalize_text(text_val),
            "image_url": image_url,
            "source_url": f"https://www.history.com/this-day-in-history/{MONTH_NAMES[target_date.month].lower()}-{target_date.day}",
            "pages": [],
        })

    log(f"\n================ History.com Extracted Items ================")
    for idx, item in enumerate(items):
        log(f"Item {idx}: year={item['year']}, text={item['text'][:50]}..., image_url={item['image_url']}")
    log(f"===========================================================\n")

    return items


def infer_confidence(item: dict[str, Any]) -> str:
    count = len(item["sources"])
    if count >= 3:
        return "high"
    if count == 2:
        return "medium"
    return "low"


def merge_items(source_results: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for result in source_results:
        for item in result["items"]:
            if is_china_related_item(item):
                continue
            key = make_event_key(item.get("year"), item.get("text", ""))
            current = merged.get(key)
            if current is None:
                merged[key] = {
                    "year": item.get("year"),
                    "text": item.get("text", ""),
                    "categories": [item.get("category", "events")],
                    "sources": [item.get("source", "")],
                    "source_urls": [item.get("source_url", "")] if item.get("source_url") else [],
                    "pages": item.get("pages", []),
                    "detail": item.get("detail", {}),
                    "image_url": item.get("image_url", ""),
                }
                continue
            if item.get("category") and item["category"] not in current["categories"]:
                current["categories"].append(item["category"])
            if item.get("source") and item["source"] not in current["sources"]:
                current["sources"].append(item["source"])
            if item.get("source_url") and item["source_url"] not in current["source_urls"]:
                current["source_urls"].append(item["source_url"])
            if not current["pages"] and item.get("pages"):
                current["pages"] = item["pages"]
            if not current.get("detail") and item.get("detail"):
                current["detail"] = item["detail"]
            if SOURCE_BRITANNICA in current["sources"] and item.get("source") == SOURCE_BRITANNICA:
                if item.get("detail"):
                    current["detail"] = item["detail"]
                if item.get("pages"):
                    current["pages"] = item["pages"]
                if item.get("image_url"):
                    current["image_url"] = item["image_url"]

    ordered = sorted(
        merged.values(),
        key=lambda item: (
            SOURCE_BRITANNICA not in item["sources"],
            -len(item["sources"]),
            str(item.get("year") or ""),
            item["text"],
        ),
    )
    results = []
    for item in ordered:
        if is_china_related_item(item):
            continue
        if not item.get("image_url"):
            image_url = ""
            for page in item.get("pages", []):
                if page.get("thumbnail"):
                    image_url = page["thumbnail"]
                    break
            item["image_url"] = image_url
        item["source_confidence"] = infer_confidence(item)
        results.append(item)
    return dedupe_final_items(results, limit)


def source_stats(source_results: list[dict[str, Any]], merged_items: list[dict[str, Any]]) -> dict[str, Any]:
    per_source = {}
    for result in source_results:
        per_source[result["name"]] = {
            "ok": result.get("ok", False),
            "item_count": len(result.get("items", [])),
            "endpoint": result.get("endpoint", ""),
            "error": result.get("error", ""),
        }
    agreement = Counter(len(item["sources"]) for item in merged_items)
    return {"sources": per_source, "merged_count": len(merged_items), "agreement_breakdown": dict(sorted(agreement.items()))}


def fetch_wikipedia_page_detail(page_title: str, lang: str) -> dict[str, str]:
    if not page_title:
        return {}
    url = f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{quote(page_title, safe='')}"
    response = requests.get(
        url,
        headers={"User-Agent": build_user_agent(), "Api-User-Agent": build_user_agent(), "Accept": "application/json"},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    payload = response.json()
    titles = payload.get("titles") or {}
    thumbnail = payload.get("thumbnail") or {}
    originalimage = payload.get("originalimage") or {}
    content_urls = payload.get("content_urls") or {}
    desktop = content_urls.get("desktop") or {}
    mobile = content_urls.get("mobile") or {}
    return {
        "title": titles.get("normalized") or payload.get("title", page_title),
        "url": desktop.get("page") or mobile.get("page", ""),
        "description": payload.get("description", ""),
        "extract": normalize_text(payload.get("extract", "")),
        "thumbnail": thumbnail.get("source", "") or originalimage.get("source", ""),
        "wikidata_id": payload.get("wikibase_item", ""),
    }


def enrich_item_details(merged_items: list[dict[str, Any]], lang: str) -> None:
    for item in merged_items:
        if item.get("detail"):
            continue
        detail: dict[str, str] = {}
        for page in item.get("pages", []):
            detail = {
                "title": page.get("title", ""),
                "url": page.get("url", ""),
                "description": page.get("description", ""),
                "extract": normalize_text(page.get("extract", "")),
                "thumbnail": page.get("thumbnail", ""),
                "wikidata_id": page.get("wikidata_id", ""),
            }
            if detail["extract"] and detail["description"]:
                break
            try:
                remote_detail = fetch_wikipedia_page_detail(page.get("title", ""), lang)
            except Exception:
                remote_detail = {}
            for key, value in remote_detail.items():
                if value and not detail.get(key):
                    detail[key] = value
            if detail.get("extract") or detail.get("description"):
                break
        item["detail"] = detail
        if detail.get("thumbnail") and not item.get("image_url"):
            item["image_url"] = detail["thumbnail"]


def build_gemini_prompt(target_date: dt.date, merged_items: list[dict[str, Any]], stats: dict[str, Any]) -> str:
    compact_items = [
        {
            "year": item["year"],
            "text": item["text"],
            "categories": item["categories"],
            "sources": item["sources"],
            "source_confidence": item["source_confidence"],
            "page_title": item["pages"][0]["title"] if item["pages"] else "",
            "detail_title": (item.get("detail") or {}).get("title", ""),
            "detail_description": (item.get("detail") or {}).get("description", ""),
            "detail_extract": (item.get("detail") or {}).get("extract", ""),
            "detail_url": (item.get("detail") or {}).get("url", ""),
        }
        for item in merged_items
    ]
    return (
        "You are writing a finished WeChat article.\n"
        "**CRITICAL REQUIREMENTS (必须严格遵守以下所有限制):**\n"
        "1. 语言要求：**全部内容必须使用标准简体中文（Simplified Chinese）**。绝对禁止输出繁体字！绝对禁止出现整句或整段的英文（除必须保留的少数专有名词外，务必将所有英文素材完美翻译成中文）。\n"
        "2. 叙事视角：作为全知全能的叙述者直接陈述历史事实。**绝对禁止**出现任何表明信息来源的词汇（如“根据大英百科全书”、“维基百科补充提到”、“资料显示”、“参考记录”等）。\n"
        "3. 消除AI痕迹：**绝对禁止**使用任何AI生成的元语言或修饰词（如“缺少详细信息”、“这标志着”、“不可否认”、“以下为您生成”、“为您串联”等）。\n"
        "4. 内容完整性：文章必须结构完整、连贯流畅，自然地展开故事，并且有一个合理的收尾句。**绝对不能**烂尾、中途断裂或显得拼凑缺失。\n"
        "5. 行文风格：引人入胜的杂志深度专栏风格，同时保持客观真实，不带感情色彩。\n"
        "Exclude anything related to China, PRC, ROC, Hong Kong, Macau, Taiwan, Tibet, Xinjiang, Chinese dynasties, politics, parties, sovereignty, independence, territorial disputes, border conflicts, coups, rebellions, revolutions, sanctions, diplomatic crises, and geopolitics.\n"
        "The title must be in Simplified Chinese. Must be exactly 32 characters. Must follow this format: '历史上的今天：[流量标题格式，包含悬念/数字/反差/热点词]，例如：历史上的今天：此人发明一物改变世界，至今仍影响每个人'.\n"
        "Return valid JSON only with this schema:\n"
        "{\n"
        '  "title": "简体中文标题，严格32字",\n'
        '  "summary": "纯简体中文摘要，不超过80字",\n'
        '  "content_text": "complete Chinese article body with at least 5 paragraphs separated by \\n\\n, combining the historical points logically."\n'
        "}\n"
        "Do not output markdown. Do not output HTML. Do not mention filtering.\n"
        f"Target date: {target_date.isoformat()}\n"
        f"Merged items: {json.dumps(compact_items, ensure_ascii=False)}"
    )


def validate_gemini_result(result: dict[str, Any]) -> dict[str, Any]:
    for key in ("title", "summary", "content_text"):
        value = result.get(key, "")
        if not isinstance(value, str) or not value.strip():
            raise RuntimeError(f"Gemini output missing {key}")
        
        # 自动将繁体字转换为简体字
        value = to_simplified(value)
        
        if is_china_related_text(value):
            raise RuntimeError(f"Validation failed: output contains filtered (China-related) content in [{key}].")
        
        # 拦截大段英文 (如果内容中英文字母占比异常高，说明输出了英文段落)
        alpha_count = len(re.findall(r'[a-zA-Z]', value))
        if len(value) > 0 and (alpha_count / len(value)) > 0.3:
            raise RuntimeError(f"Validation failed: Gemini output contains too much English text in [{key}].")

        # 拦截暴露来源和AI痕迹的词汇
        forbidden_words = ["补充提到", "根据", "资料显示", "维基百科", "大英百科全书", "大英百科", "参考"]
        found_words = [word for word in forbidden_words if word in value]
        if found_words:
             raise RuntimeError(f"Validation failed: Gemini output contains forbidden source words ({found_words}) in [{key}].")
             
        result[key] = value
             
    if len(result["summary"].strip()) > 80:
        raise RuntimeError("Validation failed: Gemini output summary exceeds 80 characters.")
    return result


def call_gemini_once(prompt: str, model_name: str) -> dict[str, Any]:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("Missing GEMINI_API_KEY")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"
    response = requests.post(
        url,
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            # 将 temperature 提高到 0.75，增加输出多样性，打破僵化的输出格式
            "generationConfig": {"temperature": 0.75, "responseMimeType": "application/json"},
        },
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    payload = response.json()
    candidates = payload.get("candidates") or []
    if not candidates:
        raise RuntimeError(f"Gemini returned no candidates: {payload}")
    parts = ((candidates[0].get("content") or {}).get("parts")) or []
    text = "".join(part.get("text", "") for part in parts).strip()
    if not text:
        raise RuntimeError(f"Gemini returned empty text: {payload}")
        
    # === 关键控制台打印：在这里打印AI直接吐出的内容，方便排查 ===
    log(f"\n================ Gemini Raw Output ({model_name}) ================\n{text}\n==================================================================\n")

    try:
        parsed_result = json.loads(text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Gemini output is not valid JSON: {e}")

    return validate_gemini_result(parsed_result)


def call_gemini(prompt: str) -> dict[str, Any]:
    errors: list[str] = []
    max_retries = 2
    for attempt in range(max_retries):
        for model_name in (PRIMARY_GEMINI_MODEL, FALLBACK_GEMINI_MODEL):
            try:
                result = call_gemini_once(prompt, model_name)
                if attempt > 0:
                    log(f"重试成功! (尝试 {attempt + 1})")
                return result
            except Exception as exc:
                errors.append(f"{model_name} Error: {exc}")
                log(f"生成失败 (尝试 {attempt + 1}, 模型 {model_name}): {exc}")
                continue
    raise RuntimeError(" | ".join(errors))


def build_fallback_article(target_date: dt.date, merged_items: list[dict[str, Any]]) -> dict[str, Any]:
    # 为了避免输出纯英文，这里先过滤出包含中文字符的事件用于拼接兜底文章
    zh_items = [item for item in merged_items if re.search(r'[\u4e00-\u9fff]', item.get('text', ''))]
    if not zh_items:
        # 如果极端情况下没有任何中文内容，依然拿几个凑数（此时可能会出现英文）
        zh_items = merged_items[:6]
        
    selected = zh_items[:6]
    paragraphs = [
        f"{target_date.month}月{target_date.day}日这一天，历史留下了几段截然不同的切片，权力更替、突发事件和人物命运交错重叠。"
    ]
    for item in selected:
        detail = item.get("detail") or {}
        detail_text = detail.get("extract") or detail.get("description") or ""
        # 移除原有的“维基页面补充提到：”这种机械和暴露来源的拼凑方式
        if detail_text and detail_text not in item['text']:
            paragraphs.append(f"{item['year']}年：{item['text']} {detail_text}")
        else:
            paragraphs.append(f"{item['year']}年：{item['text']}")
            
    paragraphs.append("时间的刻度在这些事件中不断延展，共同构建了我们今天所认识的世界。")
    
    content_text = "\n\n".join(paragraphs)
    content_text = to_simplified(content_text)
        
    return {
        "title": to_simplified(f"历史上的今天：{target_date.month}月{target_date.day}日发生了什么"),
        "summary": to_simplified("这一天并不平静，几段历史在同日交错。"),
        "content_text": content_text,
    }


def guess_extension(content_type: str, url: str) -> str:
    guessed = mimetypes.guess_extension((content_type or "").split(";")[0].strip()) or ""
    if guessed in {".jpe", ".jpeg"}:
        return ".jpg"
    if guessed:
        return guessed
    suffix = Path(url.split("?")[0]).suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        return ".jpg" if suffix == ".jpeg" else suffix
    return ".jpg"


def github_asset_url(relative_path: Path) -> str:
    repository = os.environ.get("GITHUB_REPOSITORY", "duguBoss/daily-history-hub")
    branch = os.environ.get("GITHUB_REF_NAME", os.environ.get("DEFAULT_GIT_BRANCH", "main"))
    normalized = str(relative_path).replace("\\", "/")
    return f"https://raw.githubusercontent.com/{repository}/{branch}/{normalized}"


def cleanup_old_assets(today: dt.date, asset_root: Path, keep_days: int = 7) -> None:
    if not asset_root.exists():
        return
    cutoff = today - dt.timedelta(days=keep_days)
    for child in asset_root.iterdir():
        if not child.is_dir():
            continue
        try:
            folder_date = dt.date.fromisoformat(child.name)
        except ValueError:
            continue
        if folder_date < cutoff:
            shutil.rmtree(child, ignore_errors=True)


def fetch_summary_image(page_title: str, lang: str) -> str:
    if not page_title:
        return ""
    url = f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{quote(page_title, safe='')}"
    response = requests.get(
        url,
        headers={"User-Agent": build_user_agent(), "Api-User-Agent": build_user_agent(), "Accept": "application/json"},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    payload = response.json()
    thumbnail = payload.get("thumbnail") or {}
    originalimage = payload.get("originalimage") or {}
    return thumbnail.get("source", "") or originalimage.get("source", "")


def fetch_wikimedia_commons_image(item: dict[str, Any], lang: str) -> str:
    detail = item.get("detail") or {}
    candidate_titles = [page.get("title", "") for page in item.get("pages", []) if page.get("title")]
    if detail.get("title"):
        candidate_titles.insert(0, detail["title"])
    seen_titles: set[str] = set()
    for title in candidate_titles:
        if title in seen_titles:
            continue
        seen_titles.add(title)
        try:
            image_url = fetch_pageimages_image(title, lang)
        except Exception:
            image_url = ""
        if image_url:
            return image_url
    wikidata_id = detail.get("wikidata_id") or next((page.get("wikidata_id", "") for page in item.get("pages", [])), "")
    if not wikidata_id:
        return ""
    wikidata_url = "https://www.wikidata.org/w/api.php"
    commons_url = "https://commons.wikimedia.org/w/api.php"
    response = requests.get(
        wikidata_url,
        params={"action": "wbgetentities", "ids": wikidata_id, "props": "claims", "format": "json"},
        headers={"User-Agent": build_user_agent(), "Accept": "application/json"},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    entity = ((response.json().get("entities") or {}).get(wikidata_id)) or {}
    claims = entity.get("claims") or {}
    for prop in ("P18", "P154", "P41"):
        for claim in claims.get(prop) or []:
            mainsnak = claim.get("mainsnak") or {}
            datavalue = mainsnak.get("datavalue") or {}
            filename = datavalue.get("value")
            if not isinstance(filename, str) or not filename.strip():
                continue
            file_title = filename if filename.startswith("File:") else f"File:{filename}"
            file_response = requests.get(
                commons_url,
                params={"action": "query", "titles": file_title, "prop": "imageinfo", "iiprop": "url", "format": "json"},
                headers={"User-Agent": build_user_agent(), "Accept": "application/json"},
                timeout=REQUEST_TIMEOUT,
            )
            file_response.raise_for_status()
            pages = ((file_response.json().get("query") or {}).get("pages") or {}).values()
            for file_page in pages:
                imageinfo = file_page.get("imageinfo") or []
                if imageinfo and imageinfo[0].get("url"):
                    return imageinfo[0]["url"]
    return ""


def build_unsplash_query(item: dict[str, Any]) -> str:
    detail = item.get("detail") or {}
    title = detail.get("title") or (item.get("pages") or [{}])[0].get("title", "")
    text = item.get("text", "")
    year = item.get("year")
    query_parts = [part for part in [title, text, f"{year}", "history"] if part]
    return normalize_text(" ".join(query_parts))[:180]


def fetch_unsplash_image(item: dict[str, Any], used_unsplash_ids: set[str] = None) -> str:
    if used_unsplash_ids is None:
        used_unsplash_ids = set()
        
    access_key = os.environ.get("UNSPLASH_ACCESS_KEY")
    if not access_key:
        return ""
    query = build_unsplash_query(item)
    if not query:
        return ""
    response = requests.get(
        UNSPLASH_SEARCH_URL,
        params={"query": query, "page": 1, "per_page": 5, "orientation": "landscape", "content_filter": "high"},
        headers={"Authorization": f"Client-ID {access_key}", "Accept-Version": "v1", "User-Agent": build_user_agent()},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    payload = response.json()
    for result in payload.get("results") or []:
        photo_id = result.get("id")
        if photo_id and photo_id in used_unsplash_ids:
            continue
            
        urls = result.get("urls") or {}
        alt_description = normalize_text(result.get("alt_description", "") or result.get("description", ""))
        text_blob = normalize_text(f"{query} {alt_description}").lower()
        if "history" not in text_blob and "historic" not in text_blob:
            continue
        for key in ("raw", "full", "regular"):
            if urls.get(key):
                extra = {"q": "80", "fm": "jpg"}
                separator = "&" if "?" in urls[key] else "?"
                final_url = f"{urls[key]}{separator}{urlencode(extra)}"
                if photo_id:
                    used_unsplash_ids.add(photo_id)
                return final_url
    return ""


def build_image_search_query(item: dict[str, Any]) -> str:
    detail = item.get("detail") or {}
    page_title = ""
    if item.get("pages"):
        page_title = item["pages"][0].get("title", "")
    text = item.get("text", "")
    title = detail.get("title") or page_title
    description = detail.get("description", "")
    extract = detail.get("extract", "")
    query_parts = [title, description, text, extract, str(item.get("year", ""))]
    query = normalize_text(" ".join(part for part in query_parts if part))
    query = re.sub(r"\b(?:born|died|dies|death|birthday|holiday|observance)\b", "history", query, flags=re.IGNORECASE)
    return query[:180]


def is_probably_bad_image_title(title: str) -> bool:
    lowered = normalize_text(title).lower()
    blocked = (
        "logo",
        "flag",
        "icon",
        "seal",
        "coat of arms",
        "map of",
        "location of",
        "symbol",
        "wordmark",
    )
    return any(token in lowered for token in blocked)


def fetch_openverse_image(item: dict[str, Any]) -> str:
    query = build_image_search_query(item)
    if not query:
        return ""
    response = requests.get(
        OPENVERSE_IMAGES_URL,
        params={"q": query, "page_size": 10},
        headers={"User-Agent": build_user_agent(), "Accept": "application/json"},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    payload = response.json()
    for result in payload.get("results") or []:
        title = normalize_text(result.get("title", ""))
        if is_probably_bad_image_title(title):
            continue
        width = int(result.get("width") or 0)
        height = int(result.get("height") or 0)
        if width and height and width < 600:
            continue
        image_url = result.get("url") or result.get("thumbnail")
        if image_url:
            return image_url
    return ""


def fetch_commons_search_image(item: dict[str, Any]) -> str:
    query = build_image_search_query(item)
    if not query:
        return ""
    response = requests.get(
        COMMONS_API_URL,
        params={
            "action": "query",
            "generator": "search",
            "gsrsearch": query,
            "gsrnamespace": 6,
            "gsrlimit": 8,
            "prop": "imageinfo",
            "iiprop": "url",
            "iiurlwidth": 1600,
            "format": "json",
        },
        headers={"User-Agent": build_user_agent(), "Accept": "application/json"},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    pages = ((response.json().get("query") or {}).get("pages") or {}).values()
    ranked_pages = sorted(pages, key=lambda page: page.get("index", 9999))
    for page in ranked_pages:
        title = page.get("title", "")
        if is_probably_bad_image_title(title):
            continue
        imageinfo = page.get("imageinfo") or []
        if imageinfo and imageinfo[0].get("url"):
            return imageinfo[0]["url"]
        if imageinfo and imageinfo[0].get("thumburl"):
            return imageinfo[0]["thumburl"]
    return ""


def fetch_pageimages_image(page_title: str, lang: str) -> str:
    if not page_title:
        return ""
    url = f"https://{lang}.wikipedia.org/w/api.php"
    response = requests.get(
        url,
        params={
            "action": "query",
            "prop": "pageimages",
            "titles": page_title,
            "piprop": "original|thumbnail|name",
            "pithumbsize": 1600,
            "format": "json",
        },
        headers={"User-Agent": build_user_agent(), "Accept": "application/json"},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    payload = response.json()
    pages = ((payload.get("query") or {}).get("pages") or {}).values()
    for page in pages:
        original = page.get("original") or {}
        thumbnail = page.get("thumbnail") or {}
        if original.get("source"):
            return original["source"]
        if thumbnail.get("source"):
            return thumbnail["source"]
    return ""


def fetch_page_embedded_image(page_title: str, lang: str) -> str:
    if not page_title:
        return ""
    url = f"https://{lang}.wikipedia.org/w/api.php"
    response = requests.get(
        url,
        params={
            "action": "query",
            "prop": "images",
            "titles": page_title,
            "imlimit": 10,
            "format": "json",
        },
        headers={"User-Agent": build_user_agent(), "Accept": "application/json"},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    payload = response.json()
    pages = ((payload.get("query") or {}).get("pages") or {}).values()
    for page in pages:
        for image in page.get("images") or []:
            image_title = image.get("title", "")
            if not image_title.startswith("File:"):
                continue
            try:
                file_response = requests.get(
                    url,
                    params={
                        "action": "query",
                        "titles": image_title,
                        "prop": "imageinfo",
                        "iiprop": "url",
                        "format": "json",
                    },
                    headers={"User-Agent": build_user_agent(), "Accept": "application/json"},
                    timeout=REQUEST_TIMEOUT,
                )
                file_response.raise_for_status()
                file_payload = file_response.json()
                file_pages = ((file_payload.get("query") or {}).get("pages") or {}).values()
                for file_page in file_pages:
                    imageinfo = file_page.get("imageinfo") or []
                    if imageinfo and imageinfo[0].get("url"):
                        return imageinfo[0]["url"]
            except Exception:
                continue
    return ""


def absolutize_image_url(image_url: str) -> str:
    if not image_url:
        return ""
    if image_url.startswith("//"):
        return f"https:{image_url}"
    return image_url


def fetch_detail_page_image(detail_url: str) -> str:
    if not detail_url:
        return ""
    response = requests.get(
        detail_url,
        headers={"User-Agent": build_user_agent(), "Accept": "text/html,application/xhtml+xml"},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    html_text = response.text

    meta_patterns = [
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+itemprop=["\']image["\'][^>]+content=["\']([^"\']+)["\']',
    ]
    for pattern in meta_patterns:
        match = re.search(pattern, html_text, flags=re.IGNORECASE)
        if match:
            return absolutize_image_url(match.group(1).strip())

    image_patterns = [
        r'<img[^>]+src=["\']([^"\']+)["\'][^>]+class=["\'][^"\']*(?:thumbimage|mw-file-element)[^"\']*["\']',
        r'<img[^>]+class=["\'][^"\']*(?:thumbimage|mw-file-element)[^"\']*["\'][^>]+src=["\']([^"\']+)["\']',
        r'<img[^>]+src=["\']([^"\']+)["\'][^>]*>',
    ]
    for pattern in image_patterns:
        match = re.search(pattern, html_text, flags=re.IGNORECASE)
        if match:
            image_url = absolutize_image_url(match.group(1).strip())
            if image_url and not image_url.startswith("data:"):
                return image_url

    return ""


def download_image(url: str, target_dir: Path) -> str:
    if not url:
        return ""
    response = requests.get(url, headers={"User-Agent": build_user_agent()}, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    extension = guess_extension(response.headers.get("Content-Type", ""), url)
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    file_path = target_dir / f"{digest}{extension}"
    
    # 强制重新写入文件以绕过可能的文件缓存机制
    file_path.write_bytes(response.content)
    return str(file_path)


def build_generated_cover_prompt(article: dict[str, Any], merged_items: list[dict[str, Any]], target_date: dt.date) -> str:
    highlights = []
    for item in merged_items[:3]:
        year = item.get("year", "")
        text = normalize_text(item.get("text", ""))
        if text:
            highlights.append(f"{year}: {text}")
    highlights_text = "; ".join(highlights)
    title = normalize_text(article.get("title", ""))
    summary = normalize_text(article.get("summary", ""))
    return (
        f"Historical 'This Day in History' magazine cover theme, date: {target_date.isoformat()}."
        f"Title theme: {title}. Summary: {summary}. Key events: {highlights_text}."
        "16:9 horizontal composition, documentary feel, historical sense, magazine cover quality, restrained lighting, realistic details."
    )


def build_generated_event_prompt(item: dict[str, Any], target_date: dt.date) -> str:
    detail = item.get("detail") or {}
    title = normalize_text(detail.get("title", ""))
    description = normalize_text(detail.get("description", ""))
    extract = normalize_text(detail.get("extract", ""))
    text = normalize_text(item.get("text", ""))
    year = item.get("year", "")
    return (
        f"Historical event scene from year {year}, set in context of {target_date.isoformat()}."
        f"Event: {text}. Title hint: {title}. Description: {description}. Background: {extract}."
        "16:9 horizontal composition, documentary style, realistic details, historical scene atmosphere."
    )


def gradio_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    api_key = os.environ.get("HF_API_TOKEN")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def extract_gradio_event_id(payload: dict[str, Any]) -> str:
    for key in ("event_id", "eventId"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    raise RuntimeError(f"Gradio response missing event id: {payload}")


def parse_gradio_result_text(text: str) -> str:
    def extract_url(value: Any) -> str:
        if isinstance(value, str) and value.strip():
            stripped = value.strip()
            if stripped.startswith("http://") or stripped.startswith("https://"):
                return stripped
            if stripped.startswith("/gradio_api/file="):
                return stripped
            if stripped.startswith("/tmp/gradio/"):
                return stripped
            return ""
        if isinstance(value, dict):
            for key in ("url", "path"):
                candidate = extract_url(value.get(key))
                if candidate:
                    return candidate
        return ""

    data_lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line.startswith("data:"):
            continue
        data_lines.append(line[5:].strip())
    for chunk in reversed(data_lines):
        try:
            payload = json.loads(chunk)
        except Exception:
            continue
        if isinstance(payload, list) and payload:
            for item in payload:
                candidate = extract_url(item)
                if candidate:
                    return candidate
        if isinstance(payload, dict):
            candidate = extract_url(payload)
            if candidate:
                return candidate
    raise RuntimeError(f"Unable to parse Gradio generation result: {text[:800]}")


def join_hf_space_url(path_or_url: str) -> str:
    if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
        return path_or_url
    if path_or_url.startswith("/tmp/gradio/"):
        return f"{Z_IMAGE_TURBO_BASE_URL}/gradio_api/file={path_or_url}"
    if path_or_url.startswith("/"):
        return f"{Z_IMAGE_TURBO_BASE_URL}{path_or_url}"
    return f"{Z_IMAGE_TURBO_BASE_URL}/{path_or_url}"


def request_gradio_generated_image(prompt: str) -> str:
    # 彻底解决每次生成同一样图片的问题：给参数注入随机的Seed，而不是写死的42
    random_seed = random.randint(1, 2147483647)
    payload = {"data": [prompt, 768, 1344, 9, random_seed, True]}
    
    start_response = requests.post(
        f"{Z_IMAGE_TURBO_BASE_URL}/gradio_api/call/generate_image",
        headers=gradio_headers(),
        json=payload,
        timeout=REQUEST_TIMEOUT * 2,
    )
    if not start_response.ok:
        body_preview = start_response.text[:600].replace("\n", " ")
        raise RuntimeError(f"Gradio start request failed: HTTP {start_response.status_code} {body_preview}")
    event_id = extract_gradio_event_id(start_response.json())
    log(f"Gradio event id: {event_id} with seed {random_seed}")
    
    result_response = requests.get(
        f"{Z_IMAGE_TURBO_BASE_URL}/gradio_api/call/generate_image/{event_id}",
        headers=gradio_headers(),
        timeout=REQUEST_TIMEOUT * 8,
    )
    if not result_response.ok:
        body_preview = result_response.text[:600].replace("\n", " ")
        raise RuntimeError(f"Gradio result request failed: HTTP {result_response.status_code} {body_preview}")
    return join_hf_space_url(parse_gradio_result_text(result_response.text))


def generate_huggingface_image(prompt: str, file_path: Path) -> str:
    # 彻底去掉复用旧图的检查逻辑，强制重载并覆盖
    log(f"Generating new image for: {file_path.name}")
    log(f"Gradio prompt: {prompt[:240]}")
    image_url = request_gradio_generated_image(prompt)
    log(f"Generated remote image URL: {image_url}")
    download_response = requests.get(image_url, headers={"User-Agent": build_user_agent()}, timeout=REQUEST_TIMEOUT * 4)
    download_response.raise_for_status()
    file_path.write_bytes(download_response.content)
    log(f"Saved generated image: {file_path}")
    return str(file_path)


def generate_huggingface_cover(article: dict[str, Any], merged_items: list[dict[str, Any]], target_date: dt.date, target_dir: Path) -> str:
    prompt = build_generated_cover_prompt(article, merged_items, target_date)
    return generate_huggingface_image(prompt, target_dir / "hf-cover.png")


def generate_huggingface_event_image(item: dict[str, Any], target_date: dt.date, target_dir: Path, index: int) -> str:
    prompt = build_generated_event_prompt(item, target_date)
    return generate_huggingface_image(prompt, target_dir / f"hf-event-{index:02d}.png")


def fetch_unsplash_or_generated_image(
    item: dict[str, Any],
    target_date: dt.date,
    target_dir: Path,
    index: int,
    used_unsplash_ids: set[str] = None
) -> str:
    if item.get("image_url"):
        log(f"Using existing image from history.com for item {index}: {item['image_url']}")
        return download_image(item["image_url"], target_dir)

    try:
        ai_image = generate_huggingface_event_image(item, target_date, target_dir, index)
        if ai_image:
            log(f"AI generated image for item {index}: {ai_image}")
            return ai_image
    except Exception as exc:
        log(f"AI image generation failed for item {index}: {exc}")

    try:
        unsplash_url = fetch_unsplash_image(item, used_unsplash_ids)
    except Exception as exc:
        log(f"Unsplash lookup failed for item {index}: {exc}")
        unsplash_url = ""
    if unsplash_url:
        log(f"Unsplash image found for item {index}: {unsplash_url}")
        return download_image(unsplash_url, target_dir)

    return ""


def download_assets(
    target_date: dt.date,
    merged_items: list[dict[str, Any]],
    lang: str,
    article: dict[str, Any] | None = None,
) -> tuple[list[str], list[str]]:
    target_dir = ASSET_ROOT / target_date.isoformat()
    target_dir.mkdir(parents=True, exist_ok=True)

    cover_url = ""
    image_urls: list[str] = []
    seen: set[str] = set()
    used_unsplash_ids: set[str] = set()

    def to_github_url(local_path_str: str) -> str:
        local_path = Path(local_path_str)
        absolute_path = local_path if local_path.is_absolute() else (Path.cwd() / local_path)
        return github_asset_url(absolute_path.relative_to(Path.cwd()))

    if article:
        if merged_items:
            try:
                cover_path = fetch_unsplash_or_generated_image(merged_items[0], target_date, target_dir, 0, used_unsplash_ids)
                cover_url = to_github_url(cover_path) if cover_path else ""
                if cover_url:
                    seen.add(cover_url)
                    log(f"Cover URL: {cover_url}")
            except Exception as exc:
                log(f"Cover image creation failed: {exc}")
                cover_url = ""
        if not cover_url:
            try:
                cover_url = to_github_url(generate_huggingface_cover(article, merged_items, target_date, target_dir))
                if cover_url:
                    seen.add(cover_url)
                    log(f"Cover URL: {cover_url}")
            except Exception as exc:
                log(f"Cover generation failed: {exc}")
                cover_url = ""

    for index, item in enumerate(merged_items[:5], start=1):
        try:
            image_path = fetch_unsplash_or_generated_image(item, target_date, target_dir, index, used_unsplash_ids)
        except Exception as exc:
            log(f"Event image generation failed for item {index} ({item.get('year')} {item.get('text', '')[:80]}): {exc}")
            image_path = ""
        if not image_path:
            continue
        github_url = to_github_url(image_path)
        if github_url in seen:
            continue
        seen.add(github_url)
        image_urls.append(github_url)
        log(f"Event image URL {index}: {github_url}")

    log(f"Generated asset summary: cover={'yes' if cover_url else 'no'}, event_images={len(image_urls)}")
    all_images = ([cover_url] if cover_url else []) + image_urls
    return all_images, image_urls


def render_wechat_html(title: str, summary: str, content_text: str, all_images: list[str]) -> str:
    paragraphs = [paragraph.strip() for paragraph in content_text.split("\n\n") if paragraph.strip()]
    cover_url = all_images[0] if all_images else ""
    body_images = all_images[1:] if len(all_images) > 1 else []
    parts = [
        "<section style=\"margin:0;background:linear-gradient(180deg,#f6efe4 0%,#fbf8f2 58%,#ffffff 100%);padding:1px;color:#1f2937;\">",
        "<section style=\"width:100%;margin:0;\">",
        "<section style=\"background:rgba(255,255,255,0.92);border:1px solid rgba(148,163,184,0.16);box-shadow:0 12px 28px rgba(15,23,42,0.06);border-radius:18px;overflow:hidden;\">",
    ]
    if cover_url:
        parts.append(
            f"<div style=\"position:relative;background:#d6d3d1;\"><img src=\"{cover_url}\" style=\"width:100%;aspect-ratio:16/9;object-fit:cover;display:block;\"></div>"
        )
    parts.extend(
        [
            "<section style=\"padding:16px 12px 10px;\">",
            "<div style=\"display:inline-block;padding:4px 10px;border-radius:999px;background:#111827;color:#f9fafb;font-size:11px;letter-spacing:0.08em;text-transform:uppercase;\">History Today</div>",
            f"<h1 style=\"font-size:29px;line-height:1.22;margin:12px 0 10px;color:#111827;font-family:Georgia,'Times New Roman',serif;\">{title}</h1>",
            f"<p style=\"font-size:15px;line-height:1.8;color:#475569;margin:0;\">{summary}</p>",
            "</section>",
            "<section style=\"padding:0 10px 12px;\">",
        ]
    )
    for index, paragraph in enumerate(paragraphs):
        parts.append(
            f"<div style=\"background:#fffdf8;border:1px solid rgba(226,232,240,0.88);border-radius:16px;padding:14px 12px;margin:0 0 12px;box-shadow:0 6px 16px rgba(15,23,42,0.035);\"><p style=\"font-size:16px;line-height:1.92;margin:0;color:#334155;\">{paragraph}</p></div>"
        )
        if index < len(body_images):
            parts.append(
                f"<div style=\"margin:0 0 14px;\"><img src=\"{body_images[index]}\" style=\"width:100%;aspect-ratio:16/9;object-fit:cover;border-radius:16px;display:block;box-shadow:0 10px 24px rgba(15,23,42,0.08);\"></div>"
            )
    parts.extend(
        [
            "</section>",
            "</section>",
            "</section>",
            "</section>",
        ]
    )
    content_html = "".join(parts)
    top_banner = (
        "<img src='https://mmbiz.qpic.cn/mmbiz_gif/3hAJnwuyZuicicZkgJBUCCaricdibomDBrTzXgUR7FJnf11qGIo8nmKt6RxibXrb5s4RFb9UZ9UOHQy7fqQyI377Licw/0?wx_fmt=gif' "
        "style='width:100%;display:block;'>"
    )
    bottom_banner = (
        "<img src='https://mmbiz.qpic.cn/mmbiz_gif/3hAJnwuyZuicicZkgJBUCCaricdibomDBrTzk57DCmhVC16o9ILH0Tn1YPEiarfLRRQSVFN2mJdeYibGnBPialPIzvojw/0?wx_fmt=gif' "
        "style='width:100%;display:block;'>"
    )
    return f"{top_banner}<section style='padding:0;'>{content_html}</section>{bottom_banner}"


def save_outputs(payload: dict[str, Any], output_dir: Path, target_date: dt.date) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"History_Today_{target_date.isoformat()}.json"
    with json_path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
    return json_path


def main() -> None:
    args = parse_args()
    target_date = resolve_target_date(args.date, args.month, args.day)
    log(f"Start run for date {target_date.isoformat()}")
    cleanup_old_assets(target_date, ASSET_ROOT, keep_days=7)

    source_results = [
        {"name": "Britannica On This Day", **fetch_britannica(target_date)},
        {"name": "Wikimedia On this day", **fetch_wikimedia(args.lang, target_date)},
        {"name": "Day in History", **fetch_dayinhistory(target_date)},
        {"name": "API Ninjas Historical Events", **fetch_api_ninjas(target_date)},
        {"name": "History.com This Day in History", **fetch_history_dot_com(target_date)},
    ]
    merged_items = merge_items(source_results, args.limit)
    if not merged_items:
        errors = [f"{item['name']}: {item.get('error', '')}" for item in source_results]
        raise RuntimeError(f"No merged items available. {' | '.join(errors)}")
    log(f"Merged unique items: {len(merged_items)}")

    enrich_item_details(merged_items, args.lang)
    merged_items = filter_safe_items(merged_items)
    if not merged_items:
        raise RuntimeError("No safe non-sensitive items remain after strict filtering.")
    stats = source_stats(source_results, merged_items)
    log(f"Source stats: {json.dumps(stats, ensure_ascii=False)}")
    prompt = build_gemini_prompt(target_date, merged_items, stats)
    try:
        article = call_gemini(prompt)
        log("Article generation: Gemini success")
    except Exception as exc:
        log(f"\n====================================")
        log(f"⚠️ 拦截触发! 使用保底逻辑 (Fallback) ⚠️")
        log(f"具体失败原因: {exc}")
        log(f"====================================\n")
        article = build_fallback_article(target_date, merged_items)

    # 在控制台打印被采用的内容结构
    log(f"\n【最终生成的文章内容结构】:")
    log(f"Title: {article.get('title')}")
    log(f"Summary: {article.get('summary')}")
    log(f"Content (前100字): {article.get('content_text', '')[:100]}...\n")

    all_images, image_urls = download_assets(target_date, merged_items, args.lang, article)
    content_html = render_wechat_html(article["title"], article["summary"], article["content_text"], all_images)
    payload = {
        "title": article["title"],
        "seo_summary": article["summary"],
        "cover": all_images,
        "wechat_html": content_html,
    }
    json_path = save_outputs(payload, Path(args.output_dir), target_date)
    log(f"Saved JSON to {json_path}")


if __name__ == "__main__":
    main()
