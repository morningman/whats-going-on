"""Apache Pony Mail fetcher - fetches emails from lists.apache.org API."""

import json
import os
import email
import mailbox
import tempfile
from datetime import datetime, timezone

import requests

from . import BaseFetcher

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "emails")


class PonyMailFetcher(BaseFetcher):
    fetcher_type = "ponymail"

    def fetch_emails(self, config: dict, date: str) -> list[dict]:
        """Fetch emails for a specific date from Pony Mail mbox API."""
        year_month = date[:7]  # "2026-02" from "2026-02-27"
        list_name = config.get("list", "dev")
        domain = config.get("domain", "")
        base_url = config.get("base_url", "https://lists.apache.org")

        # Check cache first
        cache = self._load_cache(config, year_month)
        if cache is not None:
            return self._filter_by_date(cache, date)

        # Fetch from mbox API
        url = f"{base_url}/api/mbox.lua"
        params = {"list": list_name, "domain": domain, "d": year_month}

        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()

        emails = self._parse_mbox(resp.text)

        # Cache the month's data
        self._save_cache(config, year_month, emails)

        return self._filter_by_date(emails, date)

    def test_connection(self, config: dict) -> dict:
        """Test connection by hitting the stats API."""
        base_url = config.get("base_url", "https://lists.apache.org")
        list_name = config.get("list", "dev")
        domain = config.get("domain", "")
        try:
            url = f"{base_url}/api/stats.lua"
            resp = requests.get(
                url, params={"list": list_name, "domain": domain}, timeout=10
            )
            resp.raise_for_status()
            data = resp.json()
            total = sum(data.get("emails", {}).values()) if "emails" in data else 0
            return {"ok": True, "message": f"Connected. Found {total} emails in archive."}
        except Exception as e:
            return {"ok": False, "message": str(e)}

    def _parse_mbox(self, mbox_text: str) -> list[dict]:
        """Parse mbox format text into unified email dicts."""
        results = []
        with tempfile.NamedTemporaryFile(mode="w", suffix=".mbox", delete=False) as f:
            f.write(mbox_text)
            tmp_path = f.name
        try:
            mbox = mailbox.mbox(tmp_path)
            for msg in mbox:
                parsed = self._parse_message(msg)
                if parsed:
                    results.append(parsed)
        finally:
            os.unlink(tmp_path)
        return results

    def _parse_message(self, msg) -> dict | None:
        """Parse a single email message into unified format."""
        try:
            subject = self._decode_header(msg.get("Subject", ""))
            from_addr = self._decode_header(msg.get("From", ""))
            msg_id = msg.get("Message-ID", "").strip("<>")
            in_reply_to = msg.get("In-Reply-To", "").strip("<>")
            references = msg.get("References", "")

            # Extract body
            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        payload = part.get_payload(decode=True)
                        if payload:
                            body = payload.decode("utf-8", errors="replace")
                            break
            else:
                payload = msg.get_payload(decode=True)
                if payload:
                    body = payload.decode("utf-8", errors="replace")

            # Parse date
            date_str = msg.get("Date", "")
            epoch = 0
            date_day = ""
            try:
                parsed_date = email.utils.parsedate_to_datetime(date_str)
                epoch = int(parsed_date.timestamp())
                date_day = parsed_date.strftime("%Y-%m-%d")
            except Exception:
                pass

            # Thread ID is the root message reference
            thread_id = ""
            if references:
                thread_id = references.strip().split()[0].strip("<>")
            elif not in_reply_to:
                thread_id = msg_id

            return {
                "id": msg_id,
                "subject": subject,
                "from": from_addr,
                "body": body,
                "date": date_day,
                "epoch": epoch,
                "in_reply_to": in_reply_to,
                "thread_id": thread_id or msg_id,
            }
        except Exception:
            return None

    def _decode_header(self, value: str) -> str:
        """Decode email header value."""
        if not value:
            return ""
        parts = email.header.decode_header(value)
        decoded = []
        for part, charset in parts:
            if isinstance(part, bytes):
                decoded.append(part.decode(charset or "utf-8", errors="replace"))
            else:
                decoded.append(part)
        return " ".join(decoded)

    def _cache_key(self, config: dict, year_month: str) -> str:
        list_name = config.get("list", "dev")
        domain = config.get("domain", "").replace(".", "_")
        return f"{domain}_{list_name}_{year_month}"

    def _cache_path(self, config: dict, year_month: str) -> str:
        os.makedirs(DATA_DIR, exist_ok=True)
        return os.path.join(DATA_DIR, f"{self._cache_key(config, year_month)}.json")

    def _load_cache(self, config: dict, year_month: str) -> list[dict] | None:
        path = self._cache_path(config, year_month)
        if os.path.exists(path):
            with open(path, "r") as f:
                return json.load(f)
        return None

    def _save_cache(self, config: dict, year_month: str, emails: list[dict]):
        path = self._cache_path(config, year_month)
        with open(path, "w") as f:
            json.dump(emails, f, ensure_ascii=False, indent=2)

    def _filter_by_date(self, emails: list[dict], date: str) -> list[dict]:
        return [e for e in emails if e.get("date") == date]
