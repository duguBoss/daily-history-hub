from __future__ import annotations

import datetime as dt
import json
import os
import re
from typing import Any

import requests

from .common import build_user_agent, log, normalize_text
from .constants import MONTH_NAMES, PRIMARY_GEMINI_MODEL, REQUEST_TIMEOUT, SOURCE_HISTORY_DOT_COM
from .filters import is_china_related_text

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


def fetch_history_dot_com(target_date: dt.date) -> dict[str, Any]:
    month_name = MONTH_NAMES[target_date.month].lower()
    url = f"https://r.jina.ai/https://www.history.com/this-day-in-history/{month_name}-{target_date.day}"
    headers = {
        "Accept": "text/plain",
        "User-Agent": build_user_agent(),
        "x-target-url": f"https://www.history.com/this-day-in-history/{month_name}-{target_date.day}",
    }
    log(f"\n{'='*80}")
    log(f"[3] History.com This Day in History")
    log(f"    URL: {url}")
    log(f"{'='*80}")
    try:
        response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        raw_text = response.text.strip()
        if not raw_text:
            log(f"    ❌ Empty response from jina.ai")
            return {"ok": False, "items": [], "endpoint": url, "error": "Empty response from jina.ai"}

        log(f"    ✓ Fetched {len(raw_text)} chars from jina.ai")

        also_on_this_day_marker = "Also on This Day in History"
        if also_on_this_day_marker in raw_text:
            raw_text = raw_text[raw_text.index(also_on_this_day_marker):]
            log(f"    → Extracted '{also_on_this_day_marker}' section ({len(raw_text)} chars)")
        else:
            log(f"    ⚠ '{also_on_this_day_marker}' marker not found, using full content")

        log(f"\n--- History.com Content for Gemini (first 1000 chars) ---")
        log(raw_text[:1000])
        log(f"... (truncated for display, total {len(raw_text)} chars)")
        log(f"-------------------------------------------\n")

        try:
            items = extract_history_dot_com_with_gemini(raw_text, target_date)
            log(f"    ✓ Extracted {len(items)} items via Gemini")
            return {"ok": bool(items), "items": items, "endpoint": url, "error": "" if items else "No items parsed"}
        except Exception as exc:
            log(f"    ❌ Gemini extraction failed: {exc}")
            return {"ok": False, "items": [], "endpoint": url, "error": str(exc)}
    except Exception as exc:
        log(f"    ❌ Request failed: {exc}")
        return {"ok": False, "items": [], "endpoint": url, "error": str(exc)}


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

    log(f"\n================ History.com Gemini Extraction Raw Output ================")
    log(f"Text length: {len(text)} characters")
    log(f"Full text content:")
    log(text)
    log("==================================================================\n")

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
        log(f"Parsed is not a list, type={type(parsed)}, value={str(parsed)[:200]}")
        raise RuntimeError(f"Expected JSON array from Gemini, got {type(parsed)}")

    log(f"Successfully parsed {len(parsed)} items from Gemini response")
    if not parsed:
        log("Parsed list is empty")
        return []
    log(f"Parsed first item type: {type(parsed[0])}, value: {str(parsed[0])}")
    log(f"All parsed items: {json.dumps(parsed, ensure_ascii=False)}")

    items: list[dict[str, Any]] = []
    for idx, entry in enumerate(parsed):
        log(f"Processing entry {idx}: type={type(entry)}, value={str(entry)}")
        if not isinstance(entry, dict):
            log(f"Skipping entry {idx} - not a dict")
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
