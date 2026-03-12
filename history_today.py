from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any

import pytz
import requests


SHANGHAI_TZ = pytz.timezone("Asia/Shanghai")
REQUEST_TIMEOUT = 30
DEFAULT_WIKIPEDIA_LANG = os.environ.get("WIKIPEDIA_LANG", "zh")
DEFAULT_LIMIT = int(os.environ.get("HISTORY_TODAY_LIMIT", "18"))
DEFAULT_OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", "output"))
DEFAULT_GEMINI_MODEL = "gemini-3-pro-preview"
DEFAULT_GEMINI_FALLBACK_MODEL = "gemini-2.5-flash-lite-preview-09-2025"
SOURCE_WIKIMEDIA = "wikimedia"
SOURCE_DAYINHISTORY = "dayinhistory"
SOURCE_API_NINJAS = "api_ninjas"
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
    "中国",
    "中华人民共和国",
    "中共",
    "中国共产党",
    "中華人民共和國",
    "中華民國",
    "北京",
    "上海",
    "香港",
    "澳门",
    "澳門",
    "台湾",
    "台灣",
    "台北",
    "西藏",
    "新疆",
]


def build_user_agent() -> str:
    repository = os.environ.get("GITHUB_REPOSITORY", "duguBoss/daily-history-hub")
    contact = os.environ.get("WIKIMEDIA_CONTACT", "https://github.com/duguBoss/daily-history-hub")
    return f"daily-history-hub/1.0 ({contact}; repo={repository})"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Aggregate on-this-day data and produce a daily brief.")
    parser.add_argument("--date", help="Target date in YYYY-MM-DD format.")
    parser.add_argument("--month", type=int, help="Target month, used with --day.")
    parser.add_argument("--day", type=int, help="Target day, used with --month.")
    parser.add_argument("--lang", default=DEFAULT_WIKIPEDIA_LANG, help="Wikipedia language edition. Default: zh")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="Maximum number of merged events.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Directory for generated files.")
    return parser.parse_args()


