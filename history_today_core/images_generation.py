from __future__ import annotations

import datetime as dt
import os
from pathlib import Path
from typing import Any

import requests

from .common import build_user_agent, log, normalize_text
from .constants import MINIMAX_IMAGE_API_URL, REQUEST_TIMEOUT

def build_generated_cover_prompt(article: dict[str, Any], merged_items: list[dict[str, Any]], target_date: dt.date) -> str:
    highlights = []
    for item in merged_items[:3]:
        year = item.get("year", "")
        text = normalize_text(item.get("text", ""))
        if text:
            highlights.append(f"{year}: {text}")
    highlights_text = "; ".join(highlights)
    title = normalize_text(article.get("title", ""))
    summary = normalize_text(article.get("summary", ""))
    return (
        f"Historical 'This Day in History' magazine cover theme, date: {target_date.isoformat()}."
        f"Title theme: {title}. Summary: {summary}. Key events: {highlights_text}."
        "16:9 horizontal composition, documentary feel, historical sense, magazine cover quality, restrained lighting, realistic details."
    )


def build_generated_event_prompt(item: dict[str, Any], target_date: dt.date) -> str:
    detail = item.get("detail") or {}
    title = normalize_text(detail.get("title", ""))
    description = normalize_text(detail.get("description", ""))
    extract = normalize_text(detail.get("extract", ""))
    text = normalize_text(item.get("text", ""))
    year = item.get("year", "")
    return (
        f"Historical event scene from year {year}, set in context of {target_date.isoformat()}."
        f"Event: {text}. Title hint: {title}. Description: {description}. Background: {extract}."
        "16:9 horizontal composition, documentary style, realistic details, historical scene atmosphere."
    )


def generate_minimax_image(prompt: str, file_path: Path, aspect_ratio: str = "16:9") -> str:
    api_key = os.environ.get("MINIMAX_API_KEY")
    if not api_key:
        raise ValueError("Missing MINIMAX_API_KEY")

    log(f"Generating MiniMax image: {file_path.name}")
    log(f"Prompt: {prompt[:200]}")

    payload = {
        "model": "image-01",
        "prompt": prompt,
        "aspect_ratio": aspect_ratio,
        "response_format": "url",
        "n": 1,
        "prompt_optimizer": True,
    }

    response = requests.post(
        MINIMAX_IMAGE_API_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=REQUEST_TIMEOUT * 10,
    )
    response.raise_for_status()
    result = response.json()

    image_url = result.get("data", [{}])[0].get("url", "")
    if not image_url:
        raise RuntimeError(f"MiniMax returned no image URL: {result}")

    log(f"Generated image URL: {image_url}")
    download_response = requests.get(image_url, headers={"User-Agent": build_user_agent()}, timeout=REQUEST_TIMEOUT * 4)
    download_response.raise_for_status()
    file_path.write_bytes(download_response.content)
    log(f"Saved generated image: {file_path}")
    return str(file_path)


def generate_minimax_cover(article: dict[str, Any], merged_items: list[dict[str, Any]], target_date: dt.date, target_dir: Path) -> str:
    prompt = build_generated_cover_prompt(article, merged_items, target_date)
    return generate_minimax_image(prompt, target_dir / "minimax-cover.png")


def generate_minimax_event_image(item: dict[str, Any], target_date: dt.date, target_dir: Path, index: int) -> str:
    prompt = build_generated_event_prompt(item, target_date)
    return generate_minimax_image(prompt, target_dir / f"minimax-event-{index:02d}.png", aspect_ratio="3:2")
