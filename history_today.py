import datetime
import hashlib
import html
import json
import mimetypes
import os
import re
from pathlib import Path
from urllib.parse import urlparse

import pytz
import requests
from bs4 import BeautifulSoup

# ================= 配置区域 =================
SHANGHAI_TZ = pytz.timezone("Asia/Shanghai")
ASSET_ROOT = Path("assets") / "history"
DEFAULT_REPOSITORY = "duguBoss/daily-news-hub"  # 替换为你的默认仓库名
DEFAULT_BRANCH = "main"

# 微信公众号顶部和底部引导关注图 (和新闻脚本保持一致的高级感)
TOP_BANNER_URL = "https://mmbiz.qpic.cn/mmbiz_gif/3hAJnwuyZuicicZkgJBUCCaricdibomDBrTzXgUR7FJnf11qGIo8nmKt6RxibXrb5s4RFb9UZ9UOHQy7fqQyI377Licw/0?wx_fmt=gif"
BOTTOM_BANNER_URL = "https://mmbiz.qpic.cn/mmbiz_gif/3hAJnwuyZuicicZkgJBUCCaricdibomDBrTzk57DCmhVC16o9ILH0Tn1YPEiarfLRRQSVFN2mJdeYibGnBPialPIzvojw/0?wx_fmt=gif"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


# ================= 辅助函数 =================
def raw_asset_url(relative_path: Path) -> str:
    """生成 GitHub Raw 图片直链"""
    repository = os.environ.get("GITHUB_REPOSITORY", DEFAULT_REPOSITORY)
    branch = os.environ.get("GITHUB_REF_NAME", DEFAULT_BRANCH)
    normalized = relative_path.as_posix()
    return f"https://raw.githubusercontent.com/{repository}/{branch}/{normalized}"


def download_image(image_url: str, target_dir: Path, file_stem: str) -> str:
    """下载图片并返回 GitHub 访问直链"""
    response = requests.get(image_url, stream=True, timeout=30, headers=HEADERS)
    response.raise_for_status()

    content_type = response.headers.get("Content-Type", "")
    extension = mimetypes.guess_extension(content_type.split(";")[0].strip().lower()) or ".jpg"
    
    # 维基百科有些图片后缀在URL里体现更准
    if not extension or extension == ".jpe":
        if ".png" in image_url.lower(): extension = ".png"
        else: extension = ".jpg"

    content = response.content
    if len(content) < 5000:  # 忽略极小图标
        raise ValueError("Image too small")

    digest = hashlib.sha1(content).hexdigest()[:8]
    filename = f"{file_stem}-{digest}{extension}"
    target_dir.mkdir(parents=True, exist_ok=True)
    relative_path = target_dir / filename
    relative_path.write_bytes(content)
    
    return raw_asset_url(relative_path)


# ================= 核心爬虫逻辑 =================
def fetch_history_today() -> dict:
    """抓取维基百科的历史上的今天数据"""
    now = datetime.datetime.now(SHANGHAI_TZ)
    month_day = f"{now.month}月{now.day}日"
    
    # 使用 zh-cn 简体中文变体
    url = f"https://zh.wikipedia.org/zh-cn/Wikipedia:历史上的今天/{month_day}"
    print(f"Fetching: {url}")
    
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, 'html.parser')

    # 1. 解析历史事件文本
    parsed_events =[]
    # 维基百科的内容通常在 .mw-parser-output 下的 ul 列表里
    ul_tags = soup.select('.mw-parser-output > ul')
    for ul in ul_tags[:2]:  # 通常前两个 ul 是历史事件、出生和逝世
        for li in ul.find_all('li', recursive=False):
            text = li.get_text().strip()
            # 用正则精准捕获：格式通常是 "1912年：XXXXX" 或 "1912年 - XXXXX"
            match = re.match(r'^(\d+年(?:前)?)[：:\-\—\s]+(.*)', text)
            if match:
                parsed_events.append({
                    "year": match.group(1).strip(),
                    "description": match.group(2).strip()
                })

    # 2. 解析右侧插图并高清化
    raw_images =[]
    for img in soup.select('.mw-parser-output img'):
        src = img.get('src', '')
        width = int(img.get('width', 0) or 0)
        
        # 排除各类界面小图标，只要大插图
        if width > 60 and "http" not in src and not src.lower().endswith('.svg'):
            if src.startswith('//'):
                src = 'https:' + src
            
            # 【关键】维基缩略图转高清图技巧 (将 /120px- 替换为 /800px-)
            src = re.sub(r'/(\d+)px-', r'/800px-', src)
            if src not in raw_images:
                raw_images.append(src)

    # 3. 下载图片存入 GitHub
    date_str = now.strftime("%Y-%m-%d")
    target_dir = ASSET_ROOT / date_str
    downloaded_img_urls = []
    
    for idx, img_url in enumerate(raw_images[:4]):  # 最多取前4张大图
        try:
            github_url = download_image(img_url, target_dir, f"history-{idx}")
            downloaded_img_urls.append(github_url)
            print(f"Image downloaded: {github_url}")
        except Exception as e:
            print(f"Failed to download image {img_url}: {e}")

    return {
        "title": "带你看看历史上的今天发生了什么？",
        "date": month_day,
        "events": parsed_events,
        "images": downloaded_img_urls,
        "source_url": url
    }