def resolve_target_date(
    date_arg: str | None,
    month_arg: int | None,
    day_arg: int | None,
) -> dt.date:
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
    return {
        "title": page.get("normalizedtitle") or titles.get("normalized") or page.get("title", ""),
        "url": desktop.get("page") or mobile.get("page", ""),
        "description": page.get("description", ""),
        "extract": page.get("extract", ""),
        "thumbnail": thumbnail.get("source", ""),
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
        return [
            (
                f"https://api.wikimedia.org/feed/v1/wikipedia/{lang}/onthisday/all/{month}/{day}",
                headers,
            )
        ]
    return [
        (
            f"https://{lang}.wikipedia.org/api/rest_v1/feed/onthisday/all/{month}/{day}",
            headers,
        ),
        (
            f"https://api.wikimedia.org/feed/v1/wikipedia/{lang}/onthisday/all/{month}/{day}",
            headers,
        ),
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
                    items.append(
                        {
                            "source": SOURCE_WIKIMEDIA,
                            "category": category,
                            "year": entry.get("year"),
                            "text": normalize_text(entry.get("text", "")),
                            "source_url": url,
                            "pages": [page for page in pages if page["title"] or page["url"]],
                        }
                    )
            filtered_items = [item for item in items if not is_china_related_item(item)]
            return {"ok": True, "items": filtered_items, "endpoint": url}
        except Exception as exc:
            last_error = exc
    return {"ok": False, "items": [], "endpoint": "", "error": str(last_error) if last_error else "unknown"}


def fetch_dayinhistory(target_date: dt.date) -> dict[str, Any]:
    month_name = MONTH_NAMES[target_date.month]
    auth = os.environ.get("DAYINHISTORY_API_KEY")
    headers = {"Accept": "application/json", "User-Agent": build_user_agent()}
    if auth:
        headers["Authorization"] = f"Bearer {auth}"

    items: list[dict[str, Any]] = []
    failures: list[str] = []
    api_bases = ["https://api.dayinhistory.com/v1", "https://api.dayinhistory.dev/v1"]
    categories = ("events", "births", "deaths")
    for category in categories:
        for base_url in api_bases:
            url = f"{base_url}/{category}/{month_name}/{target_date.day}/"
            try:
                response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
                response.raise_for_status()
                payload = response.json()
                results = []
                if isinstance(payload, list):
                    results = payload
                elif isinstance(payload, dict):
                    for key in ("data", "results", "events", "births", "deaths"):
                        if isinstance(payload.get(key), list):
                            results = payload[key]
                            break
                for entry in results:
                    text = normalize_text(
                        entry.get("event")
                        or entry.get("description")
                        or entry.get("content")
                        or entry.get("text")
                        or entry.get("title")
                        or ""
                    )
                    year = entry.get("year") or entry.get("date") or entry.get("birth_year") or entry.get("death_year")
                    items.append(
                        {
                            "source": SOURCE_DAYINHISTORY,
                            "category": category,
                            "year": year,
                            "text": text,
                            "source_url": url,
                            "pages": [],
                        }
                    )
                break
            except Exception as exc:
                failures.append(f"{category} via {base_url}: {exc}")

    filtered_items = [item for item in items if item["text"] and not is_china_related_item(item)]
    return {
        "ok": bool(filtered_items),
        "items": filtered_items,
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
    payload = response.json()
    items = [
        {
            "source": SOURCE_API_NINJAS,
            "category": "events",
            "year": entry.get("year"),
            "text": normalize_text(entry.get("event", "")),
            "source_url": url,
            "pages": [],
        }
        for entry in payload
        if normalize_text(entry.get("event", ""))
    ]
    filtered_items = [item for item in items if not is_china_related_item(item)]
    return {"ok": True, "items": filtered_items, "endpoint": url}


def infer_confidence(item: dict[str, Any]) -> str:
    source_count = len(item["sources"])
    if source_count >= 3:
        return "high"
    if source_count == 2:
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

    ordered = sorted(
        merged.values(),
        key=lambda item: (-len(item["sources"]), str(item.get("year") or ""), item["text"]),
    )
    results: list[dict[str, Any]] = []
    for item in ordered:
        if is_china_related_item(item):
            continue
        item["source_confidence"] = infer_confidence(item)
        image_url = ""
        for page in item.get("pages", []):
            if page.get("thumbnail"):
                image_url = page["thumbnail"]
                break
        item["image_url"] = image_url
        results.append(item)
        if len(results) >= limit:
            break
    return results


def source_stats(source_results: list[dict[str, Any]], merged_items: list[dict[str, Any]]) -> dict[str, Any]:
    per_source = {}
    for result in source_results:
        endpoint = result.get("endpoint", "")
        items = result.get("items", [])
        per_source[result.get("name", endpoint or "unknown")] = {
            "ok": result.get("ok", False),
            "item_count": len(items),
            "endpoint": endpoint,
            "error": result.get("error", ""),
        }

    agreement = Counter(len(item["sources"]) for item in merged_items)
    return {
        "sources": per_source,
        "merged_count": len(merged_items),
        "agreement_breakdown": dict(sorted(agreement.items())),
    }


def select_cover_image(merged_items: list[dict[str, Any]]) -> str:
    for item in merged_items:
        if item.get("image_url"):
            return item["image_url"]
    return ""


def build_gemini_prompt(target_date: dt.date, merged_items: list[dict[str, Any]], stats: dict[str, Any]) -> str:
    compact_items = [
        {
            "year": item["year"],
            "text": item["text"],
            "categories": item["categories"],
            "sources": item["sources"],
            "page_title": item["pages"][0]["title"] if item["pages"] else "",
            "page_url": item["pages"][0]["url"] if item["pages"] else "",
            "image_url": item.get("image_url", ""),
            "source_confidence": item.get("source_confidence", "low"),
        }
        for item in merged_items
    ]

    return (
        "You are a meticulous history editor and viral social copywriter. "
        "Use only the facts provided in the JSON payload. Do not invent details, dates, or names. "
        "Produce Simplified Chinese output. "
        "Exclude anything related to China, the Chinese Communist Party, PRC, ROC, Hong Kong, Macau, Taiwan, Tibet, Xinjiang, or Chinese dynasties. "
        "If an item is even potentially related to those topics, do not include it.\n\n"
        "Return valid JSON only with this schema:\n"
        "{\n"
        '  "headline": "a punchy click-enticing Chinese title under 22 chars",\n'
        '  "summary": "80-140 Chinese characters, vivid and curiosity-driven but factual",\n'
        '  "selection_notes": ["note1", "note2"],\n'
        '  "highlights": [\n'
        "    {\n"
        '      "year": "string",\n'
        '      "title": "short click-enticing Chinese subtitle",\n'
        '      "story": "2-3 Chinese sentences based strictly on the source facts",\n'
        '      "source_confidence": "high|medium|low",\n'
        '      "source_basis": "brief Chinese note explaining agreement between sources"\n'
        "    }\n"
        "  ],\n"
        '  "births_digest": ["..."],\n'
        '  "deaths_digest": ["..."],\n'
        '  "holidays_digest": ["..."]\n'
        "}\n\n"
        "Headline and summary should feel compelling, with strong curiosity hooks, but must remain factual.\n"
        "Never mention China-related content in any field.\n"
        f"Target date: {target_date.isoformat()}\n"
        f"Source stats: {json.dumps(stats, ensure_ascii=False)}\n"
        f"Merged items: {json.dumps(compact_items, ensure_ascii=False)}"
    )


def call_gemini_once(prompt: str, model_name: str) -> dict[str, Any]:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("Missing GEMINI_API_KEY")

    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model_name}:generateContent"
    )
    response = requests.post(
        url,
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        },
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.5,
                "responseMimeType": "application/json",
            },
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
    result = json.loads(text)
    text_fields = [result.get("headline", ""), result.get("summary", "")]
    text_fields.extend(result.get("selection_notes", []))
    text_fields.extend(result.get("births_digest", []))
    text_fields.extend(result.get("deaths_digest", []))
    text_fields.extend(result.get("holidays_digest", []))
    for highlight in result.get("highlights", []):
        text_fields.extend(
            [
                highlight.get("year", ""),
                highlight.get("title", ""),
                highlight.get("story", ""),
                highlight.get("source_basis", ""),
            ]
        )
    if any(is_china_related_text(value) for value in text_fields if isinstance(value, str)):
        raise RuntimeError("Gemini output contains filtered China-related content.")
    return result


