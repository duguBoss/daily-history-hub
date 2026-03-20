from __future__ import annotations

import datetime as dt
import html
import re
from typing import Any

import requests
from playwright.sync_api import sync_playwright

from .common import log, normalize_text
from .constants import MONTH_NAMES, REQUEST_TIMEOUT, SOURCE_BRITANNICA
from .filters import is_china_related_item

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
    log(f"\n{'='*80}")
    log(f"[1] Britannica On This Day")
    log(f"    URL: {url}")
    log(f"{'='*80}")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-web-security",
                ],
            )
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
                locale="en-US",
                timezone_id="America/New_York",
                viewport={"width": 1920, "height": 1080},
                extra_http_headers={
                    "Accept-Language": "en-US,en;q=0.9",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                },
            )
            page = context.new_page()
            log(f"    → Navigating to Britannica (Playwright, timeout=60s)...")
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3000)
            selectors = [".event-item", ".on-this-day-item", "[data-testid='event-item']", "article.event"]
            html_content = None
            for selector in selectors:
                try:
                    page.wait_for_selector(selector, timeout=3000)
                    html_content = page.content()
                    log(f"    ✓ Found content with selector: {selector}")
                    break
                except:
                    log(f"    ⚠ Selector '{selector}' not found, trying next...")
            if not html_content:
                log(f"    ⚠ No specific selector found, using page content anyway")
                html_content = page.content()
            browser.close()
            log(f"    ✓ Fetched {len(html_content)} chars via Playwright")
    except Exception as exc:
        log(f"    ❌ Playwright failed: {exc}")
        return {"ok": False, "items": [], "endpoint": url, "error": f"Playwright error: {exc}"}

    lines = html_to_lines(html_content)
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
