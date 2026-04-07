from __future__ import annotations

import datetime as dt
from html import escape
from pathlib import Path

from .common import normalize_text


def _clip(text: str, limit: int) -> str:
    cleaned = normalize_text(text or "")
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(0, limit - 1)].rstrip() + "..."


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
        del exc
        return str(svg_path)
    cairosvg.svg2png(bytestring=svg.encode("utf-8"), write_to=str(png_path))
    return str(png_path)


def generate_fallback_cover_image(
    article: dict[str, object],
    merged_items: list[dict[str, object]],
    target_date: dt.date,
    target_dir: Path,
) -> str:
    title = _clip(str(article.get("title", "") or "历史上的今天"), 28)
    summary = _clip(str(article.get("summary", "") or ""), 88)
    title_lines = _wrap_lines(title, 12, 2)
    summary_lines = _wrap_lines(summary, 26, 3)

    while len(title_lines) < 2:
        title_lines.append("")
    while len(summary_lines) < 3:
        summary_lines.append("")

    timeline_blocks: list[str] = []
    timeline_items = merged_items[:3] or [{"year": target_date.year, "text": "回望今天的历史节点与时代回声"}]
    start_y = 286
    step_y = 176

    for idx, item in enumerate(timeline_items):
        y = start_y + idx * step_y
        year = _clip(str(item.get("year", "") or "历史"), 10)
        text = _clip(str(item.get("text", "") or ""), 34)
        detail = item.get("detail") if isinstance(item.get("detail"), dict) else {}
        description = _clip(str((detail or {}).get("description", "") or ""), 52)
        text_lines = _wrap_lines(text, 16, 2)
        desc_lines = _wrap_lines(description, 24, 2)

        while len(text_lines) < 2:
            text_lines.append("")
        while len(desc_lines) < 2:
            desc_lines.append("")

        timeline_blocks.append(
            f"<circle cx='888' cy='{y}' r='16' fill='#c27c2c'/>"
            f"<circle cx='888' cy='{y}' r='34' fill='rgba(194,124,44,0.12)'/>"
            f"<rect x='944' y='{y - 58}' width='500' height='118' rx='20' fill='#fffaf2' stroke='#eadbc5' stroke-width='2'/>"
            f"<text x='976' y='{y - 14}' fill='#a16207' font-size='28' font-weight='700' font-family='Georgia, Times New Roman, serif'>{escape(year)}</text>"
            f"<text x='976' y='{y + 18}' fill='#1f2937' font-size='30' font-family='Noto Serif SC, STSong, serif'>{escape(text_lines[0])}</text>"
            f"<text x='976' y='{y + 52}' fill='#1f2937' font-size='30' font-family='Noto Serif SC, STSong, serif'>{escape(text_lines[1])}</text>"
            f"<text x='706' y='{y - 10}' text-anchor='end' fill='#7c5a36' font-size='24' font-family='Noto Sans SC, Microsoft YaHei, sans-serif'>{escape(desc_lines[0])}</text>"
            f"<text x='706' y='{y + 22}' text-anchor='end' fill='#7c5a36' font-size='24' font-family='Noto Sans SC, Microsoft YaHei, sans-serif'>{escape(desc_lines[1])}</text>"
        )

    svg = (
        "<svg xmlns='http://www.w3.org/2000/svg' width='1600' height='900' viewBox='0 0 1600 900'>"
        "<defs>"
        "<linearGradient id='bg' x1='0' y1='0' x2='1' y2='1'>"
        "<stop offset='0%' stop-color='#f4eee3'/>"
        "<stop offset='55%' stop-color='#fbf8f2'/>"
        "<stop offset='100%' stop-color='#efe3d0'/>"
        "</linearGradient>"
        "<linearGradient id='panel' x1='0' y1='0' x2='0' y2='1'>"
        "<stop offset='0%' stop-color='#fffdf9'/>"
        "<stop offset='100%' stop-color='#fff8ef'/>"
        "</linearGradient>"
        "</defs>"
        "<rect width='1600' height='900' fill='url(#bg)'/>"
        "<rect x='56' y='56' width='1488' height='788' rx='32' fill='url(#panel)' stroke='#e7d8be' stroke-width='2'/>"
        "<rect x='96' y='96' width='412' height='708' rx='28' fill='#1f2937'/>"
        "<text x='136' y='156' fill='#f4d7a5' font-size='24' letter-spacing='4' font-family='Noto Sans SC, Microsoft YaHei, sans-serif'>ON THIS DAY</text>"
        f"<text x='136' y='212' fill='#ffffff' font-size='54' font-weight='700' font-family='Noto Serif SC, STSong, serif'>{target_date.month} 月 {target_date.day} 日</text>"
        f"<text x='136' y='304' fill='#ffffff' font-size='58' font-weight='700' font-family='Noto Serif SC, STSong, serif'>{escape(title_lines[0])}</text>"
        f"<text x='136' y='374' fill='#ffffff' font-size='58' font-weight='700' font-family='Noto Serif SC, STSong, serif'>{escape(title_lines[1])}</text>"
        "<line x1='136' y1='424' x2='456' y2='424' stroke='rgba(244,215,165,0.5)' stroke-width='2'/>"
        f"<text x='136' y='494' fill='#d9dfeb' font-size='28' font-family='Noto Sans SC, Microsoft YaHei, sans-serif'>{escape(summary_lines[0])}</text>"
        f"<text x='136' y='534' fill='#d9dfeb' font-size='28' font-family='Noto Sans SC, Microsoft YaHei, sans-serif'>{escape(summary_lines[1])}</text>"
        f"<text x='136' y='574' fill='#d9dfeb' font-size='28' font-family='Noto Sans SC, Microsoft YaHei, sans-serif'>{escape(summary_lines[2])}</text>"
        "<rect x='136' y='646' width='188' height='54' rx='27' fill='#f4d7a5'/>"
        "<text x='230' y='681' text-anchor='middle' fill='#1f2937' font-size='22' font-weight='700' font-family='Noto Sans SC, Microsoft YaHei, sans-serif'>时间轴精选</text>"
        "<text x='136' y='752' fill='#f4d7a5' font-size='22' letter-spacing='2' font-family='Noto Sans SC, Microsoft YaHei, sans-serif'>DAILY HISTORY HUB</text>"
        "<line x1='888' y1='200' x2='888' y2='708' stroke='#d8c6ab' stroke-width='4'/>"
        "<text x='944' y='160' fill='#8b7355' font-size='24' letter-spacing='3' font-family='Noto Sans SC, Microsoft YaHei, sans-serif'>TIMELINE</text>"
        f"{''.join(timeline_blocks)}"
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
        f"<text x='96' y='126' fill='#8a5a23' font-size='30' font-family='Noto Serif SC, STSong, serif'>历史节点 #{index:02d} · {escape(target_date.isoformat())}</text>"
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
