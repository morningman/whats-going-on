"""Slack API client — fetches channels, messages, and thread replies.

Standalone implementation for the daily report tool.
"""

import logging
import time
from datetime import datetime, timedelta, timezone

import requests

logger = logging.getLogger("slack_client")

API_BASE = "https://slack.com/api"

# In-memory user cache to avoid repeated API calls within a session
_user_cache: dict[str, str] = {}


class SlackClient:
    """Fetch channel messages from a Slack workspace using the Slack Web API."""

    def __init__(self, token: str):
        self.token = token
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        }

    def _api_call(self, method: str, params: dict = None, max_retries: int = 3) -> dict:
        """Make a Slack Web API call with retry and rate-limit handling.

        Args:
            method: Slack API method (e.g. 'conversations.list')
            params: Query parameters
            max_retries: Number of retry attempts

        Returns:
            Parsed JSON response dict

        Raises:
            RuntimeError: If the API returns an error or all retries fail
        """
        url = f"{API_BASE}/{method}"

        for attempt in range(1, max_retries + 1):
            try:
                resp = requests.get(url, headers=self._headers, params=params or {}, timeout=30)
                resp.raise_for_status()
                data = resp.json()

                if not data.get("ok"):
                    error = data.get("error", "unknown_error")
                    if error == "ratelimited":
                        retry_after = int(resp.headers.get("Retry-After", 5))
                        logger.warning("Rate limited, retrying in %ds...", retry_after)
                        time.sleep(retry_after)
                        continue
                    raise RuntimeError(f"Slack API error: {error}")

                return data

            except requests.RequestException as e:
                if attempt < max_retries:
                    wait = 2 ** attempt
                    logger.warning("Request failed (%s), retrying in %ds (%d/%d)...",
                                   e, wait, attempt, max_retries)
                    time.sleep(wait)
                else:
                    raise

    def fetch_channels(self) -> list[dict]:
        """Fetch all public channels in the workspace.

        Returns list of {id, name, topic, num_members}.
        """
        logger.info("Fetching Slack channels...")
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

            data = self._api_call("conversations.list", params)

            for ch in data.get("channels", []):
                all_channels.append({
                    "id": ch["id"],
                    "name": ch.get("name", ""),
                    "topic": ch.get("topic", {}).get("value", ""),
                    "num_members": ch.get("num_members", 0),
                })

            cursor = data.get("response_metadata", {}).get("next_cursor", "")
            if not cursor:
                break

        logger.info("Fetched %d channels", len(all_channels))
        return all_channels

    def fetch_messages(
        self, channel_id: str, since_date: str, until_date: str,
    ) -> list[dict]:
        """Fetch messages from a channel within the specified date range.

        Args:
            channel_id: Channel ID (e.g. C01ABCDEF)
            since_date: Start date (YYYY-MM-DD), inclusive
            until_date: End date (YYYY-MM-DD), inclusive

        Returns list of normalized message dicts.
        """
        oldest_dt = datetime.strptime(since_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        latest_dt = datetime.strptime(until_date, "%Y-%m-%d").replace(
            hour=23, minute=59, second=59, tzinfo=timezone.utc
        )

        oldest_ts = str(oldest_dt.timestamp())
        latest_ts = str(latest_dt.timestamp())

        logger.info("Fetching messages for channel %s (%s ~ %s)",
                     channel_id, since_date, until_date)

        all_messages = []
        cursor = None

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

            data = self._api_call("conversations.history", params)

            for msg in data.get("messages", []):
                # Filter out system messages
                if msg.get("subtype") in (
                    "channel_join", "channel_leave", "channel_topic",
                    "channel_purpose", "channel_name", "bot_add", "bot_remove",
                ):
                    continue
                all_messages.append(msg)

            if not data.get("has_more", False):
                break
            cursor = data.get("response_metadata", {}).get("next_cursor", "")
            if not cursor:
                break

        logger.info("Fetched %d messages from channel %s", len(all_messages), channel_id)

        # Resolve user IDs to display names
        user_ids = {msg["user"] for msg in all_messages if msg.get("user")}
        if user_ids:
            self._resolve_users(user_ids)

        # Fetch thread replies for messages with threads
        threaded = [m for m in all_messages if m.get("reply_count", 0) > 0]
        if threaded:
            logger.info("Fetching %d thread replies...", len(threaded))
            for msg in threaded:
                try:
                    replies = self._fetch_thread_replies(channel_id, msg["ts"])
                    msg["_replies"] = replies
                except Exception as e:
                    logger.warning("Failed to fetch thread %s: %s", msg["ts"], e)
                    msg["_replies"] = []

        # Normalize
        return self._normalize_messages(all_messages)

    def _fetch_thread_replies(self, channel_id: str, thread_ts: str) -> list[dict]:
        """Fetch replies in a message thread (excluding the parent)."""
        params = {
            "channel": channel_id,
            "ts": thread_ts,
            "limit": 100,
        }
        data = self._api_call("conversations.replies", params)
        replies = data.get("messages", [])
        return replies[1:] if len(replies) > 1 else []

    def _resolve_users(self, user_ids: set[str]):
        """Resolve user IDs to display names, with in-memory caching."""
        to_resolve = [uid for uid in user_ids if uid not in _user_cache]

        for uid in to_resolve:
            try:
                data = self._api_call("users.info", {"user": uid})
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
                _user_cache[uid] = uid

    def _get_user_name(self, user_id: str) -> str:
        """Get cached user display name."""
        return _user_cache.get(user_id, user_id)

    def _normalize_messages(self, raw_messages: list[dict]) -> list[dict]:
        """Normalize raw Slack messages to a simpler format."""
        result = []
        for msg in raw_messages:
            ts = float(msg.get("ts", 0))
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)

            # Reactions
            reactions = []
            for r in msg.get("reactions", []):
                reactions.append(f":{r['name']}: ({r.get('count', 1)})")

            # Thread replies
            replies = []
            for reply in msg.get("_replies", []):
                reply_ts = float(reply.get("ts", 0))
                reply_dt = datetime.fromtimestamp(reply_ts, tz=timezone.utc)
                replies.append({
                    "user": self._get_user_name(reply.get("user", "")),
                    "text": reply.get("text", ""),
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
                "replies": replies,
            })

        result.sort(key=lambda m: m["ts"])
        return result
