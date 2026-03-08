"""Local file-system cache for email, GitHub, and Slack raw data.

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
SLACK_CACHE_DIR = os.path.join(BASE_CACHE_DIR, "slack")


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
# GitHub activity cache  (per-day granularity)
# ---------------------------------------------------------------------------

def _github_cache_path(repo_id: str, date: str) -> str:
    _ensure_dir(GITHUB_CACHE_DIR)
    return os.path.join(GITHUB_CACHE_DIR, f"{repo_id}_{date}.json")


def load_github_cache(repo_id: str, date: str) -> dict | None:
    """Load cached GitHub activity for a single day.

    Returns None if:
    - the date is today (always fetch live), or
    - no cache file exists.
    """
    if is_today(date):
        return None
    path = _github_cache_path(repo_id, date)
    if os.path.exists(path):
        logger.info("[缓存命中] GitHub 缓存: repo=%s, date=%s", repo_id, date)
        with open(path, "r") as f:
            return json.load(f)
    return None


def save_github_cache(repo_id: str, date: str, activity: dict):
    """Persist GitHub activity data for a single day to local cache file.

    Skips saving if *date* is today (today's data changes constantly).
    """
    if is_today(date):
        return
    path = _github_cache_path(repo_id, date)
    with open(path, "w") as f:
        json.dump(activity, f, ensure_ascii=False, indent=2)
    logger.info("[缓存保存] GitHub 缓存写入: repo=%s, date=%s", repo_id, date)


def load_github_cache_range(repo_id: str, dates: list[str]) -> tuple[dict, list[str]]:
    """Check per-day cache for a list of dates.

    Returns:
        (cached_data, missing_dates)
        - cached_data: {date: {"pulls": [...], "issues": [...]}}
        - missing_dates: dates that need to be fetched from the API
    """
    cached_data = {}
    missing_dates = []
    for date in dates:
        day_cache = load_github_cache(repo_id, date)
        if day_cache is not None:
            cached_data[date] = day_cache
        else:
            missing_dates.append(date)
    logger.info(
        "[缓存检查] GitHub 缓存范围: repo=%s, 总天数=%d, 命中=%d, 缺失=%d",
        repo_id, len(dates), len(cached_data), len(missing_dates),
    )
    return cached_data, missing_dates


def _split_activity_by_day(activity: dict) -> dict[str, dict]:
    """Split combined activity into per-day buckets.

    PRs are bucketed by merged_at (if merged) or created_at (otherwise).
    Issues are bucketed by updated_at (covers both new issues and new comments).

    Returns {date_str: {"pulls": [...], "issues": [...]}}.
    """
    day_buckets: dict[str, dict] = {}

    for pr in activity.get("pulls", []):
        # Use merged_at for merged PRs, created_at for open/closed PRs
        date = (pr.get("merged_at") or pr.get("created_at", ""))[:10]
        if not date:
            continue
        day_buckets.setdefault(date, {"pulls": [], "issues": []})
        day_buckets[date]["pulls"].append(pr)

    for issue in activity.get("issues", []):
        date = issue.get("updated_at", "")[:10]
        if not date:
            continue
        day_buckets.setdefault(date, {"pulls": [], "issues": []})
        day_buckets[date]["issues"].append(issue)

    return day_buckets


def save_github_cache_days(repo_id: str, activity: dict):
    """Split activity by date and save each day independently.

    Today's data is skipped (always re-fetched).
    """
    day_buckets = _split_activity_by_day(activity)
    saved = 0
    for date, day_data in day_buckets.items():
        if is_today(date):
            continue
        save_github_cache(repo_id, date, day_data)
        saved += 1
    logger.info("[缓存保存] GitHub 按天缓存: repo=%s, 共 %d 天保存", repo_id, saved)


# ---------------------------------------------------------------------------
# Slack message cache  (per-day granularity)
# ---------------------------------------------------------------------------

def _slack_cache_path(channel_key: str, date: str) -> str:
    _ensure_dir(SLACK_CACHE_DIR)
    return os.path.join(SLACK_CACHE_DIR, f"{channel_key}_{date}.json")


def load_slack_cache(channel_key: str, date: str) -> list | None:
    """Load cached Slack messages for *channel_key* on *date*.

    channel_key is typically '{workspace_id}__{channel_id}'.

    Returns None if:
    - the date is today (always fetch live), or
    - no cache file exists.
    """
    if is_today(date):
        return None
    path = _slack_cache_path(channel_key, date)
    if os.path.exists(path):
        logger.info("[缓存命中] Slack 缓存: channel=%s, date=%s", channel_key, date)
        with open(path, "r") as f:
            return json.load(f)
    return None


def save_slack_cache(channel_key: str, date: str, messages: list):
    """Persist Slack message data to local cache file.

    Skips saving if *date* is today.
    """
    if is_today(date):
        return
    path = _slack_cache_path(channel_key, date)
    with open(path, "w") as f:
        json.dump(messages, f, ensure_ascii=False, indent=2)
    logger.info("[缓存保存] Slack 缓存写入: channel=%s, date=%s, count=%d",
                channel_key, date, len(messages))


def load_slack_cache_range(channel_key: str, dates: list[str]) -> tuple[dict, list[str]]:
    """Check per-day cache for a list of dates.

    Returns:
        (cached_data, missing_dates)
        - cached_data: {date: [messages]}
        - missing_dates: dates that need to be fetched from the API
    """
    cached_data = {}
    missing_dates = []
    for date in dates:
        day_cache = load_slack_cache(channel_key, date)
        if day_cache is not None:
            cached_data[date] = day_cache
        else:
            missing_dates.append(date)
    logger.info(
        "[缓存检查] Slack 缓存范围: channel=%s, 总天数=%d, 命中=%d, 缺失=%d",
        channel_key, len(dates), len(cached_data), len(missing_dates),
    )
    return cached_data, missing_dates


def _split_messages_by_day(messages: list) -> dict[str, list]:
    """Split messages into per-day buckets based on their date field.

    Returns {date_str: [messages]}.
    """
    day_buckets: dict[str, list] = {}
    for msg in messages:
        date = msg.get("date", "")
        if not date:
            continue
        day_buckets.setdefault(date, [])
        day_buckets[date].append(msg)
    return day_buckets


def save_slack_cache_days(channel_key: str, messages: list):
    """Split messages by date and save each day independently.

    Today's data is skipped (always re-fetched).
    """
    day_buckets = _split_messages_by_day(messages)
    saved = 0
    for date, day_msgs in day_buckets.items():
        if is_today(date):
            continue
        save_slack_cache(channel_key, date, day_msgs)
        saved += 1
    logger.info("[缓存保存] Slack 按天缓存: channel=%s, 共 %d 天保存", channel_key, saved)

