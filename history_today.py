from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import mimetypes
import os
import re
import shutil
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

import pytz
import requests


SHANGHAI_TZ = pytz.timezone("Asia/Shanghai")
REQUEST_TIMEOUT = 30
DEFAULT_WIKIPEDIA_LANG = os.environ.get("WIKIPEDIA_LANG", "zh")
DEFAULT_LIMIT = int(os.environ.get("HISTORY_TODAY_LIMIT", "18"))
DEFAULT_OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", "output"))
ASSET_ROOT = Path("assets") / "generated" / "history_today"
PRIMARY_GEMINI_MODEL = "gemini-3.1-pro-preview"
FALLBACK_GEMINI_MODEL = "gemini-3.1-flash-lite-preview"
SOURCE_WIKIMEDIA = "wikimedia"
SOURCE_DAYINHISTORY = "dayinhistory"
SOURCE_API_NINJAS = "api_ninjas"
UNSPLASH_SEARCH_URL = "https://api.unsplash.com/search/photos"
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
    "qing dynasty",
    "ming dynasty",
    "yuan dynasty",
    "han dynasty",
    "tang dynasty",
    "song dynasty",
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


def make_event_key(year: Any, text: str) -> str:
    lowered = normalize_text(text).lower()
    simplified = "".join(ch for ch in lowered if ch.isalnum() or ch.isspace())
    return f"{year}|{simplified}"


def is_china_related_text(text: str) -> bool:
    lowered = normalize_text(text).lower()
    return any(pattern in lowered for pattern in CHINA_RELATED_PATTERNS)


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
    return {"ok": True, "items": items, "endpoint": url}


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
                    "detail": {},
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

    ordered = sorted(merged.values(), key=lambda item: (-len(item["sources"]), str(item.get("year") or ""), item["text"]))
    results = []
    for item in ordered:
        if is_china_related_item(item):
            continue
        image_url = ""
        for page in item.get("pages", []):
            if page.get("thumbnail"):
                image_url = page["thumbnail"]
                break
        item["image_url"] = image_url
        item["source_confidence"] = infer_confidence(item)
        results.append(item)
        if len(results) >= limit:
            break
    return results


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
        "You are writing a finished WeChat article in Simplified Chinese.\n"
        "Use only the facts in the JSON payload. Do not invent details.\n"
        "Exclude anything related to China, CCP, PRC, ROC, Hong Kong, Macau, Taiwan, Tibet, Xinjiang, or Chinese dynasties.\n"
        "Write in a click-enticing style, but remain factual.\n"
        "Return valid JSON only with this schema:\n"
        "{\n"
        '  "title": "click-enticing Chinese title under 22 chars",\n'
        '  "summary": "Chinese summary no more than 50 characters",\n'
        '  "content_text": "complete Chinese article body with 4-6 paragraphs separated by \\n\\n"\n'
        "}\n"
        "Do not output markdown. Do not output HTML. Do not mention filtering.\n"
        f"Target date: {target_date.isoformat()}\n"
        f"Source stats: {json.dumps(stats, ensure_ascii=False)}\n"
        f"Merged items: {json.dumps(compact_items, ensure_ascii=False)}"
    )


def validate_gemini_result(result: dict[str, Any]) -> dict[str, Any]:
    for key in ("title", "summary", "content_text"):
        value = result.get(key, "")
        if not isinstance(value, str) or not value.strip():
            raise RuntimeError(f"Gemini output missing {key}")
        if is_china_related_text(value):
            raise RuntimeError("Gemini output contains filtered content.")
    if len(result["summary"].strip()) > 50:
        raise RuntimeError("Gemini output summary exceeds 50 characters.")
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
            "generationConfig": {"temperature": 0.6, "responseMimeType": "application/json"},
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
    return validate_gemini_result(json.loads(text))


def call_gemini(prompt: str) -> dict[str, Any]:
    errors: list[str] = []
    for model_name in (PRIMARY_GEMINI_MODEL, FALLBACK_GEMINI_MODEL):
        try:
            return call_gemini_once(prompt, model_name)
        except Exception as exc:
            errors.append(f"{model_name}: {exc}")
    raise RuntimeError(" | ".join(errors))


