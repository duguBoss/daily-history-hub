from __future__ import annotations

import datetime as dt
import hashlib
import mimetypes
import os
import shutil
from pathlib import Path
from urllib.parse import quote

import requests

from .common import build_user_agent
from .constants import REQUEST_TIMEOUT

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


def github_asset_url(relative_path: Path) -> str:
    repository = os.environ.get("GITHUB_REPOSITORY", "duguBoss/daily-history-hub")
    branch = os.environ.get("GITHUB_REF_NAME", os.environ.get("DEFAULT_GIT_BRANCH", "main"))
    normalized = str(relative_path).replace("\\", "/")
    return f"https://raw.githubusercontent.com/{repository}/{branch}/{normalized}"


def cleanup_old_assets(today: dt.date, asset_root: Path, keep_days: int = 7) -> None:
    if not asset_root.exists():
        return
    cutoff = today - dt.timedelta(days=keep_days)
    for child in asset_root.iterdir():
        if not child.is_dir():
            continue
        try:
            folder_date = dt.date.fromisoformat(child.name)
        except ValueError:
            continue
        if folder_date < cutoff:
            shutil.rmtree(child, ignore_errors=True)


def download_image(url: str, target_dir: Path) -> str:
    if not url:
        return ""
    response = requests.get(url, headers={"User-Agent": build_user_agent()}, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    extension = guess_extension(response.headers.get("Content-Type", ""), url)
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    file_path = target_dir / f"{digest}{extension}"
    
    # 强制重新写入文件以绕过可能的文件缓存机制
    file_path.write_bytes(response.content)
    return str(file_path)
