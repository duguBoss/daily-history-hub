from __future__ import annotations

import datetime as dt
from pathlib import Path

from .assets_common import github_asset_url
from .common import log
from .constants import ASSET_ROOT
from .images_generation import generate_minimax_cover, generate_minimax_event_image

def download_assets(
    target_date: dt.date,
    merged_items: list[dict[str, Any]],
    lang: str,
    article: dict[str, Any] | None = None,
) -> tuple[list[str], list[str]]:
    del lang  # Reserved for future use.
    target_dir = ASSET_ROOT / target_date.isoformat()
    target_dir.mkdir(parents=True, exist_ok=True)

    cover_url = ""
    image_urls: list[str] = []
    seen: set[str] = set()

    def to_github_url(local_path_str: str) -> str:
        local_path = Path(local_path_str)
        absolute_path = local_path if local_path.is_absolute() else (Path.cwd() / local_path)
        return github_asset_url(absolute_path.relative_to(Path.cwd()))

    if article:
        try:
            cover_url = to_github_url(generate_minimax_cover(article, merged_items, target_date, target_dir))
            if cover_url:
                seen.add(cover_url)
                log(f"Cover URL: {cover_url}")
        except Exception as exc:
            log(f"Cover generation failed: {exc}")
            cover_url = ""

    generated = 0
    for source_index, item in enumerate(merged_items, start=1):
        if generated >= 4:
            break
        event_index = generated + 1
        try:
            image_path = generate_minimax_event_image(item, target_date, target_dir, event_index)
        except Exception as exc:
            log(
                f"Event image generation failed for item {source_index} "
                f"({item.get('year')} {item.get('text', '')[:80]}): {exc}"
            )
            continue
        if not image_path:
            continue
        github_url = to_github_url(image_path)
        if github_url in seen:
            continue
        seen.add(github_url)
        image_urls.append(github_url)
        generated += 1
        log(f"Event image URL {event_index}: {github_url}")

    log(f"Generated asset summary: cover={'yes' if cover_url else 'no'}, event_images={len(image_urls)}")
    all_images = ([cover_url] if cover_url else []) + image_urls
    return all_images, image_urls
