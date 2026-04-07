from __future__ import annotations

import datetime as dt
from html import escape
from pathlib import Path
from urllib.parse import quote

from .common import normalize_text, to_simplified


def _clip(text: str, limit: int) -> str:
    cleaned = normalize_text(text or "")
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(0, limit - 1)].rstrip() + "..."


def _pick_chinese_title(item: dict[str, object]) -> str:
    detail = item.get("detail") if isinstance(item.get("detail"), dict) else {}
    description = to_simplified(normalize_text(str((detail or {}).get("description", "") or "")))
    extract = to_simplified(normalize_text(str((detail or {}).get("extract", "") or "")))
    return description or extract or "回看这一节点与当日主题的关联。"


def _pick_chinese_meta(item: dict[str, object], title_text: str) -> str:
    detail = item.get("detail") if isinstance(item.get("detail"), dict) else {}
    extract = to_simplified(normalize_text(str((detail or {}).get("extract", "") or "")))
    description = to_simplified(normalize_text(str((detail or {}).get("description", "") or "")))
    candidate = extract or description
    if candidate == title_text:
        return "沿着时间线回看这一天在历史中的位置与影响。"
    return candidate or "沿着时间线回看这一天在历史中的位置与影响。"


def _build_timeline_rows(merged_items: list[dict[str, object]]) -> str:
    cards: list[str] = []
    for index, item in enumerate(merged_items, start=1):
        year = escape(_clip(str(item.get("year", "") or "历史"), 12))
        title_text = _pick_chinese_title(item)
        meta_text = _pick_chinese_meta(item, title_text)
        title = escape(_clip(title_text, 66))
        meta = escape(_clip(meta_text, 86))
        side_class = "left" if index % 2 else "right"
        cards.append(
            "<article class='timeline-row'>"
            f"<div class='timeline-dot'>{index:02d}</div>"
            f"<section class='timeline-card {side_class}'>"
            f"<div class='timeline-year'>{year}</div>"
            "<div class='timeline-divider'></div>"
            f"<p class='timeline-title'>{title}</p>"
            f"<p class='timeline-meta'>{meta}</p>"
            "</section>"
            "</article>"
        )
    return "".join(cards)


