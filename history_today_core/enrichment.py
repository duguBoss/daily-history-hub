from __future__ import annotations

from typing import Any
from urllib.parse import quote

import requests

from .common import build_user_agent, normalize_text
from .constants import REQUEST_TIMEOUT

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
