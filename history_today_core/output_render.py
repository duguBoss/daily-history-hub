from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

def _render_historical_figure_html(title: str, summary: str, paragraphs: list[str], cover_url: str) -> str:
    del title
    parts = [
        "<section style=\"margin:0;background:#f7f4ee;color:#1f2937;\">",
    ]
    if cover_url:
        parts.append(
            f"<div style=\"margin:0 0 18px;\"><img src=\"{cover_url}\" style=\"width:100%;height:auto;display:block;\"></div>"
        )
    parts.extend(
        [
            "<section style=\"padding:0 2px;\">",
            f"<p style=\"margin:0 0 24px;font-size:16px;line-height:1.95;color:#5b6472;\">{summary}</p>",
        ]
    )
    for paragraph in paragraphs:
        parts.append(
            "<div style=\"margin:0 0 24px;\">"
            "<div style=\"width:100%;height:1px;background:linear-gradient(90deg,rgba(139,115,85,0.22),rgba(139,115,85,0.06));margin:0 0 18px;\"></div>"
            f"<p style=\"margin:0;font-size:17px;line-height:2;color:#2f3743;\">{paragraph}</p>"
            "</div>"
        )
    parts.append("</section></section>")
    return "".join(parts)


def _render_history_today_html(title: str, summary: str, paragraphs: list[str], cover_url: str) -> str:
    del title
    parts = [
        "<section style=\"margin:0;background:linear-gradient(180deg,#f3efe7 0%,#faf8f3 34%,#ffffff 100%);color:#1f2937;\">",
    ]
    if cover_url:
        parts.append(
            f"<div style=\"margin:0 0 22px;\"><img src=\"{cover_url}\" style=\"width:100%;display:block;object-fit:cover;\"></div>"
        )
    parts.extend(
        [
            "<section style=\"padding:0;\">",
            "<div style=\"margin:0 0 12px;font-size:12px;letter-spacing:0.16em;text-transform:uppercase;color:#7c6951;\">历史时间线</div>",
            f"<p style=\"margin:0 0 28px;font-size:16px;line-height:1.95;color:#5f6b7a;\">{summary}</p>",
        ]
    )
    for index, paragraph in enumerate(paragraphs):
        first_style = "font-size:18px;color:#202733;" if index == 0 else "font-size:17px;color:#344152;"
        parts.append(
            f"<div style=\"margin:0 0 24px;\">"
            f"<div style=\"width:100%;height:1px;background:linear-gradient(90deg,rgba(139,115,85,0.22),rgba(139,115,85,0.06));margin:0 0 18px;\"></div>"
            f"<p style=\"margin:0;line-height:2;{first_style}\">{paragraph}</p>"
            "</div>"
        )
    parts.append("</section></section>")
    return "".join(parts)


def render_wechat_html(
    title: str,
    summary: str,
    content_text: str,
    all_images: list[str],
    variant: str = "history_today",
) -> str:
    paragraphs = [paragraph.strip() for paragraph in content_text.split("\n\n") if paragraph.strip()]
    cover_url = all_images[0] if all_images else ""
    if variant == "historical_figure":
        content_html = _render_historical_figure_html(title, summary, paragraphs, cover_url)
    else:
        content_html = _render_history_today_html(title, summary, paragraphs, cover_url)
    top_banner = (
        "<img src='https://mmbiz.qpic.cn/mmbiz_gif/3hAJnwuyZuicicZkgJBUCCaricdibomDBrTzXgUR7FJnf11qGIo8nmKt6RxibXrb5s4RFb9UZ9UOHQy7fqQyI377Licw/0?wx_fmt=gif' "
        "style='width:100%;display:block;margin-bottom:1em;'>"
    )
    bottom_banner = (
        "<img src='https://mmbiz.qpic.cn/mmbiz_gif/3hAJnwuyZuicicZkgJBUCCaricdibomDBrTzk57DCmhVC16o9ILH0Tn1YPEiarfLRRQSVFN2mJdeYibGnBPialPIzvojw/0?wx_fmt=gif' "
        "style='width:100%;display:block;'>"
    )
    return f"{top_banner}<section style='padding:0;'>{content_html}</section>{bottom_banner}"


def save_outputs(payload: dict[str, Any], output_dir: Path, target_date: dt.date) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"History_Today_{target_date.isoformat()}.json"
    with json_path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
    return json_path
