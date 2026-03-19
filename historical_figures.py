from __future__ import annotations

import argparse
import os
import time
from urllib.parse import quote

import requests


API_NINJAS_KEY = os.environ.get("API_NINJAS_API_KEY", "")
if not API_NINJAS_KEY:
    print("❌ 请先设置环境变量 API_NINJAS_API_KEY！")
    exit(1)

headers_ninjas = {"X-Api-Key": API_NINJAS_KEY}

SEED_TERMS = [
    "julius caesar", "napoleon bonaparte", "albert einstein", "cleopatra",
    "abraham lincoln", "william shakespeare", "winston churchill",
    "queen victoria", "socrates", "galileo galilei", "isaac newton",
    "charles darwin", "alexander the great", "queen elizabeth i",
    "leonardo da vinci", "christopher columbus", "joan of arc",
    "marie curie", "nelson mandela", "genghis khan", "augustus caesar"
]


def get_wikidata_image(name: str) -> str | None:
    try:
        search_url = f"https://www.wikidata.org/w/api.php?action=wbsearchentities&search={quote(name)}&language=en&format=json&limit=1"
        search_resp = requests.get(search_url, timeout=8).json()
        if not search_resp.get("search"):
            return None
        qid = search_resp["search"][0]["id"]

        entity_url = f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json"
        entity_resp = requests.get(entity_url, timeout=8).json()
        claims = entity_resp.get("entities", {}).get(qid, {}).get("claims", {})
        if "P18" in claims and claims["P18"]:
            image_name = claims["P18"][0]["mainsnak"]["datavalue"]["value"]
            image_url = f"https://commons.wikimedia.org/wiki/Special:FilePath/{quote(image_name.replace(' ', '_'))}"
            return image_url
    except:
        pass
    return None


def fetch_historical_figures(limit: int = 30) -> list[dict]:
    print("正在获取国际历史人物列表...\n")
    people_list = []
    seen = set()

    for term in SEED_TERMS:
        url = f"https://api.api-ninjas.com/v1/historicalfigures?name={quote(term)}"
        try:
            resp = requests.get(url, headers=headers_ninjas, timeout=10)
            if resp.status_code == 200:
                for item in resp.json():
                    name = item.get("name", "").strip()
                    if name and name.lower() not in seen:
                        seen.add(name.lower())
                        people_list.append(item)
            else:
                print(f"搜索 {term} 失败: {resp.status_code}")
        except Exception as e:
            print(f"搜索 {term} 出错: {e}")
        time.sleep(0.3)

    print(f"=== 第一步完成：共获取 {len(people_list)} 位国际历史人物 ===\n")
    return people_list[:limit]


def display_figures(people_list: list[dict]) -> None:
    print("正在查询详情并获取人物肖像图片...\n")

    for i, person in enumerate(people_list, 1):
        name = person.get("name", "")
        title = person.get("title", "N/A")

        print(f"{i:2d}. **{name}**  —  {title}")

        try:
            detail_resp = requests.get(
                f"https://api.api-ninjas.com/v1/historicalfigures?name={quote(name)}",
                headers=headers_ninjas, timeout=10
            )
            if detail_resp.status_code == 200:
                details = detail_resp.json()
                if details:
                    info = details[0].get("info", {})
                    if isinstance(info, str):
                        print("   简介:", info[:300] + "..." if len(info) > 300 else info)
                    elif isinstance(info, dict):
                        print("   简介:", str(info)[:300] + "...")
                    else:
                        print("   简介: 无详细简介")
        except:
            pass

        image_url = get_wikidata_image(name)
        if image_url:
            print(f"   🖼️  肖像图片: {image_url}")
            print(f"   ![{name}]({image_url})\n")
        else:
            print("   🖼️  未找到公开肖像图片\n")

        print("-" * 90)
        time.sleep(0.5)

    print("\n✅ 全部完成！")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="获取国际历史人物列表及肖像图片")
    parser.add_argument("--limit", type=int, default=30, help="限制获取人物数量，默认30")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    people_list = fetch_historical_figures(args.limit)
    display_figures(people_list)


if __name__ == "__main__":
    main()