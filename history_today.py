import datetime
import hashlib
import json
import os
import re
import time
from pathlib import Path
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import pytz

SHANGHAI_TZ = pytz.timezone("Asia/Shanghai")
ASSET_ROOT = Path("assets") / "history"
TOP_BANNER_URL = "https://mmbiz.qpic.cn/mmbiz_gif/3hAJnwuyZuicicZkgJBUCCaricdibomDBrTzXgUR7FJnf11qGIo8nmKt6RxibXrb5s4RFb9UZ9UOHQy7fqQyI377Licw/0?wx_fmt=gif"
BOTTOM_BANNER_URL = "https://mmbiz.qpic.cn/mmbiz_gif/3hAJnwuyZuicicZkgJBUCCaricdibomDBrTzk57DCmhVC16o9ILH0Tn1YPEiarfLRRQSVFN2mJdeYibGnBPialPIzvojw/0?wx_fmt=gif"

def save_image(img_url, target_dir):
    try:
        import requests
        resp = requests.get(img_url, timeout=20)
        resp.raise_for_status()
        digest = hashlib.sha1(resp.content).hexdigest()[:8]
        filename = f"hist-{digest}.jpg"
        target_dir.mkdir(parents=True, exist_ok=True)
        path = target_dir / filename
        path.write_bytes(resp.content)
        repo = os.environ.get("GITHUB_REPOSITORY", "duguBoss/daily-news-hub")
        branch = os.environ.get("GITHUB_REF_NAME", "main")
        return f"https://raw.githubusercontent.com/{repo}/{branch}/{path.as_posix()}"
    except Exception as e:
        print(f"Img save error: {e}")
        return None

def fetch_data():
    now = datetime.datetime.now(SHANGHAI_TZ)
    month_day = f"{now.month}月{now.day}日"
    url = f"https://zh.wikipedia.org/zh-cn/Wikipedia:历史上的今天/{month_day}"
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, wait_until="networkidle")
        content = page.content()
        browser.close()

    soup = BeautifulSoup(content, 'html.parser')
    events = []
    for li in soup.find_all('li'):
        text = li.get_text().strip()
        match = re.match(r'^(\d{1,4}年(?:前)?)[：:\-\—\s]*(.*)', text)
        if match and len(match.group(2)) > 5:
            events.append({"year": match.group(1), "description": match.group(2)})
            
    images = []
    for img in soup.find_all('img'):
        src = img.get('src', '')
        if int(img.get('width', 0) or 0) > 200 and "upload.wikimedia.org" in src and not src.lower().endswith('.svg'):
            if src.startswith('//'): src = 'https:' + src
            src = re.sub(r'/(\d+)px-', r'/800px-', src)
            if src not in images: images.append(src)
            
    return {"title": "带你看看历史上的今天发生了什么？", "date": month_day, "events": events, "images": images}

def render_html(data):
    parts = ["<section style='margin:0;padding:0;background:#ffffff;'><img src='{}' style='width:100%;display:block;'>".format(TOP_BANNER_URL)]
    parts.append("<section style='max-width:760px;margin:0 auto;padding:2px;'><section style='margin:12px 0;border-bottom:2px solid #1e293b;'><h1 style='font-size:24px;'>{}</h1></section>".format(data['title']))
    for img in data['images'][:3]:
        parts.append(f"<img src='{img}' style='width:100%;margin-bottom:10px;border-radius:4px;'>")
    for e in data['events'][:15]:
        parts.append(f"<div style='border-left:4px solid #b59f7b;padding-left:10px;margin-bottom:15px;'><p style='font-size:16px;'><strong>{e['year']}</strong> {e['description']}</p></div>")
    parts.append(f"<img src='{BOTTOM_BANNER_URL}' style='width:100%;'></section></section>")
    return "".join(parts)

def main():
    data = fetch_data()
    if len(data['events']) < 5: raise ValueError("No valid events found")
    
    date_str = datetime.datetime.now(SHANGHAI_TZ).strftime("%Y-%m-%d")
    target_dir = ASSET_ROOT / date_str
    data['images'] = [save_image(i, target_dir) for i in data['images'][:3] if save_image(i, target_dir)]
    data['wechat_html'] = render_html(data)
    
    with open(f"History_Today_{date_str}.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
