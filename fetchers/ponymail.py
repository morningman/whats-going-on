"""Apache Pony Mail fetcher - fetches emails from lists.apache.org API."""

import json
import logging
import os
import email
import mailbox
import tempfile
import time
from datetime import datetime, timezone

import requests
from requests.exceptions import ConnectionError as RequestsConnectionError

from . import BaseFetcher

logger = logging.getLogger("fetchers.ponymail")

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "emails")


class PonyMailFetcher(BaseFetcher):
    fetcher_type = "ponymail"

    # Max retries for transient connection errors
    MAX_RETRIES = 3
    RETRY_BACKOFF = 2  # seconds, doubled each retry

    def _build_request_kwargs(self, cookie: str = "", timeout: int = 30) -> dict:
        """Build common request kwargs including auth cookies if provided."""
        kwargs = {"timeout": timeout}
        if cookie:
            kwargs["headers"] = {"Cookie": cookie}
            logger.debug("[PonyMail] Using cookie authentication")
        return kwargs

    def _request_with_retry(self, method: str, url: str, cookie: str = "", **kwargs) -> requests.Response:
        """Make an HTTP request with retry logic for transient connection errors."""
        req_kwargs = self._build_request_kwargs(cookie, timeout=kwargs.pop("timeout", 30))
        req_kwargs.update(kwargs)
        last_error = None

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                resp = requests.request(method, url, **req_kwargs)
                return resp
            except RequestsConnectionError as e:
                last_error = e
                logger.warning(
                    "[PonyMail] Connection error (attempt %d/%d): %s",
                    attempt, self.MAX_RETRIES, e,
                )
                if attempt < self.MAX_RETRIES:
                    wait = self.RETRY_BACKOFF * (2 ** (attempt - 1))
                    logger.info("[PonyMail] Retrying in %ds...", wait)
                    time.sleep(wait)

        raise last_error

    def fetch_emails(self, config: dict, date: str, cookie: str = "") -> list[dict]:
        """Fetch emails for a specific date from Pony Mail mbox API."""
        year_month = date[:7]  # "2026-02" from "2026-02-27"
        list_name = config.get("list", "dev")
        domain = config.get("domain", "")
        base_url = config.get("base_url", "https://lists.apache.org")

        # Check cache first
        cache = self._load_cache(config, year_month)
        if cache is not None:
            result = self._filter_by_date(cache, date)
            logger.info("[PonyMail] Cache hit for %s@%s %s — %d emails on %s", list_name, domain, year_month, len(result), date)
            return result

        # Fetch from mbox API
        url = f"{base_url}/api/mbox.lua"
        params = {"list": list_name, "domain": domain, "d": year_month}

        logger.info("[PonyMail] Fetching mbox from %s params=%s", url, params)
        resp = self._request_with_retry("GET", url, cookie, params=params)
        resp.raise_for_status()
        logger.info("[PonyMail] Response: status=%d, content_length=%d", resp.status_code, len(resp.text))

        emails = self._parse_mbox(resp.text)
        logger.info("[PonyMail] Parsed %d emails from mbox", len(emails))

        # Cache the month's data
        self._save_cache(config, year_month, emails)

        result = self._filter_by_date(emails, date)
        logger.info("[PonyMail] %d emails match date %s", len(result), date)
        return result

    def fetch_permalink_map(self, config: dict, year_month: str, cookie: str = "") -> dict:
        """Fetch PonyMail mid hashes for a given month via the stats API.

        Returns a dict mapping raw Message-ID (without angle brackets)
        to PonyMail permalink mid, e.g.:
            {"CABxxx@mail.gmail.com": "qng54l2k714nrp..."}

        The mid can be used to build a permalink:
            https://lists.apache.org/thread/{mid}
        """
        list_name = config.get("list", "dev")
        domain = config.get("domain", "")
        base_url = config.get("base_url", "https://lists.apache.org")

        url = f"{base_url}/api/stats.lua"
        params = {
            "list": list_name,
            "domain": domain,
            "d": year_month,
            "emailsOnly": "true",
        }

        logger.info("[PonyMail] Fetching permalink map from %s for %s@%s %s", url, list_name, domain, year_month)
        try:
            resp = self._request_with_retry("GET", url, cookie, params=params)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            logger.exception("[PonyMail] Failed to fetch permalink map")
            return {}

        mid_map = {}
        for em in data.get("emails", []):
            raw_mid = em.get("message-id", "").strip("<>")
            pony_mid = em.get("mid", "")
            if raw_mid and pony_mid:
                mid_map[raw_mid] = pony_mid

        logger.info("[PonyMail] Built permalink map with %d entries", len(mid_map))
        return mid_map


    def test_connection(self, config: dict, cookie: str = "") -> dict:
        """Test connection by hitting the stats API."""
        base_url = config.get("base_url", "https://lists.apache.org")
        list_name = config.get("list", "dev")
        domain = config.get("domain", "")
        try:
            url = f"{base_url}/api/stats.lua"
            logger.info("[PonyMail] Testing connection to %s", url)
            resp = self._request_with_retry(
                "GET", url, cookie, params={"list": list_name, "domain": domain}, timeout=10
            )
            resp.raise_for_status()
            data = resp.json()
            total = sum(data.get("emails", {}).values()) if "emails" in data else 0
            logger.info("[PonyMail] Connection test OK — %d emails in archive", total)
            return {"ok": True, "message": f"Connected. Found {total} emails in archive."}
        except Exception as e:
            logger.warning("[PonyMail] Connection test failed: %s", e)
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
