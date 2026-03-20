from __future__ import annotations

from typing import Any

from .common import log, normalize_text
from .constants import CHINA_RELATED_PATTERNS, SENSITIVE_TOPIC_PATTERNS

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
