from __future__ import annotations

import datetime as dt
import json
import os
import re
from typing import Any

import requests

from .common import log, to_simplified
from .constants import FALLBACK_GEMINI_MODEL, PRIMARY_GEMINI_MODEL, REQUEST_TIMEOUT
from .filters import is_china_related_text


def build_gemini_prompt(target_date: dt.date, merged_items: list[dict[str, Any]], stats: dict[str, Any]) -> str:
    compact_items = [
        {
            "year": item["year"],
            "text": item["text"],
            "categories": item["categories"],
            "sources": item["sources"],
            "source_confidence": item["source_confidence"],
            "page_title": item["pages"][0]["title"] if item["pages"] else "",
            "detail_title": (item.get("detail") or {}).get("title", ""),
            "detail_description": (item.get("detail") or {}).get("description", ""),
            "detail_extract": (item.get("detail") or {}).get("extract", ""),
            "detail_url": (item.get("detail") or {}).get("url", ""),
        }
        for item in merged_items
    ]
    return (
        "你正在撰写一篇完整的微信公众号历史文章。\n"
        "硬性要求：\n"
        "1. 全部输出必须是标准简体中文。\n"
        "2. 严禁输出整句或整段英文；专有名词也要尽量翻译或转述成中文表达。\n"
        "3. 不要提及资料来源、百科、页面、抓取、模型、生成等元信息。\n"
        "4. 文章要像成熟专栏，不要像资料拼接。\n"
        "5. 需要同时输出正文和封面时间线节点，时间线节点必须是纯中文。\n"
        "6. 排除一切中国相关政治、主权、边界、党派、近现代敏感议题。\n"
        "标题要求：必须是简体中文，32字以内，适合微信公众号传播。\n"
        "请只返回 JSON，对象字段必须严格为：title、summary、content_text、timeline_items。\n"
        "其中：\n"
        "- title: 中文标题\n"
        "- summary: 80字以内中文摘要\n"
        "- content_text: 至少5段正文，用\\n\\n分隔\n"
        "- timeline_items: 长度为3的数组，每项都包含 year、title、note 三个字段，全部必须为简体中文，适合直接放进封面时间线。\n"
        "timeline_items.title 应该是单个历史节点的中文概述；timeline_items.note 应该是对该节点的中文补充说明。\n"
        f"目标日期：{target_date.isoformat()}\n"
        f"统计信息：{json.dumps(stats, ensure_ascii=False)}\n"
        f"历史候选事件：{json.dumps(compact_items, ensure_ascii=False)}"
    )


def _validate_text(value: str, key: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"Gemini output missing {key}")
    value = to_simplified(value.strip())
    if is_china_related_text(value):
        raise RuntimeError(f"Validation failed: output contains filtered content in [{key}]")
    alpha_count = len(re.findall(r"[a-zA-Z]", value))
    if value and (alpha_count / max(1, len(value))) > 0.25:
        raise RuntimeError(f"Validation failed: Gemini output contains too much English text in [{key}]")
    forbidden_words = ["维基百科", "大英百科", "根据资料", "资料显示", "补充提到", "来源"]
    if any(word in value for word in forbidden_words):
        raise RuntimeError(f"Validation failed: Gemini output contains source-trace text in [{key}]")
    return value


def validate_gemini_result(result: dict[str, Any]) -> dict[str, Any]:
    result["title"] = _validate_text(result.get("title", ""), "title")
    result["summary"] = _validate_text(result.get("summary", ""), "summary")
    result["content_text"] = _validate_text(result.get("content_text", ""), "content_text")
    if len(result["summary"]) > 80:
        raise RuntimeError("Validation failed: summary exceeds 80 characters.")

    timeline_items = result.get("timeline_items")
    if not isinstance(timeline_items, list) or len(timeline_items) < 3:
        raise RuntimeError("Validation failed: timeline_items must contain at least 3 items.")

    cleaned_timeline: list[dict[str, str]] = []
    for index, item in enumerate(timeline_items[:3], start=1):
        if not isinstance(item, dict):
            raise RuntimeError(f"Validation failed: timeline_items[{index}] must be an object.")
        year = _validate_text(str(item.get("year", "")), f"timeline_items[{index}].year")
        title = _validate_text(str(item.get("title", "")), f"timeline_items[{index}].title")
        note = _validate_text(str(item.get("note", "")), f"timeline_items[{index}].note")
        cleaned_timeline.append({"year": year, "title": title, "note": note})
    result["timeline_items"] = cleaned_timeline
    return result


def call_gemini_once(prompt: str, model_name: str) -> dict[str, Any]:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("Missing GEMINI_API_KEY")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"
    response = requests.post(
        url,
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.75, "responseMimeType": "application/json"},
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
    log(f"\n================ Gemini Raw Output ({model_name}) ================\n{text}\n==================================================================\n")
    parsed_result = json.loads(text)
    return validate_gemini_result(parsed_result)


def call_gemini(prompt: str) -> dict[str, Any]:
    errors: list[str] = []
    for attempt in range(2):
        for model_name in (PRIMARY_GEMINI_MODEL, FALLBACK_GEMINI_MODEL):
            try:
                result = call_gemini_once(prompt, model_name)
                if attempt > 0:
                    log(f"Retry succeeded on attempt {attempt + 1}")
                return result
            except Exception as exc:
                errors.append(f"{model_name}: {exc}")
                log(f"Generation failed (attempt {attempt + 1}, model {model_name}): {exc}")
    raise RuntimeError(" | ".join(errors))


def build_fallback_article(target_date: dt.date, merged_items: list[dict[str, Any]]) -> dict[str, Any]:
    selected = merged_items[:5]
    paragraphs = [
        f"{target_date.month}月{target_date.day}日并不平静，这一天在历史长河里留下了多条相互交错的轨迹，既有公共议题，也有人物命运与突发事件的回响。"
    ]
    timeline_items: list[dict[str, str]] = []
    for item in selected:
        detail = item.get("detail") or {}
        description = to_simplified(str(detail.get("description", "") or ""))
        extract = to_simplified(str(detail.get("extract", "") or ""))
        body_text = description or extract or to_simplified(str(item.get("text", "") or ""))
        year = to_simplified(str(item.get("year", "") or "历史"))
        if body_text:
            paragraphs.append(f"{year}年：{body_text}")
        if len(timeline_items) < 3:
            timeline_items.append(
                {
                    "year": year,
                    "title": _validate_text(body_text or "这一天留下了值得回望的历史节点。", "fallback.timeline.title"),
                    "note": _validate_text(extract or "这一节点与当日主题形成了清晰呼应。", "fallback.timeline.note"),
                }
            )
    while len(timeline_items) < 3:
        timeline_items.append(
            {
                "year": "今日",
                "title": "回看这一天留下的历史回声。",
                "note": "不同人物、事件与公共议题在同一天交织成线。",
            }
        )
    paragraphs.append("这些节点被放在同一条时间线上后，能更清楚地看见历史并不是孤立发生，而是在不同领域里同时推动世界向前。")
    content_text = "\n\n".join(paragraphs)
    return {
        "title": to_simplified(f"历史上的今天：{target_date.month}月{target_date.day}日留下了哪些回声"),
        "summary": to_simplified("这一天并不单薄，几条历史线索在同一页日历上相互照映。"),
        "content_text": to_simplified(content_text),
        "timeline_items": timeline_items[:3],
    }