def build_fallback_article(target_date: dt.date, merged_items: list[dict[str, Any]]) -> dict[str, Any]:
    selected = merged_items[:6]
    paragraphs = [
        f"{target_date.month}月{target_date.day}日这一天，历史留下了几段气质截然不同的切片，权力更替、突发事件和人物命运在同一天交错出现。"
    ]
    for item in selected:
        detail = item.get("detail") or {}
        detail_text = detail.get("extract") or detail.get("description") or ""
        if detail_text:
            paragraphs.append(f"{item['year']}年，{item['text']}。维基页面补充提到：{detail_text}")
        else:
            paragraphs.append(f"{item['year']}年，{item['text']}。")
    return {
        "title": f"{target_date.month}月{target_date.day}日发生了什么",
        "summary": "这一天并不平静，几段历史在同日交错。",
        "content_text": "\n\n".join(paragraphs),
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


def fetch_unsplash_image(item: dict[str, Any]) -> str:
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
        urls = result.get("urls") or {}
        alt_description = normalize_text(result.get("alt_description", "") or result.get("description", ""))
        text_blob = normalize_text(f"{query} {alt_description}").lower()
        if "history" not in text_blob and "historic" not in text_blob:
            continue
        for key in ("raw", "full", "regular"):
            if urls.get(key):
                extra = {"q": "80", "fm": "jpg"}
                separator = "&" if "?" in urls[key] else "?"
                return f"{urls[key]}{separator}{urlencode(extra)}"
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
    if not file_path.exists():
        file_path.write_bytes(response.content)
    return str(file_path)


def resolve_item_image_url(item: dict[str, Any], lang: str) -> str:
    if item.get("image_url"):
        return item["image_url"]
    try:
        image_url = fetch_wikimedia_commons_image(item, lang)
    except Exception:
        image_url = ""
    if image_url:
        return image_url
    for page in item.get("pages", []):
        if page.get("thumbnail"):
            return page["thumbnail"]
    for page in item.get("pages", []):
        try:
            image_url = fetch_pageimages_image(page.get("title", ""), lang)
        except Exception:
            image_url = ""
        if image_url:
            return image_url
    for page in item.get("pages", []):
        try:
            image_url = fetch_page_embedded_image(page.get("title", ""), lang)
        except Exception:
            image_url = ""
        if image_url:
            return image_url
    for page in item.get("pages", []):
        try:
            image_url = fetch_detail_page_image(page.get("url", ""))
        except Exception:
            image_url = ""
        if image_url:
            return image_url
    for page in item.get("pages", []):
        try:
            image_url = fetch_summary_image(page.get("title", ""), lang)
        except Exception:
            image_url = ""
        if image_url:
            return image_url
    try:
        image_url = fetch_unsplash_image(item)
    except Exception:
        image_url = ""
    if image_url:
        return image_url
    return ""


def download_assets(target_date: dt.date, merged_items: list[dict[str, Any]], lang: str) -> tuple[str, list[str]]:
    target_dir = ASSET_ROOT / target_date.isoformat()
    target_dir.mkdir(parents=True, exist_ok=True)

    cover_url = ""
    image_urls: list[str] = []
    seen: set[str] = set()

    for item in merged_items:
        source_url = resolve_item_image_url(item, lang)
        if not source_url or source_url in seen:
            continue
        seen.add(source_url)
        try:
            local_path = Path(download_image(source_url, target_dir))
            github_url = github_asset_url(local_path.relative_to(Path.cwd()))
        except Exception:
            continue
        if not cover_url:
            cover_url = github_url
            continue
        image_urls.append(github_url)
        if len(image_urls) >= 7:
            break

    return cover_url, image_urls


def render_wechat_html(title: str, summary: str, content_text: str, cover_url: str, image_urls: list[str]) -> str:
    paragraphs = [paragraph.strip() for paragraph in content_text.split("\n\n") if paragraph.strip()]
    parts = [
        "<section style=\"max-width:760px;margin:0 auto;padding:24px 18px;background:#f7f3ea;color:#1f2937;\">",
        f"<h1 style=\"font-size:30px;line-height:1.35;margin:0 0 16px 0;color:#111827;\">{title}</h1>",
        f"<p style=\"font-size:15px;line-height:1.8;color:#4b5563;margin:0 0 20px 0;\">{summary}</p>",
    ]
    if cover_url:
        parts.append(f"<p style=\"margin:0 0 22px 0;\"><img src=\"{cover_url}\" style=\"width:100%;border-radius:12px;display:block;\"></p>")
    for index, paragraph in enumerate(paragraphs):
        parts.append(f"<p style=\"font-size:17px;line-height:1.95;margin:0 0 18px 0;\">{paragraph}</p>")
        if index < len(image_urls):
            parts.append(
                f"<p style=\"margin:0 0 22px 0;\"><img src=\"{image_urls[index]}\" style=\"width:100%;border-radius:12px;display:block;\"></p>"
            )
    parts.append("</section>")
    return "".join(parts)


def save_outputs(payload: dict[str, Any], output_dir: Path, target_date: dt.date) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"History_Today_{target_date.isoformat()}.json"
    with json_path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
    return json_path


def main() -> None:
    args = parse_args()
    target_date = resolve_target_date(args.date, args.month, args.day)
    cleanup_old_assets(target_date, ASSET_ROOT, keep_days=7)

    source_results = [
        {"name": "Wikimedia On this day", **fetch_wikimedia(args.lang, target_date)},
        {"name": "Day in History", **fetch_dayinhistory(target_date)},
        {"name": "API Ninjas Historical Events", **fetch_api_ninjas(target_date)},
    ]
    merged_items = merge_items(source_results, args.limit)
    if not merged_items:
        errors = [f"{item['name']}: {item.get('error', '')}" for item in source_results]
        raise RuntimeError(f"No merged items available. {' | '.join(errors)}")

    enrich_item_details(merged_items, args.lang)
    stats = source_stats(source_results, merged_items)
    prompt = build_gemini_prompt(target_date, merged_items, stats)
    try:
        article = call_gemini(prompt)
    except Exception:
        article = build_fallback_article(target_date, merged_items)

    cover_url, image_urls = download_assets(target_date, merged_items, args.lang)
    if not cover_url:
        raise RuntimeError("No usable image found after fetching detail pages and summary images.")
    content_html = render_wechat_html(article["title"], article["summary"], article["content_text"], cover_url, image_urls)
    payload = {
        "title": article["title"],
        "summary": article["summary"],
        "content": content_html,
        "cover": cover_url,
        "images": image_urls,
        "items": merged_items,
    }
    json_path = save_outputs(payload, Path(args.output_dir), target_date)
    print(f"Saved JSON to {json_path}")


if __name__ == "__main__":
    main()
