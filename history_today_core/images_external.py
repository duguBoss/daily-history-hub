from __future__ import annotations

import os
import random
import re
from typing import Any
from urllib.parse import urlencode

import requests

from .common import build_user_agent, normalize_text
from .constants import COMMONS_API_URL, OPENVERSE_IMAGES_URL, REQUEST_TIMEOUT, UNSPLASH_SEARCH_URL

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
