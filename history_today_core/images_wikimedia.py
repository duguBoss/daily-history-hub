from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

import requests

from .common import build_user_agent
from .constants import COMMONS_API_URL, REQUEST_TIMEOUT

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
