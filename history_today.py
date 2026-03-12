import datetime
import json
import os
import requests
import pytz

SHANGHAI_TZ = pytz.timezone("Asia/Shanghai")
ASSET_ROOT = Path("assets") / "history"
TOP_BANNER_URL = "https://mmbiz.qpic.cn/mmbiz_gif/3hAJnwuyZuicicZkgJBUCCaricdibomDBrTzXgUR7FJnf11qGIo8nmKt6RxibXrb5s4RFb9UZ9UOHQy7fqQyI377Licw/0?wx_fmt=gif"
BOTTOM_BANNER_URL = "https://mmbiz.qpic.cn/mmbiz_gif/3hAJnwuyZuicicZkgJBUCCaricdibomDBrTzk57DCmhVC16o9ILH0Tn1YPEiarfLRRQSVFN2mJdeYibGnBPialPIzvojw/0?wx_fmt=gif"

def fetch_via_api():
    now = datetime.datetime.now(SHANGHAI_TZ)
    # 使用一个可靠的免费 API: https://api.todayonhistory.com/
    url = f"https://api.todayonhistory.com/v1/history?month={now.month}&day={now.day}"
    print(f"[*] 请求 API: {url}")
    
    resp = requests.get(url, timeout=30)
    data = resp.json()
    
    # 解析数据结构
    events = []
    # 假设 API 返回格式为 {'data': [...]}
    raw_list = data.get('data', [])
    for item in raw_list[:15]:
        events.append({
            "year": f"{item.get('year')}年",
            "description": item.get('title')
        })
        
    return {
        "title": "带你看看历史上的今天发生了什么？",
        "date": f"{now.month}月{now.day}日",
        "events": events,
        "images": [] # API通常不提供图片，我们保留此字段为空
    }

def render_html(data):
    # 此处省略：代码逻辑同之前，保持 UI 不变
    parts = ["<section style='margin:0;padding:0;background:#ffffff;'><img src='{}' style='width:100%;display:block;'>".format(TOP_BANNER_URL)]
    parts.append("<section style='max-width:760px;margin:0 auto;padding:2px;'><section style='margin:12px 0;border-bottom:2px solid #1e293b;'><h1 style='font-size:24px;'>{}</h1></section>".format(data['title']))
    for e in data['events']:
        parts.append(f"<div style='border-left:4px solid #b59f7b;padding-left:10px;margin-bottom:15px;'><p style='font-size:16px;'><strong style='color:#1e293b;'>{e['year']}</strong> {e['description']}</p></div>")
    parts.append(f"<img src='{BOTTOM_BANNER_URL}' style='width:100%;'></section></section>")
    return "".join(parts)

def main():
    try:
        data = fetch_via_html_alternative() # 如果 API 不行，我们用下面的兜底
    except:
        # 如果 API 挂了，我们用 Wikipedia 原始网页但避开复杂的解析
        data = fetch_via_requests_simple()
        
    if not data['events']: raise ValueError("Fatal: No events found from any source")
    
    date_str = datetime.datetime.now(SHANGHAI_TZ).strftime("%Y-%m-%d")
    data['wechat_html'] = render_html(data)
    
    with open(f"History_Today_{date_str}.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def fetch_via_requests_simple():
    # 这是一个超简单的维基请求方案，直接抓取原始文本
    now = datetime.datetime.now(SHANGHAI_TZ)
    url = f"https://zh.wikipedia.org/zh-cn/Wikipedia:历史上的今天/{now.month}月{now.day}日"
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
    # 使用正则直接提取 li 中的内容，不依赖复杂的 DOM
    events = re.findall(r'<li>(\d{1,4}年(?:前)?)[：:\-\—\s]*(.*?)</li>', r.text)
    return {"events": [{"year": e[0], "description": e[1]} for e in events[:15]]}

if __name__ == "__main__":
    main()