def call_gemini(prompt: str) -> dict[str, Any]:
    primary_model = DEFAULT_GEMINI_MODEL
    fallback_model = DEFAULT_GEMINI_FALLBACK_MODEL
    errors: list[str] = []

    for model_name in [primary_model, fallback_model]:
        if not model_name:
            continue
        try:
            return call_gemini_once(prompt, model_name)
        except Exception as exc:
            errors.append(f"{model_name}: {exc}")

    raise RuntimeError(" | ".join(errors))


def build_fallback_editorial(target_date: dt.date, merged_items: list[dict[str, Any]]) -> dict[str, Any]:
    highlights = []
    births_digest: list[str] = []
    deaths_digest: list[str] = []
    holidays_digest: list[str] = []

    for item in merged_items:
        category_set = set(item["categories"])
        if "births" in category_set and len(births_digest) < 5:
            births_digest.append(f"{item['year']}: {item['text']}")
            continue
        if "deaths" in category_set and len(deaths_digest) < 5:
            deaths_digest.append(f"{item['year']}: {item['text']}")
            continue
        if "holidays" in category_set and len(holidays_digest) < 5:
            holidays_digest.append(item["text"])
            continue
        if len(highlights) < 8:
            highlights.append(
                {
                    "year": str(item["year"]),
                    "title": item["text"][:24],
                    "story": item["text"],
                    "source_confidence": item.get("source_confidence", "low"),
                    "source_basis": f"Sources: {', '.join(item['sources'])}",
                }
            )

    return {
        "headline": f"{target_date.month}月{target_date.day}日这天不简单",
        "summary": "过滤全部涉华内容后，这一天留下的历史切片依旧充满戏剧性：权力更替、突发冲突与人物命运在同一天交错出现。",
        "selection_notes": [
            "Prioritized multi-source agreement.",
            "Filtered China-related and CCP-related content.",
        ],
        "highlights": highlights,
        "births_digest": births_digest,
        "deaths_digest": deaths_digest,
        "holidays_digest": holidays_digest,
    }


