"""Local file-system cache for email and GitHub raw data.

Caching rules:
- Data for dates **before today** is considered immutable and cached permanently.
- Data for **today** is always fetched live (cache is skipped).
"""

import json
import logging
import os
from datetime import datetime

logger = logging.getLogger("cache")

BASE_CACHE_DIR = os.path.join(os.path.dirname(__file__), "data", "cache")
EMAIL_CACHE_DIR = os.path.join(BASE_CACHE_DIR, "emails")
GITHUB_CACHE_DIR = os.path.join(BASE_CACHE_DIR, "github")


def _ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)


def is_today(date_str: str) -> bool:
    """Check whether *date_str* (YYYY-MM-DD) is today."""
    return date_str == datetime.now().strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Email cache
# ---------------------------------------------------------------------------

def _email_cache_path(list_id: str, date: str) -> str:
    _ensure_dir(EMAIL_CACHE_DIR)
    return os.path.join(EMAIL_CACHE_DIR, f"{list_id}_{date}.json")


def load_email_cache(list_id: str, date: str) -> list | None:
    """Load cached emails for *list_id* on *date*.

    Returns None if:
    - the date is today (always fetch live), or
    - no cache file exists.
    """
    if is_today(date):
        return None
    path = _email_cache_path(list_id, date)
    if os.path.exists(path):
        logger.info("[缓存命中] 邮件缓存: list=%s, date=%s", list_id, date)
        with open(path, "r") as f:
            return json.load(f)
    return None


def save_email_cache(list_id: str, date: str, emails: list):
    """Persist email data to local cache file."""
    path = _email_cache_path(list_id, date)
    with open(path, "w") as f:
        json.dump(emails, f, ensure_ascii=False, indent=2)
    logger.info("[缓存保存] 邮件缓存写入: list=%s, date=%s, count=%d", list_id, date, len(emails))


# ---------------------------------------------------------------------------
# GitHub activity cache
# ---------------------------------------------------------------------------

def _github_cache_path(repo_id: str, date: str, days: int) -> str:
    _ensure_dir(GITHUB_CACHE_DIR)
    return os.path.join(GITHUB_CACHE_DIR, f"{repo_id}_{date}_{days}d.json")


def load_github_cache(repo_id: str, date: str, days: int) -> dict | None:
    """Load cached GitHub activity.

    The cache key is (repo_id, date, days).  Because *date* is always set to
    today when the request is made, the cache is effectively valid for one day
    and automatically expires the next day (the key changes).

    Returns None if no cache file exists.
    """
    path = _github_cache_path(repo_id, date, days)
    if os.path.exists(path):
        logger.info("[缓存命中] GitHub 缓存: repo=%s, date=%s, days=%d", repo_id, date, days)
        with open(path, "r") as f:
            return json.load(f)
    return None


def save_github_cache(repo_id: str, date: str, days: int, activity: dict):
    """Persist GitHub activity data to local cache file."""
    path = _github_cache_path(repo_id, date, days)
    with open(path, "w") as f:
        json.dump(activity, f, ensure_ascii=False, indent=2)
    logger.info("[缓存保存] GitHub 缓存写入: repo=%s, date=%s, days=%d", repo_id, date, days)
