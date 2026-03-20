from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

from .assets_common import download_image, github_asset_url
from .common import log
from .constants import ASSET_ROOT
from .images_external import fetch_unsplash_image
from .images_generation import generate_minimax_cover, generate_minimax_event_image

def fetch_unsplash_or_generated_image(
    item: dict[str, Any],
    target_date: dt.date,
    target_dir: Path,
    index: int,
    used_unsplash_ids: set[str] = None
) -> str:
    if item.get("image_url"):
        log(f"Using existing image from history.com for item {index}: {item['image_url']}")
        return download_image(item["image_url"], target_dir)

    try:
        ai_image = generate_minimax_event_image(item, target_date, target_dir, index)
        if ai_image:
            log(f"AI generated image for item {index}: {ai_image}")
            return ai_image
    except Exception as exc:
        log(f"AI image generation failed for item {index}: {exc}")

    try:
        unsplash_url = fetch_unsplash_image(item, used_unsplash_ids)
    except Exception as exc:
        log(f"Unsplash lookup failed for item {index}: {exc}")
        unsplash_url = ""
    if unsplash_url:
        log(f"Unsplash image found for item {index}: {unsplash_url}")
        return download_image(unsplash_url, target_dir)

    return ""


def download_assets(
    target_date: dt.date,
    merged_items: list[dict[str, Any]],
    lang: str,
    article: dict[str, Any] | None = None,
) -> tuple[list[str], list[str]]:
    target_dir = ASSET_ROOT / target_date.isoformat()
    target_dir.mkdir(parents=True, exist_ok=True)

    cover_url = ""
    image_urls: list[str] = []
    seen: set[str] = set()
    used_unsplash_ids: set[str] = set()

    def to_github_url(local_path_str: str) -> str:
        local_path = Path(local_path_str)
        absolute_path = local_path if local_path.is_absolute() else (Path.cwd() / local_path)
        return github_asset_url(absolute_path.relative_to(Path.cwd()))

    if article:
        if merged_items:
            try:
                cover_path = fetch_unsplash_or_generated_image(merged_items[0], target_date, target_dir, 0, used_unsplash_ids)
                cover_url = to_github_url(cover_path) if cover_path else ""
                if cover_url:
                    seen.add(cover_url)
                    log(f"Cover URL: {cover_url}")
            except Exception as exc:
                log(f"Cover image creation failed: {exc}")
                cover_url = ""
        if not cover_url:
            try:
                cover_url = to_github_url(generate_minimax_cover(article, merged_items, target_date, target_dir))
                if cover_url:
                    seen.add(cover_url)
                    log(f"Cover URL: {cover_url}")
            except Exception as exc:
                log(f"Cover generation failed: {exc}")
                cover_url = ""

    for index, item in enumerate(merged_items[:5], start=1):
        try:
            image_path = fetch_unsplash_or_generated_image(item, target_date, target_dir, index, used_unsplash_ids)
        except Exception as exc:
            log(f"Event image generation failed for item {index} ({item.get('year')} {item.get('text', '')[:80]}): {exc}")
            image_path = ""
        if not image_path:
            continue
        github_url = to_github_url(image_path)
        if github_url in seen:
            continue
        seen.add(github_url)
        image_urls.append(github_url)
        log(f"Event image URL {index}: {github_url}")

    log(f"Generated asset summary: cover={'yes' if cover_url else 'no'}, event_images={len(image_urls)}")
    all_images = ([cover_url] if cover_url else []) + image_urls
    return all_images, image_urls
