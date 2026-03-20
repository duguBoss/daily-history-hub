from __future__ import annotations

import datetime as dt
import os
from typing import Any
from urllib.parse import quote

import requests

from .common import build_user_agent, log, normalize_text
from .constants import MONTH_NAMES, REQUEST_TIMEOUT, SOURCE_API_NINJAS, SOURCE_DAYINHISTORY, SOURCE_WIKIMEDIA
from .filters import is_china_related_item, normalize_page

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
    log(f"\n{'='*80}")
    log(f"[2] Wikimedia On This Day")
    log(f"    Lang: {lang}, Date: {target_date.isoformat()}")
    log(f"{'='*80}")
    last_error: Exception | None = None
    for idx, (url, headers) in enumerate(wikimedia_candidates(lang, target_date), 1):
        try:
            log(f"    → Trying endpoint {idx}: {url}")
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
            log(f"    ✓ Success: {len(items)} items from {len(payload.get('selected', []) + payload.get('events', []))} entries")
            return {"ok": True, "items": items, "endpoint": url}
        except Exception as exc:
            log(f"    ⚠ Endpoint {idx} failed: {exc}")
            last_error = exc
    log(f"    ❌ All endpoints failed")
    return {"ok": False, "items": [], "endpoint": "", "error": str(last_error) if last_error else "unknown"}


def fetch_dayinhistory(target_date: dt.date) -> dict[str, Any]:
    month_name = MONTH_NAMES[target_date.month]
    log(f"\n{'='*80}")
    log(f"[4] Day in History API")
    log(f"    Date: {month_name} {target_date.day}")
    log(f"{'='*80}")
    headers = {"Accept": "application/json", "User-Agent": build_user_agent()}
    items: list[dict[str, Any]] = []
    failures: list[str] = []
    for category in ("events", "births", "deaths"):
        for base_url in ("https://api.dayinhistory.com/v1", "https://api.dayinhistory.dev/v1"):
            url = f"{base_url}/{category}/{month_name}/{target_date.day}/"
            try:
                log(f"    → Trying: {url}")
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
                log(f"    ✓ {category}: {len(results)} results from {base_url}")
                break
            except Exception as exc:
                failures.append(f"{category} via {base_url}: {exc}")
                log(f"    ⚠ {category}/{base_url}: {exc}")
    if items:
        log(f"    ✓ Total: {len(items)} items")
    else:
        log(f"    ❌ All endpoints failed")
    return {
        "ok": bool(items),
        "items": items,
        "endpoint": "https://api.dayinhistory.com/v1/ or https://api.dayinhistory.dev/v1/",
        "error": "; ".join(failures),
    }


def fetch_api_ninjas(target_date: dt.date) -> dict[str, Any]:
    log(f"\n{'='*80}")
    log(f"[5] API Ninjas Historical Events")
    log(f"    Date: {target_date.month}/{target_date.day}")
    log(f"{'='*80}")
    api_key = os.environ.get("API_NINJAS_API_KEY")
    if not api_key:
        log(f"    ❌ Missing API_NINJAS_API_KEY")
        return {"ok": False, "items": [], "endpoint": "", "error": "Missing API_NINJAS_API_KEY"}
    url = f"https://api.api-ninjas.com/v1/historicalevents?month={target_date.month}&day={target_date.day}"
    log(f"    → URL: {url}")
    try:
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
        log(f"    ✓ Success: {len(items)} items extracted")
        if items:
            log(f"    Sample items:")
            for idx, item in enumerate(items[:3]):
                log(f"      [{idx}] {item['year']}: {item['text'][:60]}...")
        return {"ok": True, "items": items, "endpoint": url}
    except Exception as exc:
        log(f"    ❌ Request failed: {exc}")
        return {"ok": False, "items": [], "endpoint": url, "error": str(exc)}
