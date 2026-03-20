from __future__ import annotations

import datetime as dt
import json
import os
import re
from typing import Any

import requests

from .common import build_user_agent, log, normalize_text
from .constants import MONTH_NAMES, PRIMARY_GEMINI_MODEL, REQUEST_TIMEOUT, SOURCE_HISTORY_DOT_COM
from .filters import is_china_related_text, is_sensitive_topic_text

EXTRACT_HISTORY_DOT_COM_PROMPT = """Extract events from the section 'Also on This Day in History'.
Return only a JSON array of objects with fields: year, text, image_url.
Rules:
- year: four-digit year at the start of each event
- text: event description
- image_url: image URL if present, else empty string
- skip China-related, political, war/conflict events
Target date: {target_date}
Raw text:
{raw_text}
"""


def _render_extract_prompt(raw_text: str, target_date: dt.date) -> str:
    # Use replace instead of str.format to avoid JSON braces in prompt causing KeyError.
    return (
        EXTRACT_HISTORY_DOT_COM_PROMPT.replace("{target_date}", target_date.isoformat())
        .replace("{raw_text}", raw_text)
    )


def _merge_unique_items(*item_lists: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for items in item_lists:
        for item in items:
            key = (str(item.get("year", "")), normalize_text(item.get("text", "")).lower())
            if not key[0] or not key[1] or key in seen:
                continue
            seen.add(key)
            merged.append(item)
    return merged


def extract_history_dot_com_locally(raw_text: str, target_date: dt.date) -> list[dict[str, Any]]:
    event_block_pattern = re.compile(r"(?ms)^\[(\d{4})\s+(.*?)(?=^\[\d{4}\s+|\Z)")
    image_pattern = re.compile(r"!\[[^\]]*\]\((https?://[^)\s]+)\)", re.IGNORECASE)
    source_url = f"https://www.history.com/this-day-in-history/{MONTH_NAMES[target_date.month].lower()}-{target_date.day}"
    items: list[dict[str, Any]] = []

    for match in event_block_pattern.finditer(raw_text):
        year, block = match.group(1), match.group(2)
        image_match = image_pattern.search(block)
        image_url = image_match.group(1) if image_match else ""

        text_val = image_pattern.sub(" ", block)
        text_val = re.sub(r"\]\((https?://[^)\s]+)\)", " ", text_val)
        text_val = re.sub(r"\b\d{1,2}:\d{2}\s*m\s*read\b", " ", text_val, flags=re.IGNORECASE)
        text_val = text_val.replace("[", " ").replace("]", " ")
        text_val = normalize_text(text_val)

        if not text_val:
            continue
        if is_china_related_text(text_val) or is_sensitive_topic_text(text_val):
            continue

        items.append(
            {
                "source": SOURCE_HISTORY_DOT_COM,
                "category": "events",
                "year": year,
                "text": text_val,
                "image_url": image_url,
                "source_url": source_url,
                "pages": [],
            }
        )

    return items


def fetch_history_dot_com(target_date: dt.date) -> dict[str, Any]:
    month_name = MONTH_NAMES[target_date.month].lower()
    url = f"https://r.jina.ai/https://www.history.com/this-day-in-history/{month_name}-{target_date.day}"
    headers = {
        "Accept": "text/plain",
        "User-Agent": build_user_agent(),
        "x-target-url": f"https://www.history.com/this-day-in-history/{month_name}-{target_date.day}",
    }
    log(f"\n{'='*80}")
    log("[3] History.com This Day in History")
    log(f"    URL: {url}")
    log(f"{'='*80}")

    try:
        response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        raw_text = response.text.strip()
        if not raw_text:
            return {"ok": False, "items": [], "endpoint": url, "error": "Empty response from jina.ai"}

        log(f"    Fetched {len(raw_text)} chars from jina.ai")
        marker = "Also on This Day in History"
        if marker in raw_text:
            raw_text = raw_text[raw_text.index(marker) :]
            log(f"    Extracted '{marker}' section ({len(raw_text)} chars)")

        local_items = extract_history_dot_com_locally(raw_text, target_date)
        log(f"    Local parser extracted {len(local_items)} items")

        gemini_items: list[dict[str, Any]] = []
        gemini_error = ""
        try:
            gemini_items = extract_history_dot_com_with_gemini(raw_text, target_date)
            log(f"    Gemini extracted {len(gemini_items)} items")
        except Exception as exc:
            gemini_error = str(exc)
            log(f"    Gemini extraction failed, using local parser fallback: {gemini_error}")

        merged_items = _merge_unique_items(local_items, gemini_items)
        if merged_items:
            return {"ok": True, "items": merged_items, "endpoint": url, "error": ""}

        err = gemini_error or "No items parsed"
        return {"ok": False, "items": [], "endpoint": url, "error": err}
    except Exception as exc:
        return {"ok": False, "items": [], "endpoint": url, "error": str(exc)}


def extract_history_dot_com_with_gemini(raw_text: str, target_date: dt.date) -> list[dict[str, Any]]:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("Missing GEMINI_API_KEY")

    prompt = _render_extract_prompt(raw_text, target_date)
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
        raise RuntimeError("Gemini returned empty text")

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        json_match = re.search(r"\[.*\]", text, re.DOTALL)
        if not json_match:
            raise RuntimeError("Gemini output is not valid JSON")
        parsed = json.loads(json_match.group(0))

    if not isinstance(parsed, list):
        raise RuntimeError(f"Expected JSON array from Gemini, got {type(parsed)}")

    source_url = f"https://www.history.com/this-day-in-history/{MONTH_NAMES[target_date.month].lower()}-{target_date.day}"
    items: list[dict[str, Any]] = []
    for entry in parsed:
        if not isinstance(entry, dict):
            continue
        year = str(entry.get("year", "")).strip()
        text_val = normalize_text(str(entry.get("text", "")).strip())
        image_url = str(entry.get("image_url", "") or "").strip()
        if not year or not text_val:
            continue
        if is_china_related_text(text_val) or is_sensitive_topic_text(text_val):
            continue
        items.append(
            {
                "source": SOURCE_HISTORY_DOT_COM,
                "category": "events",
                "year": year,
                "text": text_val,
                "image_url": image_url,
                "source_url": source_url,
                "pages": [],
            }
        )

    return items
