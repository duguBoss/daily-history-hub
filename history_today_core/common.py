from __future__ import annotations

import argparse
import datetime as dt
import os

import opencc

from .constants import DEFAULT_LIMIT, DEFAULT_OUTPUT_DIR, DEFAULT_WIKIPEDIA_LANG, SHANGHAI_TZ

def build_user_agent() -> str:
    repository = os.environ.get("GITHUB_REPOSITORY", "duguBoss/daily-history-hub")
    contact = os.environ.get("WIKIMEDIA_CONTACT", "https://github.com/duguBoss/daily-history-hub")
    return f"daily-history-hub/1.0 ({contact}; repo={repository})"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Aggregate on-this-day data and produce a WeChat HTML article.")
    parser.add_argument("--date", help="Target date in YYYY-MM-DD format.")
    parser.add_argument("--month", type=int, help="Target month, used with --day.")
    parser.add_argument("--day", type=int, help="Target day, used with --month.")
    parser.add_argument("--lang", default=DEFAULT_WIKIPEDIA_LANG, help="Wikipedia language edition. Default: zh")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="Maximum number of merged events.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Directory for generated files.")
    return parser.parse_args()


def resolve_target_date(date_arg: str | None, month_arg: int | None, day_arg: int | None) -> dt.date:
    today = dt.datetime.now(SHANGHAI_TZ).date()
    if date_arg:
        return dt.date.fromisoformat(date_arg)
    if month_arg is not None or day_arg is not None:
        if month_arg is None or day_arg is None:
            raise ValueError("--month and --day must be provided together.")
        return dt.date(today.year, month_arg, day_arg)
    return today


def normalize_text(text: str) -> str:
    return " ".join((text or "").replace("\n", " ").split())


def to_simplified(text: str) -> str:
    if not text:
        return text
    converter = opencc.OpenCC("t2s")
    return converter.convert(text)


def log(message: str) -> None:
    print(f"[history_today] {message}", flush=True)