def _build_cover_html(article: dict[str, object], merged_items: list[dict[str, object]], target_date: dt.date) -> str:
    title = escape(_clip(to_simplified(str(article.get("title", "") or "历史上的今天")), 34))
    summary = escape(_clip(to_simplified(str(article.get("summary", "") or "")), 140))
    day_label = f"{target_date.month:02d}.{target_date.day:02d}"
    timeline_rows = _build_timeline_rows(merged_items)
    if not timeline_rows:
        timeline_rows = (
            "<article class='timeline-row'>"
            "<div class='timeline-dot'>01</div>"
            "<section class='timeline-card right'>"
            "<div class='timeline-year'>今日</div>"
            "<div class='timeline-divider'></div>"
            "<p class='timeline-title'>回看今天的历史节点与时代回声</p>"
            "<p class='timeline-meta'>当日无可用事件时，使用摘要内容作为时间线兜底展示。</p>"
            "</section>"
            "</article>"
        )

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>历史上的今天时间线封面</title>
  <style>
    :root {{
      --ink: #1f2937;
      --muted: #6b7280;
      --accent: #b7791f;
      --deep: #202a36;
      --shadow: 0 22px 60px rgba(31, 41, 55, 0.10);
    }}
    * {{
      box-sizing: border-box;
    }}
    body {{
      margin: 0;
      background:
        radial-gradient(circle at top left, rgba(183,121,31,0.10), transparent 28%),
        linear-gradient(180deg, #f5efe5 0%, #fbf8f3 52%, #f0e6d6 100%);
      color: var(--ink);
      font-family: "Noto Serif SC", "Source Han Serif SC", "Songti SC", serif;
    }}
    .page {{
      width: 1600px;
      margin: 0 auto;
      padding: 52px 56px 72px;
    }}
    .shell {{
      background: linear-gradient(180deg, rgba(255,250,243,0.96), rgba(255,248,238,0.98));
      border: 1px solid rgba(178, 148, 103, 0.22);
      border-radius: 34px;
      box-shadow: var(--shadow);
      overflow: hidden;
    }}
    .hero {{
      display: grid;
      grid-template-columns: 420px 1fr;
      border-bottom: 1px solid rgba(178, 148, 103, 0.16);
      min-height: 420px;
    }}
    .hero-aside {{
      background: linear-gradient(180deg, #202a36 0%, #263242 100%);
      color: #fff;
      padding: 56px 42px 48px;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
    }}
    .eyebrow {{
      font-family: "Segoe UI", "PingFang SC", sans-serif;
      font-size: 22px;
      letter-spacing: 0.18em;
      color: #f0d4a5;
      text-transform: uppercase;
    }}
    .date-block {{
      margin-top: 26px;
    }}
    .date {{
      font-size: 74px;
      line-height: 0.95;
      font-weight: 700;
      margin: 0 0 14px;
    }}
    .subdate {{
      font-family: "Segoe UI", "PingFang SC", sans-serif;
      font-size: 24px;
      color: rgba(255,255,255,0.74);
      letter-spacing: 0.08em;
    }}
    .hero-note {{
      border-top: 1px solid rgba(240,212,165,0.26);
      padding-top: 20px;
      font-family: "Segoe UI", "PingFang SC", sans-serif;
      font-size: 22px;
      line-height: 1.7;
      color: rgba(255,255,255,0.82);
    }}
    .hero-main {{
      padding: 56px 62px 48px;
      display: flex;
      flex-direction: column;
      justify-content: center;
    }}
    .kicker {{
      font-family: "Segoe UI", "PingFang SC", sans-serif;
      font-size: 18px;
      letter-spacing: 0.18em;
      color: #9a7b4f;
      margin-bottom: 18px;
    }}
    .hero-title {{
      font-size: 62px;
      line-height: 1.18;
      margin: 0;
      color: #18202b;
    }}
    .hero-divider {{
      width: 88px;
      height: 2px;
      background: linear-gradient(90deg, var(--accent), rgba(183,121,31,0.18));
      margin: 28px 0 24px;
    }}
    .hero-summary {{
      font-family: "Segoe UI", "PingFang SC", sans-serif;
      font-size: 28px;
      line-height: 1.9;
      color: #5e6877;
      margin: 0;
      max-width: 930px;
    }}
    .timeline-wrap {{
      position: relative;
      padding: 48px 68px 64px;
    }}
    .timeline-head {{
      display: grid;
      grid-template-columns: 240px 1fr;
      gap: 36px;
      align-items: end;
      margin-bottom: 36px;
    }}
    .timeline-label {{
      font-family: "Segoe UI", "PingFang SC", sans-serif;
      font-size: 22px;
      letter-spacing: 0.16em;
      color: #8b7355;
    }}
    .timeline-caption {{
      font-family: "Segoe UI", "PingFang SC", sans-serif;
      font-size: 24px;
      color: #7b6b56;
      line-height: 1.8;
      padding-bottom: 10px;
      border-bottom: 1px solid rgba(178, 148, 103, 0.18);
    }}
    .timeline {{
      position: relative;
      padding-top: 12px;
    }}
    .timeline::before {{
      content: "";
      position: absolute;
      left: 50%;
      top: 0;
      bottom: 0;
      width: 3px;
      transform: translateX(-50%);
      background: linear-gradient(180deg, rgba(183,121,31,0.24), rgba(183,121,31,0.50), rgba(183,121,31,0.14));
    }}
    .timeline-row {{
      position: relative;
      min-height: 180px;
      margin-bottom: 22px;
    }}
    .timeline-dot {{
      position: absolute;
      left: 50%;
      top: 34px;
      transform: translateX(-50%);
      width: 52px;
      height: 52px;
      border-radius: 50%;
      background: #fff;
      border: 2px solid rgba(183,121,31,0.26);
      box-shadow: 0 10px 28px rgba(183,121,31,0.16);
      color: var(--accent);
      font-family: "Segoe UI", sans-serif;
      font-size: 18px;
      font-weight: 700;
      display: flex;
      align-items: center;
      justify-content: center;
      z-index: 2;
    }}
    .timeline-card {{
      width: calc(50% - 62px);
      background: rgba(255, 251, 244, 0.92);
      border: 1px solid rgba(178, 148, 103, 0.18);
      border-radius: 24px;
      padding: 26px 28px 24px;
      box-shadow: 0 16px 38px rgba(31,41,55,0.07);
      position: relative;
    }}
    .timeline-card.left {{
      margin-right: auto;
    }}
    .timeline-card.right {{
      margin-left: auto;
    }}
    .timeline-year {{
      font-family: "Segoe UI", sans-serif;
      font-size: 20px;
      letter-spacing: 0.12em;
      color: var(--accent);
    }}
    .timeline-divider {{
      width: 100%;
      height: 1px;
      background: linear-gradient(90deg, rgba(183,121,31,0.26), rgba(183,121,31,0.05));
      margin: 12px 0 18px;
    }}
    .timeline-title {{
      font-size: 34px;
      line-height: 1.6;
      color: var(--deep);
      margin: 0 0 14px;
    }}
    .timeline-meta {{
      font-family: "Segoe UI", "PingFang SC", sans-serif;
      font-size: 24px;
      line-height: 1.9;
      color: var(--muted);
      margin: 0;
    }}
  </style>
</head>
<body>
  <main class="page">
    <section class="shell">
      <header class="hero">
        <aside class="hero-aside">
          <div>
            <div class="eyebrow">历史上的今天</div>
            <div class="date-block">
              <p class="date">{day_label}</p>
              <div class="subdate">{target_date.year} / {target_date.month:02d} / {target_date.day:02d}</div>
            </div>
          </div>
          <div class="hero-note">以时间线方式整理当日节点，用分段、分隔线和留白建立阅读节奏，不把所有内容压成一段。</div>
        </aside>
        <section class="hero-main">
          <div class="kicker">今日历史时间线</div>
          <h1 class="hero-title">{title}</h1>
          <div class="hero-divider"></div>
          <p class="hero-summary">{summary}</p>
        </section>
      </header>
      <section class="timeline-wrap">
        <div class="timeline-head">
          <div class="timeline-label">事件时间线</div>
          <div class="timeline-caption">按时间线展开今日历史节点。每个节点独立成段，使用年份、分隔线与说明文字分层组织，避免大段内容堆叠。</div>
        </div>
        <section class="timeline">
          {timeline_rows}
        </section>
      </section>
    </section>
  </main>
</body>
</html>
"""


def _render_html_to_png(html: str, html_path: Path, png_path: Path) -> str:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("Missing playwright dependency for HTML screenshot rendering.") from exc
    html_path.write_text(html, encoding="utf-8")
    normalized = str(html_path.resolve()).replace("\\", "/")
    file_url = f"file:///{quote(normalized, safe=':/')}"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1600, "height": 1200}, device_scale_factor=1)
        page.goto(file_url, wait_until="load")
        page.screenshot(path=str(png_path), full_page=True)
        browser.close()
    return str(png_path)


def generate_fallback_cover_image(
    article: dict[str, object],
    merged_items: list[dict[str, object]],
    target_date: dt.date,
    target_dir: Path,
) -> str:
    html = _build_cover_html(article, merged_items, target_date)
    return _render_html_to_png(
        html=html,
        html_path=target_dir / "timeline-cover.html",
        png_path=target_dir / "timeline-cover.png",
    )


def generate_fallback_event_image(
    item: dict[str, object],
    target_date: dt.date,
    target_dir: Path,
    index: int,
) -> str:
    year = escape(_clip(str(item.get("year", "") or "历史"), 20))
    title_text = _pick_chinese_title(item)
    meta_text = _pick_chinese_meta(item, title_text)
    title = escape(_clip(title_text, 84))
    meta = escape(_clip(meta_text, 160))
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <style>
    body {{
      margin: 0;
      background: linear-gradient(180deg, #f6efdf, #fff9ef);
      font-family: "Noto Serif SC", "Songti SC", serif;
    }}
    .card {{
      width: 1200px;
      min-height: 800px;
      margin: 0 auto;
      padding: 56px 72px;
      box-sizing: border-box;
    }}
    .eyebrow {{
      font: 700 20px "Segoe UI", sans-serif;
      color: #a16207;
      letter-spacing: .12em;
    }}
    .year {{
      margin: 28px 0 12px;
      font-size: 72px;
      color: #2a2116;
    }}
    .divider {{
      width: 100%;
      height: 1px;
      background: rgba(161, 98, 7, .2);
      margin: 18px 0 26px;
    }}
    .title {{
      font-size: 42px;
      line-height: 1.6;
      color: #1f2937;
      margin: 0 0 18px;
    }}
    .meta {{
      font: 28px/1.9 "Segoe UI", "PingFang SC", sans-serif;
      color: #6b7280;
      margin: 0;
    }}
  </style>
</head>
<body>
  <section class="card">
    <div class="eyebrow">历史节点 #{index:02d} / {target_date.isoformat()}</div>
    <div class="year">{year}</div>
    <div class="divider"></div>
    <p class="title">{title}</p>
    <p class="meta">{meta}</p>
  </section>
</body>
</html>
"""
    return _render_html_to_png(
        html=html,
        html_path=target_dir / f"timeline-event-{index:02d}.html",
        png_path=target_dir / f"timeline-event-{index:02d}.png",
    )