# ================= 微信高级 UI 渲染 =================
def render_wechat_html(data: dict) -> str:
    month_day = data["date"]
    
    parts =[
        "<section style=\"margin:0;padding:0;background:#ffffff;\">",
        f"<img src=\"{TOP_BANNER_URL}\" style=\"width:100%;display:block;\">",
        "<section style=\"max-width:760px;margin:0 auto;padding:2px;\">",
        
        # 顶部标题栏
        "<section style=\"margin:12px 0 20px 0;padding:2px 2px 8px 2px;border-bottom:2px solid #1e293b;\">",
        f"<div style=\"font-size:12px;letter-spacing:2px;color:#b59f7b;text-transform:uppercase;margin-bottom:4px;font-weight:600;\">On This Day • {month_day}</div>",
        f"<h1 style=\"margin:0;font-size:26px;line-height:1.4;color:#0f172a;font-weight:bold;letter-spacing:0.5px;\">{html.escape(data['title'])}</h1>",
        "</section>"
    ]

    # 图片展示区 (如有图则渲染)
    if data["images"]:
        parts.append("<section style=\"margin:0 0 24px 0;\">")
        for img_url in data["images"]:
            parts.append(
                "<section style=\"margin:0 0 10px 0;\">"
                f"<img src=\"{html.escape(img_url)}\" style=\"width:100%;display:block;border-radius:4px;border:1px solid #f1f5f9;\">"
                "</section>"
            )
        parts.append("</section>")

    # 历史事件遍历渲染区 (采用高级左侧香槟金边框流设计)
    parts.append("<section style=\"margin:0 0 18px 0;padding:0 2px;\">")
    for event in data["events"]:
        year_html = f"<strong style=\"color:#1e293b;font-family:serif;font-size:17px;\">{html.escape(event['year'])}</strong>"
        text_html = html.escape(event['description'])
        parts.append(
            "<div style=\"margin:0 0 16px 0;padding-left:12px;border-left:4px solid #b59f7b;\">"
            f"<p style=\"margin:0;color:#334155;font-size:16px;line-height:1.8;letter-spacing:0.5px;text-align:justify;\">"
            f"{year_html} {text_html}"
            "</p></div>"
        )
    parts.append("</section>")

    # 底部金句结语卡片
    parts.append(
        "<section style=\"margin:24px 2px 16px 2px;padding:16px;background:#0f172a;border-top:3px solid #b59f7b;border-radius:2px;\">"
        "<div style=\"font-size:12px;letter-spacing:2px;text-transform:uppercase;color:#b59f7b;margin-bottom:8px;font-weight:600;\">Time Capsule</div>"
        "<p style=\"margin:0;font-size:15px;line-height:1.8;color:#e2e8f0;text-align:justify;letter-spacing:0.5px;\">"
        "历史是过去传到将来的回声，是将来对过去的反映。在时间的长河中，今天仅仅是漫长岁月里的璀璨一瞬。"
        "</p>"
        "</section>"
    )

    parts.append("</section>")
    parts.append(f"<img src=\"{BOTTOM_BANNER_URL}\" style=\"width:100%;display:block;\">")
    parts.append("</section>")

    return "".join(parts)


def main():
    # 抓取数据并下载图片
    data = fetch_history_today()
    
    if not data["events"]:
        print("未抓取到任何历史事件，可能页面格式变更或请求被拦截。")
        return

    # 渲染 HTML
    wechat_html = render_wechat_html(data)
    data["wechat_html"] = wechat_html

    # 保存 JSON 文件
    now = datetime.datetime.now(SHANGHAI_TZ)
    date_str = now.strftime("%Y-%m-%d")
    json_filename = f"History_Today_{date_str}.json"
    
    with open(json_filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"✅ 成功生成历史上的今天数据，包含 {len(data['events'])} 条事件，保存至: {json_filename}")


if __name__ == "__main__":
    main()
