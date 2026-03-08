"""Slack data source — fetches channel messages from Slack workspaces via Web API."""

import logging
import time
from datetime import datetime, timedelta, timezone

import requests

logger = logging.getLogger("sources.slack")

API_BASE = "https://slack.com/api"

# In-memory user cache to avoid repeated API calls within a session
_user_cache: dict[str, str] = {}


class SlackSource:
    """Fetch channel messages from Slack workspaces using the Slack Web API."""

    def _headers(self, token: str) -> dict:
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        }

    def _api_call(
        self, method: str, token: str, params: dict = None,
        max_retries: int = 3, progress_cb=None,
    ) -> dict:
        """Make a Slack Web API call with retry logic.

        Args:
            method: Slack API method name (e.g. 'conversations.list')
            token: Slack User Token (xoxp-...)
            params: Query parameters
            max_retries: Number of retry attempts

        Returns:
            Parsed JSON response dict

        Raises:
            RuntimeError: If the API returns an error or all retries fail
        """
        url = f"{API_BASE}/{method}"
        headers = self._headers(token)

        for attempt in range(1, max_retries + 1):
            try:
                resp = requests.get(url, headers=headers, params=params or {}, timeout=30)
                resp.raise_for_status()
                data = resp.json()

                if not data.get("ok"):
                    error = data.get("error", "unknown_error")
                    # Rate limited — respect Retry-After header
                    if error == "ratelimited":
                        retry_after = int(resp.headers.get("Retry-After", 5))
                        msg = f"Slack API 限流，{retry_after}s 后重试..."
                        logger.warning(msg)
                        if progress_cb:
                            progress_cb("retry", msg)
                        time.sleep(retry_after)
                        continue
                    raise RuntimeError(f"Slack API error: {error}")

                return data

            except requests.RequestException as e:
                if attempt < max_retries:
                    wait = 2 ** attempt
                    msg = f"请求失败 ({e})，{wait}s 后重试 ({attempt}/{max_retries})..."
                    logger.warning(msg)
                    if progress_cb:
                        progress_cb("retry", msg, attempt=attempt, max_attempts=max_retries)
                    time.sleep(wait)
                else:
                    if progress_cb:
                        progress_cb("error", f"请求失败，已重试 {max_retries} 次: {e}")
                    raise

    # ----- Channel operations -----

    def fetch_channels(self, token: str, progress_cb=None) -> list[dict]:
        """Fetch list of public channels in the workspace.

        Returns list of {id, name, topic, num_members, is_member}.
        """
        logger.info("Fetching Slack channels")
        if progress_cb:
            progress_cb("progress", "正在获取 Slack 频道列表...", step="fetch_channels")

        all_channels = []
        cursor = None

        while True:
            params = {
                "types": "public_channel,private_channel",
                "exclude_archived": "true",
                "limit": 200,
            }
            if cursor:
                params["cursor"] = cursor

            data = self._api_call("conversations.list", token, params, progress_cb=progress_cb)

            for ch in data.get("channels", []):
                all_channels.append({
                    "id": ch["id"],
                    "name": ch.get("name", ""),
                    "topic": ch.get("topic", {}).get("value", ""),
                    "num_members": ch.get("num_members", 0),
                    "is_member": ch.get("is_member", False),
                })

            # Pagination
            cursor = data.get("response_metadata", {}).get("next_cursor", "")
            if not cursor:
                break

        logger.info("Fetched %d channels", len(all_channels))
        if progress_cb:
            progress_cb("progress", f"获取到 {len(all_channels)} 个频道", step="fetch_channels_done")

        return all_channels

    # ----- Message operations -----

    def fetch_messages(
        self, token: str, channel_id: str, days: int = 3,
        progress_cb=None, since_date: str = None, until_date: str = None,
    ) -> list[dict]:
        """Fetch messages from a channel within the specified time range.

        Args:
            token: Slack User Token
            channel_id: Channel ID (e.g. C01ABCDEF)
            days: Number of days to look back (default 3)
            progress_cb: Optional progress callback
            since_date: Start date (YYYY-MM-DD), overrides days
            until_date: End date (YYYY-MM-DD), defaults to today

        Returns list of normalized message dicts.
        """
        # Compute time range as Unix timestamps
        if since_date:
            oldest_dt = datetime.strptime(since_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        else:
            oldest_dt = datetime.now(timezone.utc) - timedelta(days=days)

        if until_date:
            latest_dt = datetime.strptime(until_date, "%Y-%m-%d").replace(
                hour=23, minute=59, second=59, tzinfo=timezone.utc
            )
        else:
            latest_dt = datetime.now(timezone.utc)

        oldest_ts = str(oldest_dt.timestamp())
        latest_ts = str(latest_dt.timestamp())

        logger.info("Fetching messages for channel %s (oldest=%s, latest=%s)", channel_id, oldest_ts, latest_ts)
        if progress_cb:
            progress_cb("progress", f"正在获取频道消息...", step="fetch_messages")

        all_messages = []
        cursor = None
        page = 0

        while True:
            params = {
                "channel": channel_id,
                "oldest": oldest_ts,
                "latest": latest_ts,
                "limit": 200,
                "inclusive": "true",
            }
            if cursor:
                params["cursor"] = cursor

            page += 1
            if progress_cb:
                progress_cb(
                    "progress",
                    f"正在获取消息 (第 {page} 页)...",
                    step="fetch_messages",
                    detail=f"已获取 {len(all_messages)} 条消息",
                )

            data = self._api_call("conversations.history", token, params, progress_cb=progress_cb)

            messages = data.get("messages", [])
            # Filter out channel_join/leave/bot messages, keep only real messages
            for msg in messages:
                if msg.get("subtype") in ("channel_join", "channel_leave", "channel_topic",
                                          "channel_purpose", "channel_name", "bot_add",
                                          "bot_remove"):
                    continue
                all_messages.append(msg)

            if not data.get("has_more", False):
                break
            cursor = data.get("response_metadata", {}).get("next_cursor", "")
            if not cursor:
                break

        logger.info("Fetched %d messages from channel %s", len(all_messages), channel_id)

        # Resolve user IDs to display names
        user_ids = set()
        for msg in all_messages:
            if msg.get("user"):
                user_ids.add(msg["user"])
        if user_ids:
            if progress_cb:
                progress_cb("progress", f"正在解析 {len(user_ids)} 个用户名...", step="resolve_users")
            self._resolve_users(token, user_ids, progress_cb=progress_cb)

        # Fetch thread replies for messages with threads
        threaded = [m for m in all_messages if m.get("reply_count", 0) > 0]
        if threaded:
            if progress_cb:
                progress_cb("progress", f"正在获取 {len(threaded)} 个讨论串的回复...", step="fetch_threads")
            for i, msg in enumerate(threaded, 1):
                try:
                    replies = self.fetch_thread_replies(token, channel_id, msg["ts"])
                    msg["_replies"] = replies
                    if progress_cb and i % 5 == 0:
                        progress_cb("progress", f"已获取 {i}/{len(threaded)} 个讨论串", step="fetch_threads")
                except Exception as e:
                    logger.warning("Failed to fetch thread %s: %s", msg["ts"], e)
                    msg["_replies"] = []

        # Normalize
        normalized = self._normalize_messages(all_messages)

        if progress_cb:
            progress_cb("progress", f"消息获取完成，共 {len(normalized)} 条", step="fetch_messages_done")

        return normalized

    def fetch_thread_replies(self, token: str, channel_id: str, thread_ts: str) -> list[dict]:
        """Fetch replies in a message thread.

        Returns raw reply messages (excluding the parent).
        """
        params = {
            "channel": channel_id,
            "ts": thread_ts,
            "limit": 100,
        }
        data = self._api_call("conversations.replies", token, params)
        replies = data.get("messages", [])
        # The first message is the parent, skip it
        return replies[1:] if len(replies) > 1 else []

    def _resolve_users(self, token: str, user_ids: set[str], progress_cb=None):
        """Resolve user IDs to display names, with in-memory caching."""
        to_resolve = [uid for uid in user_ids if uid not in _user_cache]

        for uid in to_resolve:
            try:
                data = self._api_call("users.info", token, {"user": uid})
                user = data.get("user", {})
                display_name = (
                    user.get("profile", {}).get("display_name")
                    or user.get("profile", {}).get("real_name")
                    or user.get("real_name")
                    or user.get("name")
                    or uid
                )
                _user_cache[uid] = display_name
            except Exception as e:
                logger.warning("Failed to resolve user %s: %s", uid, e)
                _user_cache[uid] = uid  # Fallback to raw ID

    def _get_user_name(self, user_id: str) -> str:
        """Get cached user display name."""
        return _user_cache.get(user_id, user_id)

    def _normalize_messages(self, raw_messages: list[dict]) -> list[dict]:
        """Normalize raw Slack messages to a simpler format."""
        result = []
        for msg in raw_messages:
            ts = float(msg.get("ts", 0))
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)

            # Extract reactions
            reactions = []
            for r in msg.get("reactions", []):
                reactions.append(f":{r['name']}: ({r.get('count', 1)})")

            # Normalize thread replies
            replies_preview = []
            for reply in msg.get("_replies", []):
                reply_ts = float(reply.get("ts", 0))
                reply_dt = datetime.fromtimestamp(reply_ts, tz=timezone.utc)
                replies_preview.append({
                    "user": self._get_user_name(reply.get("user", "")),
                    "text": reply.get("text", "")[:500],
                    "datetime": reply_dt.isoformat(),
                })

            result.append({
                "user": self._get_user_name(msg.get("user", "")),
                "text": msg.get("text", ""),
                "ts": msg.get("ts", ""),
                "datetime": dt.isoformat(),
                "date": dt.strftime("%Y-%m-%d"),
                "thread_reply_count": msg.get("reply_count", 0),
                "reactions": reactions,
                "replies_preview": replies_preview,
            })

        # Sort by timestamp (oldest first)
        result.sort(key=lambda m: m["ts"])
        return result
