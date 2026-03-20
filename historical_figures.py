from __future__ import annotations

import argparse
import datetime as dt
import json
import mimetypes
import os
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pytz
import requests

from history_today_core.output_render import render_wechat_html


SHANGHAI_TZ = pytz.timezone("Asia/Shanghai")
REQUEST_TIMEOUT = 30
PRIMARY_GEMINI_MODEL = "gemini-3-flash-preview"

DEFAULT_OUTPUT_ROOT = Path("output") / "historical_figure"
DEFAULT_ASSET_ROOT = Path("assets") / "generated" / "historical_figure"
STATE_FILE_NAME = "seen_figures.json"

SEED_TERMS = [
    "julius caesar",
    "napoleon bonaparte",
    "albert einstein",
    "cleopatra",
    "abraham lincoln",
    "william shakespeare",
    "winston churchill",
    "queen victoria",
    "socrates",
    "galileo galilei",
    "isaac newton",
    "charles darwin",
    "alexander the great",
    "queen elizabeth i",
    "leonardo da vinci",
    "christopher columbus",
    "joan of arc",
    "marie curie",
    "nelson mandela",
    "genghis khan",
    "augustus caesar",
]


def log(message: str) -> None:
    print(f"[historical_figure] {message}", flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate one daily historical figure with avatar and Gemini intro.")
    parser.add_argument("--date", help="Target date in YYYY-MM-DD format.")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT), help="Root folder for output JSON.")
    parser.add_argument("--asset-root", default=str(DEFAULT_ASSET_ROOT), help="Root folder for generated assets by date.")
    parser.add_argument("--seed-limit", type=int, default=len(SEED_TERMS), help="How many seed terms to query.")
    return parser.parse_args()


def resolve_target_date(date_arg: str | None) -> dt.date:
    if date_arg:
        return dt.date.fromisoformat(date_arg)
    return dt.datetime.now(SHANGHAI_TZ).date()


def build_user_agent() -> str:
    repository = os.environ.get("GITHUB_REPOSITORY", "duguBoss/daily-history-hub")
    contact = os.environ.get("WIKIMEDIA_CONTACT", "https://github.com/duguBoss/daily-history-hub")
    return f"daily-history-hub/1.0 ({contact}; repo={repository})"


def normalize_text(text: str) -> str:
    return " ".join((text or "").replace("\n", " ").split())


def normalize_name(name: str) -> str:
    return normalize_text(name).lower()


def github_asset_url(relative_path: Path) -> str:
    repository = os.environ.get("GITHUB_REPOSITORY", "duguBoss/daily-history-hub")
    branch = os.environ.get("GITHUB_REF_NAME", os.environ.get("DEFAULT_GIT_BRANCH", "main"))
    normalized = str(relative_path).replace("\\", "/")
    return f"https://raw.githubusercontent.com/{repository}/{branch}/{normalized}"


def cleanup_daily_dirs(root: Path, target_date: dt.date) -> None:
    root.mkdir(parents=True, exist_ok=True)
    keep = target_date.isoformat()
    for child in root.iterdir():
        if child.is_dir() and child.name != keep:
            shutil.rmtree(child, ignore_errors=True)


def cleanup_output_json_files(output_root: Path, target_date: dt.date) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    keep_name = f"History_Figure_{target_date.isoformat()}.json"
    for child in output_root.glob("History_Figure_*.json"):
        if child.name != keep_name:
            try:
                child.unlink()
            except Exception:
                pass


def load_seen_names(state_file: Path) -> set[str]:
    if not state_file.exists():
        return set()
    try:
        payload = json.loads(state_file.read_text(encoding="utf-8"))
    except Exception:
        return set()
    seen = payload.get("seen")
    if not isinstance(seen, list):
        return set()
    return {normalize_name(str(item)) for item in seen if str(item).strip()}


