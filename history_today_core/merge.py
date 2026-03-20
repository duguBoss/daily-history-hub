from __future__ import annotations

from collections import Counter
from typing import Any

from .constants import SOURCE_API_NINJAS, SOURCE_BRITANNICA, SOURCE_DAYINHISTORY, SOURCE_HISTORY_DOT_COM, SOURCE_WIKIMEDIA
from .filters import dedupe_final_items, is_china_related_item, make_event_key

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
                    "detail": item.get("detail", {}),
                    "image_url": item.get("image_url", ""),
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
            if not current.get("detail") and item.get("detail"):
                current["detail"] = item["detail"]
            if SOURCE_BRITANNICA in current["sources"] and item.get("source") == SOURCE_BRITANNICA:
                if item.get("detail"):
                    current["detail"] = item["detail"]
                if item.get("pages"):
                    current["pages"] = item["pages"]
                if item.get("image_url"):
                    current["image_url"] = item["image_url"]

    ordered = sorted(
        merged.values(),
        key=lambda item: (
            SOURCE_BRITANNICA not in item["sources"],
            -len(item["sources"]),
            str(item.get("year") or ""),
            item["text"],
        ),
    )
    results = []
    for item in ordered:
        if is_china_related_item(item):
            continue
        if not item.get("image_url"):
            image_url = ""
            for page in item.get("pages", []):
                if page.get("thumbnail"):
                    image_url = page["thumbnail"]
                    break
            item["image_url"] = image_url
        item["source_confidence"] = infer_confidence(item)
        results.append(item)
    return dedupe_final_items(results, limit)


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
