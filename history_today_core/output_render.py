from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

def render_wechat_html(title: str, summary: str, content_text: str, all_images: list[str]) -> str:
    paragraphs = [paragraph.strip() for paragraph in content_text.split("\n\n") if paragraph.strip()]
    cover_url = all_images[0] if all_images else ""
    body_images = all_images[1:] if len(all_images) > 1 else []
    parts = [
        "<section style=\"margin:0;background:linear-gradient(180deg,#f6efe4 0%,#fbf8f2 58%,#ffffff 100%);padding:1px;color:#1f2937;\">",
        "<section style=\"width:100%;margin:0;\">",
        "<section style=\"background:rgba(255,255,255,0.92);border:1px solid rgba(148,163,184,0.16);box-shadow:0 12px 28px rgba(15,23,42,0.06);border-radius:18px;overflow:hidden;\">",
    ]
    if cover_url:
        parts.append(
            f"<div style=\"position:relative;background:#d6d3d1;\"><img src=\"{cover_url}\" style=\"width:100%;aspect-ratio:16/9;object-fit:cover;display:block;\"></div>"
        )
    parts.extend(
        [
            "<section style=\"padding:16px 12px 10px;\">",
            "<div style=\"display:inline-block;padding:4px 10px;border-radius:999px;background:#111827;color:#f9fafb;font-size:11px;letter-spacing:0.08em;text-transform:uppercase;\">History Today</div>",
            f"<h1 style=\"font-size:29px;line-height:1.22;margin:12px 0 10px;color:#111827;font-family:Georgia,'Times New Roman',serif;\">{title}</h1>",
            f"<p style=\"font-size:15px;line-height:1.8;color:#475569;margin:0;\">{summary}</p>",
            "</section>",
            "<section style=\"padding:0 10px 12px;\">",
        ]
    )
    for index, paragraph in enumerate(paragraphs):
        parts.append(
            f"<div style=\"background:#fffdf8;border:1px solid rgba(226,232,240,0.88);border-radius:16px;padding:14px 12px;margin:0 0 12px;box-shadow:0 6px 16px rgba(15,23,42,0.035);\"><p style=\"font-size:16px;line-height:1.92;margin:0;color:#334155;\">{paragraph}</p></div>"
        )
        if index < len(body_images):
            parts.append(
                f"<div style=\"margin:0 0 14px;\"><img src=\"{body_images[index]}\" style=\"width:100%;aspect-ratio:16/9;object-fit:cover;border-radius:16px;display:block;box-shadow:0 10px 24px rgba(15,23,42,0.08);\"></div>"
            )
    parts.extend(
        [
            "</section>",
            "</section>",
            "</section>",
            "</section>",
        ]
    )
    content_html = "".join(parts)
    top_banner = (
        "<img src='https://mmbiz.qpic.cn/mmbiz_gif/3hAJnwuyZuicicZkgJBUCCaricdibomDBrTzXgUR7FJnf11qGIo8nmKt6RxibXrb5s4RFb9UZ9UOHQy7fqQyI377Licw/0?wx_fmt=gif' "
        "style='width:100%;display:block;'>"
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