def save_seen_names(state_file: Path, seen: set[str]) -> None:
    state_file.parent.mkdir(parents=True, exist_ok=True)
    payload = {"seen": sorted(seen)}
    state_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def fetch_figures_by_term(term: str, api_key: str) -> list[dict[str, Any]]:
    url = f"https://api.api-ninjas.com/v1/historicalfigures?name={quote(term)}"
    response = requests.get(
        url,
        headers={"X-Api-Key": api_key, "User-Agent": build_user_agent()},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    data = response.json()
    return data if isinstance(data, list) else []


def fetch_person_detail(name: str, api_key: str) -> dict[str, Any]:
    entries = fetch_figures_by_term(name, api_key)
    target = normalize_name(name)
    for entry in entries:
        if normalize_name(str(entry.get("name", ""))) == target:
            return entry
    return entries[0] if entries else {"name": name}


def build_candidate_pool(seed_limit: int, api_key: str) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    terms = SEED_TERMS[: max(1, min(seed_limit, len(SEED_TERMS)))]

    for term in terms:
        try:
            items = fetch_figures_by_term(term, api_key)
        except Exception as exc:
            log(f"Seed query failed for '{term}': {exc}")
            continue

        for item in items:
            name = normalize_name(str(item.get("name", "")))
            if not name or name in seen_names:
                continue
            seen_names.add(name)
            candidates.append(item)

    return candidates


def choose_daily_figure(candidates: list[dict[str, Any]], seen_names: set[str], target_date: dt.date) -> dict[str, Any]:
    if not candidates:
        raise RuntimeError("No candidate figures available from API Ninjas.")

    unseen = [item for item in candidates if normalize_name(str(item.get("name", ""))) not in seen_names]
    if not unseen:
        log("All candidates have been used. Resetting seen list for a new cycle.")
        seen_names.clear()
        unseen = candidates

    index = target_date.toordinal() % len(unseen)
    return unseen[index]


def get_wikidata_image_url(name: str) -> str:
    try:
        search_url = (
            "https://www.wikidata.org/w/api.php?action=wbsearchentities"
            f"&search={quote(name)}&language=en&format=json&limit=1"
        )
        search_resp = requests.get(search_url, headers={"User-Agent": build_user_agent()}, timeout=REQUEST_TIMEOUT)
        search_resp.raise_for_status()
        search_payload = search_resp.json()
        entities = search_payload.get("search") or []
        if not entities:
            return ""

        qid = entities[0].get("id", "")
        if not qid:
            return ""

        entity_url = f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json"
        entity_resp = requests.get(entity_url, headers={"User-Agent": build_user_agent()}, timeout=REQUEST_TIMEOUT)
        entity_resp.raise_for_status()
        entity_payload = entity_resp.json()
        claims = (entity_payload.get("entities") or {}).get(qid, {}).get("claims", {})
        p18 = claims.get("P18") or []
        if not p18:
            return ""

        image_name = p18[0].get("mainsnak", {}).get("datavalue", {}).get("value", "")
        if not image_name:
            return ""

        return f"https://commons.wikimedia.org/wiki/Special:FilePath/{quote(image_name.replace(' ', '_'))}"
    except Exception:
        return ""


def guess_extension(content_type: str, url: str) -> str:
    guessed = mimetypes.guess_extension((content_type or "").split(";")[0].strip()) or ""
    if guessed in {".jpe", ".jpeg"}:
        return ".jpg"
    if guessed:
        return guessed
    suffix = Path(url.split("?")[0]).suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        return ".jpg" if suffix == ".jpeg" else suffix
    return ".jpg"


def download_avatar(image_url: str, output_dir: Path, base_name: str = "avatar") -> str:
    if not image_url:
        return ""

    response = requests.get(image_url, headers={"User-Agent": build_user_agent()}, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()

    extension = guess_extension(response.headers.get("Content-Type", ""), image_url)
    file_path = output_dir / f"{base_name}{extension}"
    file_path.write_bytes(response.content)
    return str(file_path)


def build_gemini_prompt(person: dict[str, Any], target_date: dt.date) -> str:
    name = normalize_text(str(person.get("name", "")))
    title = normalize_text(str(person.get("title", "")))
    info = person.get("info", "")
    info_text = normalize_text(info if isinstance(info, str) else json.dumps(info, ensure_ascii=False))

    return (
        "请根据下面人物资料，生成更适合微信公众号推荐分发的中文内容。"
        "只返回 JSON 对象，字段必须是 title、summary、content_text。"
        "写作要求："
        "1) title 18-28字，突出反差/转折/价值，不做夸张标题党；"
        "2) summary 90-130字，清楚告诉读者“为什么值得看”；"
        "3) content_text 共5段："
        "首段用强钩子切入并点明时代意义；"
        "中间3段给出关键经历、代表贡献、争议或局限（有信息密度）；"
        "末段给出今天的启发并抛出一个互动问题；"
        "4) 语言自然、有画面感、可读性强，避免空泛套话；"
        "5) 保持事实严谨，不编造信息。"
        f"\n\n目标日期：{target_date.isoformat()}"
        f"\n人物姓名：{name}"
        f"\n人物标签：{title}"
        f"\n资料：{info_text}"
    )


def fallback_profile(person: dict[str, Any], target_date: dt.date) -> dict[str, str]:
    name = normalize_text(str(person.get("name", "未知人物")))
    title = normalize_text(str(person.get("title", "历史人物"))) or "历史人物"
    info = person.get("info", "")
    info_text = normalize_text(info if isinstance(info, str) else json.dumps(info, ensure_ascii=False))
    summary = (
        f"{target_date.month}月{target_date.day}日的历史人物是{name}。"
        f"这位{title}如何在时代压力中做出关键选择，至今仍影响我们的认知方式与行动策略。"
        "读完你会更清楚：真正改变历史的，往往不是身份，而是判断与执行力。"
    )
    content = (
        f"很多人第一次听到{name}，会把他/她简单归类为“{title}”。但真正值得追问的是："
        "在那个复杂时代，为什么偏偏是他/她做出了后来被历史放大的决定？\n\n"
        f"从资料来看，{name}并不是在真空中行动。政治结构、社会情绪、技术条件与个人经历交织在一起，"
        "共同塑造了其关键路径。理解这一层，才能看懂人物背后的时代逻辑。\n\n"
        f"再看其核心贡献：无论是思想、制度还是作品，{name}都改变了当时人们处理问题的方式。"
        "这类改变的价值，往往不是一时轰动，而是长期渗透到后续规则和日常生活。\n\n"
        f"当然，关于{name}也存在争议和局限。把人物放回具体历史语境，既看到成就也看到代价，"
        "才是更成熟的历史阅读方法。\n\n"
        f"如果把{name}放到今天，你认为他/她最值得我们借鉴的一条原则是什么？"
        f"资料摘录：{info_text[:320]}"
    )
    return {
        "title": f"{name}为何改变了历史走向？",
        "summary": summary,
        "content_text": content,
    }


def generate_profile_with_gemini(person: dict[str, Any], target_date: dt.date) -> dict[str, str]:
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        log("Missing GEMINI_API_KEY, using fallback profile")
        return fallback_profile(person, target_date)

    prompt = build_gemini_prompt(person, target_date)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{PRIMARY_GEMINI_MODEL}:generateContent"

    try:
        response = requests.post(
            url,
            headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.4, "responseMimeType": "application/json"},
            },
            timeout=REQUEST_TIMEOUT * 3,
        )
        response.raise_for_status()
        payload = response.json()
        candidates = payload.get("candidates") or []
        if not candidates:
            raise RuntimeError(f"Gemini returned no candidates: {payload}")

        parts = ((candidates[0].get("content") or {}).get("parts")) or []
        text = "".join(part.get("text", "") for part in parts).strip()
        if not text:
            raise RuntimeError("Gemini returned empty text")

        data = json.loads(text)
        title = normalize_text(str(data.get("title", "")))
        summary = normalize_text(str(data.get("summary", "")))
        content_text = str(data.get("content_text", "")).strip()
        if not title or not summary or not content_text:
            raise RuntimeError(f"Incomplete Gemini payload: {data}")

        return {"title": title, "summary": summary, "content_text": content_text}
    except Exception as exc:
        log(f"Gemini profile generation failed: {exc}")
        return fallback_profile(person, target_date)


