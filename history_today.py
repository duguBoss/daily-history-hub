from __future__ import annotations

import json
from pathlib import Path

from history_today_core.article_generation import build_fallback_article, build_gemini_prompt, call_gemini
from history_today_core.assets_common import cleanup_old_assets
from history_today_core.assets_pipeline import download_assets
from history_today_core.common import log, parse_args, resolve_target_date
from history_today_core.constants import ASSET_ROOT
from history_today_core.enrichment import enrich_item_details
from history_today_core.filters import filter_safe_items
from history_today_core.merge import merge_items, source_stats
from history_today_core.output_render import render_wechat_html, save_outputs
from history_today_core.source_britannica import fetch_britannica
from history_today_core.source_history_dot_com import fetch_history_dot_com
from history_today_core.source_open_data import fetch_api_ninjas, fetch_dayinhistory, fetch_wikimedia


def main() -> None:
    args = parse_args()
    target_date = resolve_target_date(args.date, args.month, args.day)
    log(f"Start run for date {target_date.isoformat()}")
    cleanup_old_assets(target_date, ASSET_ROOT, keep_days=7)

    source_results = [
        {"name": "Britannica On This Day", **fetch_britannica(target_date)},
        {"name": "Wikimedia On this day", **fetch_wikimedia(args.lang, target_date)},
        {"name": "Day in History", **fetch_dayinhistory(target_date)},
        {"name": "API Ninjas Historical Events", **fetch_api_ninjas(target_date)},
        {"name": "History.com This Day in History", **fetch_history_dot_com(target_date)},
    ]
    merged_items = merge_items(source_results, args.limit)
    if not merged_items:
        errors = [f"{item['name']}: {item.get('error', '')}" for item in source_results]
        raise RuntimeError(f"No merged items available. {' | '.join(errors)}")
    log(f"Merged unique items: {len(merged_items)}")

    enrich_item_details(merged_items, args.lang)
    merged_items = filter_safe_items(merged_items)
    if not merged_items:
        raise RuntimeError("No safe non-sensitive items remain after strict filtering.")
    stats = source_stats(source_results, merged_items)
    log(f"Source stats: {json.dumps(stats, ensure_ascii=False)}")
    prompt = build_gemini_prompt(target_date, merged_items, stats)
    try:
        article = call_gemini(prompt)
        log("Article generation: Gemini success")
    except Exception as exc:
        log("\n====================================")
        log("⚠️ 拦截触发! 使用保底逻辑 (Fallback) ⚠️")
        log(f"具体失败原因: {exc}")
        log("====================================\n")
        article = build_fallback_article(target_date, merged_items)

    log(f"\n【最终生成的文章内容结构】")
    log(f"Title: {article.get('title')}")
    log(f"Summary: {article.get('summary')}")
    log(f"Content (前100字): {article.get('content_text', '')[:100]}...\n")

    all_images, image_urls = download_assets(target_date, merged_items, args.lang, article)
    del image_urls
    lead_images = all_images[:1]
    content_html = render_wechat_html(
        article["title"],
        article["summary"],
        article["content_text"],
        lead_images,
        variant="history_today",
    )
    payload = {
        "title": article["title"],
        "seo_summary": article["summary"],
        "cover": lead_images,
        "wechat_html": content_html,
    }
    json_path = save_outputs(payload, Path(args.output_dir), target_date)
    log(f"Saved JSON to {json_path}")


if __name__ == "__main__":
    main()
