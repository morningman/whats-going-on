"""Mailman 2 Pipermail fetcher - fetches emails from Pipermail archives."""

import email
import email.header
import gzip
import json
import logging
import mailbox
import os
import tempfile
from datetime import datetime

import requests

from . import BaseFetcher

logger = logging.getLogger("fetchers.pipermail")

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "emails")

# Pipermail uses month name format for archive URLs
MONTH_NAMES = [
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


class PipermailFetcher(BaseFetcher):
    fetcher_type = "pipermail"

    def fetch_emails(self, config: dict, date: str) -> list[dict]:
        """Fetch emails for a specific date from Pipermail mbox archive."""
        year_month = date[:7]
        year = int(date[:4])
        month = int(date[5:7])

        # Check cache first
        cache = self._load_cache(config, year_month)
        if cache is not None:
            result = self._filter_by_date(cache, date)
            logger.info("[Pipermail] Cache hit for %s — %d emails on %s", year_month, len(result), date)
            return result

        base_url = config.get("base_url", "").rstrip("/")
        auth = config.get("auth")
        month_name = MONTH_NAMES[month]

        # Try .txt.gz first, then .txt
        mbox_text = None
        for suffix in [f"{year}-{month_name}.txt.gz", f"{year}-{month_name}.txt"]:
            url = f"{base_url}/{suffix}"
            try:
                kwargs = {"timeout": 30}
                if auth:
                    kwargs["auth"] = (auth.get("username", ""), auth.get("password", ""))
                logger.info("[Pipermail] Trying %s", url)
                resp = requests.get(url, **kwargs)
                if resp.status_code == 200:
                    if suffix.endswith(".gz"):
                        mbox_text = gzip.decompress(resp.content).decode("utf-8", errors="replace")
                    else:
                        mbox_text = resp.text
                    logger.info("[Pipermail] Downloaded %s — %d bytes", url, len(mbox_text))
                    break
                else:
                    logger.debug("[Pipermail] %s returned status %d", url, resp.status_code)
            except Exception as e:
                logger.debug("[Pipermail] Failed to fetch %s: %s", url, e)
                continue

        if mbox_text is None:
            logger.warning("[Pipermail] No mbox archive found for %s", year_month)
            return []

        emails = self._parse_mbox(mbox_text)
        logger.info("[Pipermail] Parsed %d emails from mbox", len(emails))
        self._save_cache(config, year_month, emails)
        result = self._filter_by_date(emails, date)
        logger.info("[Pipermail] %d emails match date %s", len(result), date)
        return result

    def test_connection(self, config: dict) -> dict:
        """Test connection by trying to access the archive index."""
        base_url = config.get("base_url", "").rstrip("/")
        auth = config.get("auth")
        try:
            kwargs = {"timeout": 10}
            if auth:
                kwargs["auth"] = (auth.get("username", ""), auth.get("password", ""))
            logger.info("[Pipermail] Testing connection to %s", base_url)
            resp = requests.get(base_url + "/", **kwargs)
            resp.raise_for_status()
            logger.info("[Pipermail] Connection test OK")
            return {"ok": True, "message": "Connected to Pipermail archive."}
        except Exception as e:
            logger.warning("[Pipermail] Connection test failed: %s", e)
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

            date_str = msg.get("Date", "")
            epoch = 0
            date_day = ""
            try:
                parsed_date = email.utils.parsedate_to_datetime(date_str)
                epoch = int(parsed_date.timestamp())
                date_day = parsed_date.strftime("%Y-%m-%d")
            except Exception:
                pass

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
        base_url = config.get("base_url", "")
        safe_name = base_url.replace("https://", "").replace("http://", "").replace("/", "_").rstrip("_")
        return f"pipermail_{safe_name}_{year_month}"

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