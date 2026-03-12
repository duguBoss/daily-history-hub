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
import requests

SHANGHAI_TZ = pytz.timezone("Asia/Shanghai")
ASSET_ROOT = Path("assets") / "history"

def fetch_data():
    now = datetime.datetime.now(SHANGHAI_TZ)
    month_day = f"{now.month}月{now.day}日"
    url = f"https://zh.wikipedia.org/wiki/Wikipedia:历史上的今天/{month_day}"
    
    events = []
    images = []

    with sync_playwright() as p:
        # 伪装层：设置真实的 User-Agent 和 viewport
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        print(f"正在访问: {url}")
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        time.sleep(3) # 给页面JS一点时间执行
        
        content = page.content()
        browser.close()

    soup = BeautifulSoup(content, 'html.parser')
    
    # 扩大查找范围：查找所有 li，并正则匹配年份
    for li in soup.find_all('li'):
        text = li.get_text().strip()
        # 匹配 "1912年" 或 "1912年 " 开头的行
        match = re.match(r'^(\d{1,4}年(?:前)?)[：:\-\—\s]*(.*)', text)
        if match and len(match.group(2)) > 5:
            events.append({"year": match.group(1), "description": match.group(2)})
            
    # 图片提取逻辑
    for img in soup.find_all('img'):
        src = img.get('src', '')
        if int(img.get('width', 0) or 0) > 150 and "upload.wikimedia.org" in src and not src.lower().endswith('.svg'):
            if src.startswith('//'): src = 'https:' + src
            src = re.sub(r'/(\d+)px-', r'/800px-', src)
            if src not in images: images.append(src)
            
    print(f"抓取完成，共 {len(events)} 条事件")
    return {"title": "带你看看历史上的今天发生了什么？", "date": month_day, "events": events, "images": images}

# ... [保持 download_image, render_html, main 函数不变] ...
