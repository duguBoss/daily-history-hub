from __future__ import annotations

import datetime as dt
from html import escape
from pathlib import Path

from .common import normalize_text


def _clip(text: str, limit: int) -> str:
    cleaned = normalize_text(text or "")
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(0, limit - 1)].rstrip() + "…"


def _wrap_lines(text: str, max_chars: int, max_lines: int) -> list[str]:
    content = normalize_text(text or "")
    if not content:
        return []
    lines: list[str] = []
    rest = content
    while rest and len(lines) < max_lines:
        if len(rest) <= max_chars:
            lines.append(rest)
            rest = ""
            break
        split_at = rest.rfind(" ", 0, max_chars + 1)
        if split_at < max_chars // 2:
            split_at = max_chars
        line = rest[:split_at].strip()
        if not line:
            break
        lines.append(line)
        rest = rest[split_at:].strip()
    if rest and lines:
        lines[-1] = _clip(lines[-1], max(1, max_chars - 1))
    return lines


def _render_svg_to_png(svg: str, svg_path: Path, png_path: Path) -> str:
    svg_path.write_text(svg, encoding="utf-8")
    try:
        import cairosvg
    except ImportError as exc:
        raise RuntimeError("Missing cairosvg dependency for SVG to PNG fallback conversion.") from exc
    cairosvg.svg2png(bytestring=svg.encode("utf-8"), write_to=str(png_path))
    return str(png_path)


def generate_fallback_cover_image(
    article: dict[str, object],
    merged_items: list[dict[str, object]],
    target_date: dt.date,
    target_dir: Path,
) -> str:
    title = _clip(str(article.get("title", "") or "历史上的今天"), 34)
    summary = _clip(str(article.get("summary", "") or ""), 66)
    event_lines = []
    for item in merged_items[:3]:
        year = str(item.get("year", "")).strip()
        text = _clip(str(item.get("text", "") or ""), 34)
        if text:
            event_lines.append(f"{year} · {text}" if year else text)
    if not event_lines:
        event_lines.append("精选历史节点，回看时代转折。")

    lines = _wrap_lines(summary, 30, 2)
    while len(lines) < 2:
        lines.append("")

    events_svg = []
    base_y = 570
    for idx, line in enumerate(event_lines):
        events_svg.append(
            f"<text x='140' y='{base_y + idx * 56}' fill='#7a4e1d' "
            "font-size='34' font-family='Noto Serif SC, STSong, serif'>"
            f"{escape(line)}</text>"
        )

    svg = (
        "<svg xmlns='http://www.w3.org/2000/svg' width='1600' height='900' viewBox='0 0 1600 900'>"
        "<defs>"
        "<linearGradient id='bg' x1='0' y1='0' x2='0' y2='1'>"
        "<stop offset='0%' stop-color='#f4e2be'/>"
        "<stop offset='55%' stop-color='#f8edcf'/>"
        "<stop offset='100%' stop-color='#fffaf0'/>"
        "</linearGradient>"
        "</defs>"
        "<rect width='1600' height='900' fill='url(#bg)'/>"
        "<rect x='70' y='70' width='1460' height='760' rx='24' fill='#fff9ea' stroke='#d8b274' stroke-width='3'/>"
        f"<text x='140' y='178' fill='#8a5a23' font-size='36' letter-spacing='2' "
        "font-family='Noto Serif SC, STSong, serif'>历史上的今天 · "
        f"{escape(target_date.isoformat())}</text>"
        f"<text x='140' y='276' fill='#2f1b0e' font-size='70' font-weight='700' "
        "font-family='Noto Serif SC, STSong, serif'>"
        f"{escape(title)}</text>"
        f"<text x='140' y='360' fill='#5f3f22' font-size='36' font-family='Noto Serif SC, STSong, serif'>{escape(lines[0])}</text>"
        f"<text x='140' y='412' fill='#5f3f22' font-size='36' font-family='Noto Serif SC, STSong, serif'>{escape(lines[1])}</text>"
        "<line x1='140' y1='482' x2='1460' y2='482' stroke='#d9b676' stroke-width='2'/>"
        "<text x='140' y='534' fill='#8a5a23' font-size='30' letter-spacing='1' "
        "font-family='Noto Serif SC, STSong, serif'>今日历史看点</text>"
        f"{''.join(events_svg)}"
        "</svg>"
    )

    return _render_svg_to_png(
        svg=svg,
        svg_path=target_dir / "fallback-cover.svg",
        png_path=target_dir / "fallback-cover.png",
    )


def generate_fallback_event_image(
    item: dict[str, object],
    target_date: dt.date,
    target_dir: Path,
    index: int,
) -> str:
    year = str(item.get("year", "")).strip()
    text = _clip(str(item.get("text", "") or ""), 46)
    detail = item.get("detail") if isinstance(item.get("detail"), dict) else {}
    description = _clip(str((detail or {}).get("description", "") or ""), 120)

    main_lines = _wrap_lines(text or "历史事件", 24, 2)
    desc_lines = _wrap_lines(description, 34, 3)
    while len(main_lines) < 2:
        main_lines.append("")
    while len(desc_lines) < 3:
        desc_lines.append("")

    svg = (
        "<svg xmlns='http://www.w3.org/2000/svg' width='1200' height='800' viewBox='0 0 1200 800'>"
        "<defs>"
        "<linearGradient id='evbg' x1='0' y1='0' x2='0' y2='1'>"
        "<stop offset='0%' stop-color='#f0d9ad'/>"
        "<stop offset='100%' stop-color='#fff7e5'/>"
        "</linearGradient>"
        "</defs>"
        "<rect width='1200' height='800' fill='url(#evbg)'/>"
        "<rect x='52' y='52' width='1096' height='696' rx='20' fill='#fff9ec' stroke='#d9b676' stroke-width='2'/>"
        f"<text x='96' y='126' fill='#8a5a23' font-size='30' font-family='Noto Serif SC, STSong, serif'>"
        f"历史节点 #{index:02d} · {escape(target_date.isoformat())}</text>"
        f"<text x='96' y='206' fill='#3a2310' font-size='64' font-weight='700' font-family='Noto Serif SC, STSong, serif'>{escape(year)}</text>"
        f"<text x='96' y='294' fill='#4a2d16' font-size='44' font-family='Noto Serif SC, STSong, serif'>{escape(main_lines[0])}</text>"
        f"<text x='96' y='350' fill='#4a2d16' font-size='44' font-family='Noto Serif SC, STSong, serif'>{escape(main_lines[1])}</text>"
        "<line x1='96' y1='404' x2='1104' y2='404' stroke='#d7b26c' stroke-width='2'/>"
        f"<text x='96' y='478' fill='#6a4420' font-size='30' font-family='Noto Serif SC, STSong, serif'>{escape(desc_lines[0])}</text>"
        f"<text x='96' y='528' fill='#6a4420' font-size='30' font-family='Noto Serif SC, STSong, serif'>{escape(desc_lines[1])}</text>"
        f"<text x='96' y='578' fill='#6a4420' font-size='30' font-family='Noto Serif SC, STSong, serif'>{escape(desc_lines[2])}</text>"
        "</svg>"
    )

    return _render_svg_to_png(
        svg=svg,
        svg_path=target_dir / f"fallback-event-{index:02d}.svg",
        png_path=target_dir / f"fallback-event-{index:02d}.png",
    )