def render_markdown(payload: dict[str, Any]) -> str:
    editorial = payload["editorial"]
    lines = [f"# {editorial['headline']}", ""]

    if payload.get("cover_image_url"):
        lines.extend([f"![cover image]({payload['cover_image_url']})", ""])

    lines.extend(
        [
            f"- Date: {payload['date']}",
            f"- Wikipedia lang: {payload['wikipedia_lang']}",
            f"- Total merged items: {payload['stats']['merged_count']}",
            "",
            editorial["summary"],
            "",
            "## Highlights",
            "",
        ]
    )

    for item in editorial["highlights"]:
        lines.append(f"### {item['year']} | {item['title']}")
        match = next(
            (
                entry
                for entry in payload["merged_items"]
                if str(entry["year"]) == str(item["year"]) and entry["text"] in item["story"]
            ),
            None,
        )
        if match and match.get("image_url"):
            lines.append(f"![highlight image]({match['image_url']})")
        lines.append(item["story"])
        lines.append(f"- Confidence: {item['source_confidence']}")
        lines.append(f"- Basis: {item['source_basis']}")
        if match and match["pages"]:
            lines.append(f"- Reference: [{match['pages'][0]['title']}]({match['pages'][0]['url']})")
        lines.append("")

    for section_name, key in (
        ("Births", "births_digest"),
        ("Deaths", "deaths_digest"),
        ("Holidays", "holidays_digest"),
    ):
        if editorial.get(key):
            lines.extend([f"## {section_name}", ""])
            for entry in editorial[key]:
                lines.append(f"- {entry}")
            lines.append("")

    lines.extend(["## Source Stats", ""])
    for source_name, stats in payload["stats"]["sources"].items():
        lines.append(f"- {source_name}: ok={stats['ok']}, items={stats['item_count']}, endpoint={stats['endpoint']}")
        if stats["error"]:
            lines.append(f"  error={stats['error']}")
    lines.append("")
    return "\n".join(lines)


def save_outputs(payload: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    date_str = payload["date"]
    json_path = output_dir / f"History_Today_{date_str}.json"
    md_path = output_dir / f"History_Today_{date_str}.md"

    with json_path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)

    with md_path.open("w", encoding="utf-8") as file:
        file.write(render_markdown(payload))

    return json_path, md_path


def main() -> None:
    args = parse_args()
    target_date = resolve_target_date(args.date, args.month, args.day)

    source_results = [
        {"name": "Wikimedia On this day", **fetch_wikimedia(args.lang, target_date)},
        {"name": "Day in History", **fetch_dayinhistory(target_date)},
        {"name": "API Ninjas Historical Events", **fetch_api_ninjas(target_date)},
    ]

    merged_items = merge_items(source_results, args.limit)
    if not merged_items:
        errors = [f"{item['name']}: {item.get('error', '')}" for item in source_results]
        raise RuntimeError(f"No merged items available. {' | '.join(errors)}")

    stats = source_stats(source_results, merged_items)
    prompt = build_gemini_prompt(target_date, merged_items, stats)

    try:
        editorial = call_gemini(prompt)
    except Exception as exc:
        editorial = build_fallback_editorial(target_date, merged_items)
        editorial["selection_notes"].append(f"Gemini fallback triggered: {exc}")

    payload = {
        "date": target_date.isoformat(),
        "wikipedia_lang": args.lang,
        "generated_at": dt.datetime.now(SHANGHAI_TZ).isoformat(),
        "cover_image_url": select_cover_image(merged_items),
        "stats": stats,
        "editorial": editorial,
        "merged_items": merged_items,
        "sources": source_results,
    }
    json_path, md_path = save_outputs(payload, Path(args.output_dir))
    print(f"Saved JSON to {json_path}")
    print(f"Saved Markdown to {md_path}")


if __name__ == "__main__":
    main()