def save_payload(payload: dict[str, Any], output_root: Path, target_date: dt.date) -> Path:
    output_root.mkdir(parents=True, exist_ok=True)
    output_path = output_root / f"History_Figure_{target_date.isoformat()}.json"
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def main() -> None:
    args = parse_args()
    target_date = resolve_target_date(args.date)

    api_ninjas_key = os.environ.get("API_NINJAS_API_KEY", "")
    if not api_ninjas_key:
        raise RuntimeError("Missing API_NINJAS_API_KEY")

    output_root = Path(args.output_root)
    asset_root = Path(args.asset_root)
    state_file = output_root / STATE_FILE_NAME

    cleanup_output_json_files(output_root, target_date)
    cleanup_daily_dirs(asset_root, target_date)

    asset_day_dir = asset_root / target_date.isoformat()
    asset_day_dir.mkdir(parents=True, exist_ok=True)

    seen_names = load_seen_names(state_file)
    candidates = build_candidate_pool(args.seed_limit, api_ninjas_key)
    log(f"Candidate figures fetched: {len(candidates)}")

    selected = choose_daily_figure(candidates, seen_names, target_date)
    selected_name = normalize_text(str(selected.get("name", "")))
    if not selected_name:
        raise RuntimeError("Selected figure has empty name")

    detail = fetch_person_detail(selected_name, api_ninjas_key)
    log(f"Selected figure: {selected_name}")

    avatar_source_url = get_wikidata_image_url(selected_name)
    avatar_local = ""
    if avatar_source_url:
        try:
            avatar_local = download_avatar(avatar_source_url, asset_day_dir, base_name="avatar")
            log(f"Avatar saved: {avatar_local}")
        except Exception as exc:
            log(f"Avatar download failed: {exc}")

    cover_urls: list[str] = []
    if avatar_local:
        rel = Path(avatar_local) if Path(avatar_local).is_absolute() else (Path.cwd() / avatar_local)
        cover_urls = [github_asset_url(rel.relative_to(Path.cwd()))]

    profile = generate_profile_with_gemini(detail, target_date)
    html = render_wechat_html(profile["title"], profile["summary"], profile["content_text"], cover_urls)

    payload = {
        "title": profile["title"],
        "seo_summary": profile["summary"],
        "cover": cover_urls,
        "wechat_html": html,
    }

    output_path = save_payload(payload, output_root, target_date)
    seen_names.add(normalize_name(selected_name))
    save_seen_names(state_file, seen_names)

    log(f"Saved JSON: {output_path}")
    log(f"Saved cover count: {len(cover_urls)}")


if __name__ == "__main__":
    main()
