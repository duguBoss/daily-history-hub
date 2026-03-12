import datetime
import hashlib
import html
import json
import mimetypes
import os
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
import pytz
import requests
from bs4 import BeautifulSoup

# ================= 配置区域 =================
SHANGHAI_TZ = pytz.timezone("Asia/Shanghai")
ASSET_ROOT = Path("assets") / "history"
TOP_BANNER_URL = "https://mmbiz.qpic.cn/mmbiz_gif/3hAJnwuyZuicicZkgJBUCCaricdibomDBrTzXgUR7FJnf11qGIo8nmKt6RxibXrb5s4RFb9UZ9UOHQy7fqQyI377Licw/0?wx_fmt=gif"
BOTTOM_BANNER_URL = "https://mmbiz.qpic.cn/mmbiz_gif/3hAJnwuyZuicicZkgJBUCCaricdibomDBrTzk57DCmhVC16o9ILH0Tn1YPEiarfLRRQSVFN2mJdeYibGnBPialPIzvojw/0?wx_fmt=gif"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
}

def download_image(image_url: str, target_dir: Path, file_stem: str) -> str:
    response = requests.get(image_url, stream=True, timeout=30, headers=HEADERS)
    response.raise_for_status()
    content = response.content
    if len(content) < 5000: raise ValueError("Image too small")
    
    digest = hashlib.sha1(content).hexdigest()[:8]
    ext = ".jpg" # 强制转为jpg确保微信显示兼容
    filename = f"{file_stem}-{digest}{ext}"
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / filename
    path.write_bytes(content)
    
    repo = os.environ.get("GITHUB_REPOSITORY", "duguBoss/daily-news-hub")
    branch = os.environ.get("GITHUB_REF_NAME", "main")
    return f"https://raw.githubusercontent.com/{repo}/{branch}/{path.as_posix()}"

def fetch_history_today() -> dict:
    now = datetime.datetime.now(SHANGHAI_TZ)
    month_day = f"{now.month}月{now.day}日"
    url = f"https://zh.wikipedia.org/zh-cn/Wikipedia:历史上的今天/{month_day}"
    
    resp = requests.get(url, headers=HEADERS, timeout=30)
    soup = BeautifulSoup(resp.text, 'html.parser')

    # 提取事件
    events = []
    for ul in soup.select('.mw-parser-output > ul')[:3]:
        for li in ul.find_all('li', recursive=False):
            text = li.get_text().strip()
            match = re.match(r'^(\d+年(?:前)?)[：:\-\—\s]*(.*)', text)
            if match:
                events.append({"year": match.group(1), "description": match.group(2)})
    
    # 提取图片
    images = []
    for img in soup.select('.mw-parser-output img'):
        src = img.get('src', '')
        if int(img.get('width', 0) or 0) > 100 and "upload.wikimedia.org" in src and not src.endswith('.svg'):
            if src.startswith('//'): src = 'https:' + src
            src = re.sub(r'/(\d+)px-', r'/800px-', src)
            if src not in images: images.append(src)

    # 下载图片
    date_str = now.strftime("%Y-%m-%d")
    target_dir = ASSET_ROOT / date_str
    downloaded = []
    for i, url in enumerate(images[:3]):
        try: downloaded.append(download_image(url, target_dir, f"hist-{i}"))
        except: continue
        
    return {"title": "带你看看历史上的今天发生了什么？", "date": month_day, "events": events, "images": downloaded}

def render_html(data: dict) -> str:
    parts = [
        "<section style=\"margin:0;padding:0;background:#ffffff;\">",
        f"<img src=\"{TOP_BANNER_URL}\" style=\"width:100%;display:block;\">",
        "<section style=\"max-width:760px;margin:0 auto;padding:2px;\">",
        "<section style=\"margin:12px 0 16px 0;padding:2px 2px 8px 2px;border-bottom:2px solid #1e293b;\">",
        f"<h1 style=\"margin:0;font-size:26px;color:#0f172a;font-weight:bold;\">{html.escape(data['title'])}</h1>",
        "</section>"
    ]
    for img in data['images']:
        parts.append(f"<section style=\"margin:0 0 10px 0;\"><img src=\"{html.escape(img)}\" style=\"width:100%;display:block;border-radius:4px;\"></section>")
    for event in data['events']:
        parts.append(f"<div style=\"margin:0 0 16px 0;padding-left:12px;border-left:4px solid #b59f7b;\"><p style=\"margin:0;color:#334155;font-size:16px;line-height:1.8;\"><strong style=\"color:#1e293b;\">{html.escape(event['year'])}</strong> {html.escape(event['description'])}</p></div>")
    parts.append(f"<img src=\"{BOTTOM_BANNER_URL}\" style=\"width:100%;display:block;\"></section></section>")
    return "".join(parts)

def main():
    try:
        data = fetch_history_today()
        if not data['events']: raise ValueError("No events found")
        data['wechat_html'] = render_html(data)
        
        filename = f"History_Today_{datetime.datetime.now(SHANGHAI_TZ).strftime('%Y-%m-%d')}.json"
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"✅ Success: {filename}")
    except Exception as e:
        print(f"❌ Error: {e}")
        raise e

if __name__ == "__main__":
    main()
