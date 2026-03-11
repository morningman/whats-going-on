"""What's Going On - Information aggregation center for email lists, Slack, and GitHub."""

import copy
import json
import logging
import logging.handlers
import os
import re
import sys
from datetime import datetime, timedelta

import queue
import threading

import requests as http_requests
from flask import Flask, Response, jsonify, render_template, request, stream_with_context

from fetchers import get_fetcher
import asf_auth
import cache
import summarizer

app = Flask(__name__)


def setup_logging(log_dir: str | None = None):
    """Configure logging with file rotation and console output.

    Logs are written to <log_dir>/app.log with daily rotation, keeping 30 days.
    """
    if log_dir is None:
        log_dir = os.path.join(os.path.dirname(__file__), "log")
    os.makedirs(log_dir, exist_ok=True)

    log_file = os.path.join(log_dir, "app.log")

    # Root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # Formatter
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # File handler — daily rotation, keep 30 days
    file_handler = logging.handlers.TimedRotatingFileHandler(
        log_file, when="midnight", interval=1, backupCount=30,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(fmt)
    file_handler.suffix = "%Y-%m-%d"

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(fmt)

    # Avoid duplicate handlers on reload
    root_logger.handlers.clear()
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    # Tone down noisy third-party loggers
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    logging.info("Logging initialized — log_dir=%s", log_dir)


logger = logging.getLogger("app")

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")
CONFIG_EXAMPLE_PATH = os.path.join(os.path.dirname(__file__), "config.example.json")


def load_config() -> dict:
    """Load config from config.json, falling back to example."""
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r") as f:
            config = json.load(f)
    elif os.path.exists(CONFIG_EXAMPLE_PATH):
        with open(CONFIG_EXAMPLE_PATH, "r") as f:
            config = json.load(f)
    else:
        config = {
            "mailing_lists": [],
            "llm": {"active_provider": "", "providers": []},
            "fetch_days": 7,
        }
    return _migrate_config(config)


def _migrate_config(config: dict) -> dict:
    """Migrate old config format (single provider) to new multi-provider format."""
    llm = config.get("llm", {})
    if "providers" not in llm:
        # Old format: {provider, api_key, model}
        old_key = llm.get("api_key", "")
        old_model = llm.get("model", "claude-sonnet-4-20250514")
        config["llm"] = {
            "active_provider": "anthropic",
            "providers": [
                {
                    "id": "anthropic",
                    "name": "Anthropic Claude",
                    "type": "anthropic",
                    "base_url": "",
                    "auth_token": old_key,
                    "model": old_model,
                }
            ],
        }
    return config


def _mask_tokens(config: dict) -> dict:
    """Mask auth tokens, passwords, and cookies in config for safe API response."""
    safe = copy.deepcopy(config)
    for p in safe.get("llm", {}).get("providers", []):
        token = p.get("auth_token", "")
        if token and len(token) > 12:
            p["auth_token"] = token[:8] + "..." + token[-4:]
        elif token:
            p["auth_token"] = "***"
    # Mask centralized ASF auth cookie
    asf = safe.get("asf_auth", {})
    cookie = asf.get("cookie", "")
    if cookie and len(cookie) > 12:
        asf["cookie"] = cookie[:8] + "..." + cookie[-4:]
    elif cookie:
        asf["cookie"] = "***"
    # Mask ASF password
    password = asf.get("password", "")
    if password:
        asf["password"] = "***"
    # Mask GitHub token
    gh_token = safe.get("github", {}).get("token", "")
    if gh_token and len(gh_token) > 12:
        safe["github"]["token"] = gh_token[:8] + "..." + gh_token[-4:]
    elif gh_token:
        safe.setdefault("github", {})["token"] = "***"
    # Mask Slack tokens
    slack_token = safe.get("slack", {}).get("user_token", "")
    if slack_token and len(slack_token) > 12:
        safe["slack"]["user_token"] = slack_token[:8] + "..." + slack_token[-4:]
    elif slack_token:
        safe.setdefault("slack", {})["user_token"] = "***"
    # Mask Slack push webhook URL
    slack_push_url = safe.get("slack", {}).get("push_webhook_url", "")
    if slack_push_url and len(slack_push_url) > 20:
        safe.setdefault("slack", {})["push_webhook_url"] = slack_push_url[:40] + "..." + slack_push_url[-6:]
    elif slack_push_url:
        safe.setdefault("slack", {})["push_webhook_url"] = "***"
    # Mask Feishu webhook URL (contains secret token)
    feishu_url = safe.get("feishu", {}).get("webhook_url", "")
    if feishu_url and len(feishu_url) > 20:
        safe.setdefault("feishu", {})["webhook_url"] = feishu_url[:40] + "..." + feishu_url[-6:]
    elif feishu_url:
        safe.setdefault("feishu", {})["webhook_url"] = "***"
    # Mask Feishu Bot A app_secret
    bot_a = safe.get("feishu", {}).get("bot_a", {})
    bot_a_secret = bot_a.get("app_secret", "")
    if bot_a_secret and len(bot_a_secret) > 8:
        bot_a["app_secret"] = bot_a_secret[:4] + "..." + bot_a_secret[-4:]
    elif bot_a_secret:
        bot_a["app_secret"] = "***"
    # Mask Feishu Bot B webhook URL
    bot_b = safe.get("feishu", {}).get("bot_b", {})
    bot_b_url = bot_b.get("webhook_url", "")
    if bot_b_url and len(bot_b_url) > 20:
        bot_b["webhook_url"] = bot_b_url[:40] + "..." + bot_b_url[-6:]
    elif bot_b_url:
        bot_b["webhook_url"] = "***"
    return safe


def _restore_masked_tokens(new_config: dict) -> dict:
    """Restore masked auth tokens, passwords, and cookies from existing saved config."""
    if not os.path.exists(CONFIG_PATH):
        return new_config
    try:
        with open(CONFIG_PATH, "r") as f:
            old_config = json.load(f)
        old_config = _migrate_config(old_config)
    except Exception:
        return new_config

    old_providers = {
        p["id"]: p for p in old_config.get("llm", {}).get("providers", [])
    }
    for p in new_config.get("llm", {}).get("providers", []):
        token = p.get("auth_token", "")
        if "..." in token or token == "***":
            old_p = old_providers.get(p["id"])
            if old_p:
                p["auth_token"] = old_p.get("auth_token", "")

    # Restore masked centralized ASF auth cookie
    old_asf = old_config.get("asf_auth", {})
    new_asf = new_config.get("asf_auth", {})
    cookie = new_asf.get("cookie", "")
    if cookie and ("..." in cookie or cookie == "***"):
        new_asf["cookie"] = old_asf.get("cookie", "")
    # Restore masked ASF password
    password = new_asf.get("password", "")
    if password == "***":
        new_asf["password"] = old_asf.get("password", "")

    # Restore masked GitHub token
    old_gh = old_config.get("github", {})
    new_gh = new_config.get("github", {})
    gh_token = new_gh.get("token", "")
    if gh_token and ("..." in gh_token or gh_token == "***"):
        new_gh["token"] = old_gh.get("token", "")

    # Restore masked Slack token
    old_slack = old_config.get("slack", {})
    new_slack = new_config.get("slack", {})
    slack_token = new_slack.get("user_token", "")
    if slack_token and ("..." in slack_token or slack_token == "***"):
        new_slack["user_token"] = old_slack.get("user_token", "")
    # Restore masked Slack push webhook URL
    slack_push_url = new_slack.get("push_webhook_url", "")
    if slack_push_url and ("..." in slack_push_url or slack_push_url == "***"):
        new_slack["push_webhook_url"] = old_slack.get("push_webhook_url", "")

    # Restore masked Feishu webhook URL
    old_feishu = old_config.get("feishu", {})
    new_feishu = new_config.get("feishu", {})
    feishu_url = new_feishu.get("webhook_url", "")
    if feishu_url and ("..." in feishu_url or feishu_url == "***"):
        new_feishu["webhook_url"] = old_feishu.get("webhook_url", "")
    # Restore masked Feishu Bot A app_secret
    old_bot_a = old_feishu.get("bot_a", {})
    new_bot_a = new_feishu.get("bot_a", {})
    bot_a_secret = new_bot_a.get("app_secret", "")
    if bot_a_secret and ("..." in bot_a_secret or bot_a_secret == "***"):
        new_bot_a["app_secret"] = old_bot_a.get("app_secret", "")
    # Restore masked Feishu Bot B webhook URL
    old_bot_b = old_feishu.get("bot_b", {})
    new_bot_b = new_feishu.get("bot_b", {})
    bot_b_url = new_bot_b.get("webhook_url", "")
    if bot_b_url and ("..." in bot_b_url or bot_b_url == "***"):
        new_bot_b["webhook_url"] = old_bot_b.get("webhook_url", "")

    return new_config


def save_config(config: dict):
    """Save config to config.json.

    Also syncs back to the source directory so that rebuilds preserve
    settings changes made through the UI.
    """
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    logger.info("Config saved to %s", CONFIG_PATH)

    # Sync back to source directory if running from output/
    _sync_config_to_source(config)


def _sync_config_to_source(config: dict):
    """If running from an output/ subdirectory, also save config to the
    parent (source) directory so that rebuilds don't lose user changes."""
    try:
        app_dir = os.path.dirname(os.path.abspath(__file__))
        parent_dir = os.path.dirname(app_dir)
        # Check if we're in an output/ subdirectory
        if os.path.basename(app_dir) == "output" and os.path.isdir(parent_dir):
            source_config = os.path.join(parent_dir, "config.json")
            with open(source_config, "w") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            logger.debug("Config synced back to source: %s", source_config)
    except Exception as e:
        logger.warning("Failed to sync config to source directory: %s", e)


# --- Page routes ---

@app.route("/")
def dashboard():
    return render_template("dashboard.html", active_page="dashboard")


@app.route("/email")
def email_page():
    return render_template("email.html", active_page="email")


@app.route("/slack")
def slack_page():
    return render_template("slack.html", active_page="slack")


@app.route("/github")
def github_page():
    return render_template("github.html", active_page="github")


@app.route("/settings")
def settings():
    return render_template("settings.html", active_page="settings")


# --- Config API ---

@app.route("/api/config", methods=["GET", "POST"])
def api_config():
    if request.method == "GET":
        logger.debug("GET /api/config")
        config = load_config()
        safe = _mask_tokens(config)
        return jsonify(safe)
    else:
        logger.info("POST /api/config — saving new configuration")
        new_config = request.get_json()
        if not new_config:
            logger.warning("POST /api/config — invalid JSON body")
            return jsonify({"error": "Invalid JSON"}), 400
        new_config = _restore_masked_tokens(new_config)
        save_config(new_config)
        return jsonify({"ok": True})


# --- Lists API ---

@app.route("/api/lists")
def api_lists():
    config = load_config()
    lists = [
        {"id": ml["id"], "name": ml["name"], "type": ml["type"], "private": ml.get("private", False)}
        for ml in config.get("mailing_lists", [])
    ]
    logger.debug("GET /api/lists — returning %d lists", len(lists))
    return jsonify(lists)


# --- Emails API ---

@app.route("/api/emails")
def api_emails():
    list_id = request.args.get("list_id", "")
    date = request.args.get("date", "")
    if not list_id or not date:
        logger.warning("GET /api/emails — missing list_id or date")
        return jsonify({"error": "list_id and date are required"}), 400

    logger.info("GET /api/emails — list_id=%s, date=%s", list_id, date)
    config = load_config()
    ml = _find_list(config, list_id)
    if not ml:
        logger.warning("GET /api/emails — list '%s' not found", list_id)
        return jsonify({"error": f"List '{list_id}' not found"}), 404

    # Check private list authentication
    cookie = _get_cookie_for_list(config, ml)
    if ml.get("private", False) and not cookie:
        msg = f"List '{ml['name']}' is private and requires ASF authentication. Please log in on the Settings page."
        logger.warning("GET /api/emails — %s", msg)
        return jsonify({"error": msg}), 403

    try:
        fetcher = get_fetcher(ml["type"])
        emails = fetcher.fetch_emails(ml["config"], date, cookie=cookie)
        logger.info("GET /api/emails — fetched %d emails for %s on %s", len(emails), list_id, date)
        return jsonify({"emails": emails, "count": len(emails)})
    except Exception as e:
        logger.exception("GET /api/emails — error fetching emails for %s on %s", list_id, date)
        return jsonify({"error": str(e)}), 500


# --- Digest API ---

@app.route("/api/digest", methods=["GET", "POST"])
def api_digest():
    list_id = request.args.get("list_id", "")
    date = request.args.get("date", "")
    if not list_id or not date:
        logger.warning("%s /api/digest — missing list_id or date", request.method)
        return jsonify({"error": "list_id and date are required"}), 400

    config = load_config()
    ml = _find_list(config, list_id)
    if not ml:
        logger.warning("%s /api/digest — list '%s' not found", request.method, list_id)
        return jsonify({"error": f"List '{list_id}' not found"}), 404

    if request.method == "GET":
        logger.debug("GET /api/digest — list_id=%s, date=%s", list_id, date)
        digest = summarizer.load_digest(list_id, date)
        if digest:
            logger.info("GET /api/digest — returning cached digest for %s on %s", list_id, date)
            return jsonify(digest)
        return jsonify({"summary": None, "email_count": 0})

    # POST - generate new digest
    logger.info("POST /api/digest — generating digest for %s on %s", list_id, date)
    # Check private list authentication
    cookie = _get_cookie_for_list(config, ml)
    if ml.get("private", False) and not cookie:
        msg = f"List '{ml['name']}' is private and requires ASF authentication. Please log in on the Settings page."
        logger.warning("POST /api/digest — %s", msg)
        return jsonify({"error": msg}), 403

    try:
        fetcher = get_fetcher(ml["type"])
        emails = fetcher.fetch_emails(ml["config"], date, cookie=cookie)
        llm_config = config.get("llm", {})
        digest = summarizer.generate_digest(
            emails, list_id, ml["name"], date, llm_config
        )
        logger.info("POST /api/digest — digest generated for %s on %s (%d emails)", list_id, date, digest.get("email_count", 0))
        return jsonify(digest)
    except Exception as e:
        logger.exception("POST /api/digest — error generating digest for %s on %s", list_id, date)
        return jsonify({"error": str(e)}), 500


# --- Email SSE streaming endpoint ---


@app.route("/api/email/digest/stream")
def api_email_digest_stream():
    """SSE endpoint: stream progress while fetching emails and generating digest."""
    list_id = request.args.get("list_id", "")
    start_date = request.args.get("start_date", "")
    end_date = request.args.get("end_date", "")
    try:
        days = int(request.args.get("days", "3"))
    except ValueError:
        days = 3
    if not start_date and days not in (1, 3, 7):
        days = 3
    lang = request.args.get("lang", "zh")
    if lang not in ("zh", "en"):
        lang = "zh"

    if not list_id:
        def err_gen():
            yield _sse_event({"type": "error", "message": "list_id is required"})
        return Response(err_gen(), mimetype="text/event-stream")

    config = load_config()
    ml = _find_list(config, list_id)
    if not ml:
        def err_gen():
            yield _sse_event({"type": "error", "message": f"邮件组 '{list_id}' 未找到"})
        return Response(err_gen(), mimetype="text/event-stream")

    # Check private list authentication
    cookie = _get_cookie_for_list(config, ml)
    if ml.get("private", False) and not cookie:
        def err_gen():
            yield _sse_event({
                "type": "error",
                "message": f"邮件组 '{ml['name']}' 是私有列表，需要 ASF 认证。请在设置页面登录。",
            })
        return Response(err_gen(), mimetype="text/event-stream")

    logger.info(
        "SSE /api/email/digest/stream — list=%s (%s), days=%d, start_date=%s, end_date=%s",
        list_id, ml["name"], days, start_date, end_date,
    )

    q = queue.Queue()

    def progress_cb(event_type, message, **kwargs):
        event = {"type": event_type, "message": message}
        event.update(kwargs)
        q.put(event)

    def worker():
        try:
            # Build date list
            dates = []
            if start_date and end_date:
                # Use explicit date range
                try:
                    sd = datetime.strptime(start_date, "%Y-%m-%d")
                    ed = datetime.strptime(end_date, "%Y-%m-%d")
                    d = sd
                    while d <= ed:
                        dates.append(d.strftime("%Y-%m-%d"))
                        d += timedelta(days=1)
                except ValueError:
                    dates = []
            if not dates:
                for i in range(days):
                    d = datetime.now() - timedelta(days=i)
                    dates.append(d.strftime("%Y-%m-%d"))
            dates.sort()

            fetcher = get_fetcher(ml["type"])
            all_emails = []

            for date_str in dates:
                q.put({
                    "type": "progress",
                    "message": f"正在获取 {ml['name']} 在 {date_str} 的邮件...",
                })
                try:
                    # Try cache first (skips today's date automatically)
                    cached_emails = cache.load_email_cache(list_id, date_str)
                    if cached_emails is not None:
                        emails = cached_emails
                        q.put({
                            "type": "progress",
                            "message": f"{date_str}: [缓存命中] {len(emails)} 封邮件",
                        })
                    else:
                        emails = fetcher.fetch_emails(ml["config"], date_str, cookie=cookie)
                        cache.save_email_cache(list_id, date_str, emails)
                        q.put({
                            "type": "progress",
                            "message": f"{date_str}: 获取到 {len(emails)} 封邮件",
                        })
                    all_emails.extend(emails)
                except Exception as e:
                    logger.exception("Error fetching emails for %s on %s", ml["name"], date_str)
                    q.put({
                        "type": "retry",
                        "message": f"{date_str}: 获取邮件失败 — {e}",
                    })

            # Emit emails_loaded so frontend can render them immediately
            q.put({
                "type": "emails_loaded",
                "data": {
                    "emails": all_emails,
                    "count": len(all_emails),
                },
            })

            if not all_emails:
                q.put({
                    "type": "done",
                    "data": {
                        "summary": "在所选时间范围内没有邮件。",
                        "generated_at": "",
                        "email_count": 0,
                    },
                })
                return

            # Generate digest with progress callbacks
            cache_date = dates[-1]  # use latest date for cache key
            llm_config = config.get("llm", {})
            digest_date_range = f"{dates[0]} ~ {dates[-1]}" if len(dates) > 1 else dates[0]
            digest = summarizer.generate_digest(
                all_emails, list_id, ml["name"], cache_date, llm_config,
                progress_cb=progress_cb,
                force=True,
                lang=lang,
                date_range=digest_date_range,
            )
            q.put({"type": "done", "data": digest})
        except Exception as e:
            logger.exception("SSE /api/email/digest/stream — error")
            q.put({"type": "error", "message": str(e)})

    t = threading.Thread(target=worker, daemon=True)
    t.start()

    def generate():
        while True:
            try:
                event = q.get(timeout=300)  # 5 min timeout for LLM calls
            except queue.Empty:
                yield _sse_event({"type": "error", "message": "操作超时 (5 分钟)"})
                return
            yield _sse_event(event)
            if event["type"] in ("done", "error"):
                return

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# --- Daily Summary API ---


@app.route("/api/daily-summary", methods=["GET", "POST", "DELETE"])
def api_daily_summary():
    """One-click daily summary across all mailing lists.

    Accepts a 'days' query parameter (1, 3, or 7) to control the time range.
    """
    config = load_config()
    today = datetime.now().strftime("%Y-%m-%d")

    # Parse days parameter (default 3)
    try:
        num_days = int(request.args.get("days", "3"))
    except ValueError:
        num_days = 3
    if num_days not in (1, 3, 7):
        num_days = 3

    # Cache key includes days count
    cache_key = f"{today}__{num_days}d"

    if request.method == "GET":
        logger.debug("GET /api/daily-summary days=%d", num_days)
        cached = summarizer.load_daily_summary(cache_key)
        if cached:
            return jsonify(cached)
        return jsonify({"lists": None, "total_emails": 0})

    if request.method == "DELETE":
        logger.info("DELETE /api/daily-summary — clearing cache for %s", cache_key)
        deleted = summarizer.delete_daily_summary(cache_key)
        return jsonify({"ok": True, "deleted": deleted})

    # POST — generate new daily summary
    force = request.args.get("force", "").lower() in ("1", "true", "yes")
    logger.info("POST /api/daily-summary — generating daily summary (days=%d, force=%s)", num_days, force)

    # --- Pre-checks ---
    errors = []

    # 1. Check LLM configuration
    llm_config = config.get("llm", {})
    try:
        provider = summarizer._get_active_provider(llm_config)
        if not provider.get("auth_token", ""):
            errors.append("LLM 认证令牌未配置。请在设置页面配置 LLM Provider 的 Auth Token。")
    except ValueError as e:
        errors.append(str(e))

    # 2. Check mailing lists exist
    mailing_lists = config.get("mailing_lists", [])
    if not mailing_lists:
        errors.append("未配置任何邮件组。请在设置页面添加至少一个邮件组。")

    # 3. Check private list authentication
    private_lists_without_auth = []
    for ml in mailing_lists:
        if ml.get("private", False):
            cookie = _get_cookie_for_list(config, ml)
            if not cookie:
                private_lists_without_auth.append(ml["name"])

    if private_lists_without_auth:
        errors.append(
            f"以下私有邮件组需要 ASF 认证: {', '.join(private_lists_without_auth)}。"
            f"这些邮件组将被跳过，或请先在设置页面完成 ASF 登录。"
        )

    # If critical errors (no LLM or no lists), return immediately
    if not mailing_lists or (llm_config and not llm_config.get("providers")):
        if errors:
            logger.warning("POST /api/daily-summary — pre-check failed: %s", errors)
            return jsonify({"error": " | ".join(errors)}), 400

    # --- Fetch emails for last N days ---
    dates = []
    for i in range(num_days):
        d = datetime.now() - timedelta(days=i)
        dates.append(d.strftime("%Y-%m-%d"))
    dates.sort()  # oldest first

    all_data = {}  # {list_name: {date: [emails]}}
    # Also collect email metadata per list for linking
    all_email_meta = {}  # {list_name: {date: [{id, subject, from, link}]}}
    skipped_lists = []

    for ml in mailing_lists:
        # Skip private lists without auth
        if ml.get("private", False):
            cookie = _get_cookie_for_list(config, ml)
            if not cookie:
                skipped_lists.append(ml["name"])
                continue
        else:
            cookie = _get_cookie_for_list(config, ml)

        list_name = ml["name"]
        list_data = {}
        list_meta = {}
        base_url = ml.get("config", {}).get("base_url", "https://lists.apache.org")
        try:
            fetcher = get_fetcher(ml["type"])

            # For PonyMail lists, fetch the permalink map (raw Message-ID → mid hash)
            permalink_map = {}
            if ml.get("type") == "ponymail":
                year_months = sorted(set(d[:7] for d in dates))
                for ym in year_months:
                    pm = fetcher.fetch_permalink_map(ml["config"], ym, cookie=cookie)
                    permalink_map.update(pm)

            for date in dates:
                logger.info("Fetching emails for %s on %s", list_name, date)
                # Try cache first (skips today's date automatically)
                cached_emails = cache.load_email_cache(ml["id"], date)
                if cached_emails is not None:
                    emails = cached_emails
                    logger.info("[缓存命中] %s on %s: %d emails", list_name, date, len(emails))
                else:
                    emails = fetcher.fetch_emails(ml["config"], date, cookie=cookie)
                    cache.save_email_cache(ml["id"], date, emails)
                list_data[date] = emails
                # Build email metadata with correct PonyMail permalink links
                day_meta = []
                for em in emails:
                    raw_id = em.get("id", "")
                    link = ""
                    if raw_id and ml.get("type") == "ponymail":
                        pony_mid = permalink_map.get(raw_id, "")
                        if pony_mid:
                            link = f"{base_url}/thread/{pony_mid}"
                    day_meta.append({
                        "id": raw_id,
                        "subject": em.get("subject", ""),
                        "from": em.get("from", ""),
                        "link": link,
                    })
                list_meta[date] = day_meta
                logger.info("Fetched %d emails for %s on %s", len(emails), list_name, date)
        except Exception as e:
            logger.exception("Error fetching emails for %s", list_name)
            list_data = {date: [] for date in dates}
            list_meta = {date: [] for date in dates}

        all_data[list_name] = list_data
        all_email_meta[list_name] = list_meta

    # --- Generate summary ---
    try:
        result = summarizer.generate_daily_summary(
            all_data, dates, llm_config, cache_key, force=force
        )
        # Attach email metadata to result for frontend linking
        result["email_meta"] = all_email_meta
        if skipped_lists:
            result["skipped_lists"] = skipped_lists
        if errors:
            result["warnings"] = errors
        logger.info("POST /api/daily-summary — done, total_emails=%d", result.get("total_emails", 0))
        return jsonify(result)
    except Exception as e:
        logger.exception("POST /api/daily-summary — error generating summary")
        return jsonify({"error": f"生成摘要时出错: {str(e)}"}), 500


# --- ASF Authentication API ---


@app.route("/api/asf-auth", methods=["GET", "POST"])
def api_asf_auth():
    """Manage ASF authentication for private mailing lists."""
    config = load_config()

    if request.method == "GET":
        # Return current auth status
        cookie = config.get("asf_auth", {}).get("cookie", "")
        result = asf_auth.validate_cookie(cookie) if cookie else {"ok": False, "uid": "", "fullname": "", "message": "Not authenticated"}
        # Also list which lists are private
        private_lists = [
            {"id": ml["id"], "name": ml["name"], "private": ml.get("private", False)}
            for ml in config.get("mailing_lists", [])
        ]
        return jsonify({"auth": result, "lists": private_lists})

    # POST — either login with credentials or save a manual cookie
    data = request.get_json()
    if not data:
        return jsonify({"ok": False, "message": "Request body is required"}), 400

    # Option 1: Login with username/password
    if "username" in data and "password" in data:
        username = data["username"].strip()
        password = data["password"]
        if not username or not password:
            return jsonify({"ok": False, "message": "Username and password are required."})
        logger.info("POST /api/asf-auth — attempting login for user '%s'", username)
        result = asf_auth.login(username, password)
        if result["ok"] and result.get("cookie"):
            config.setdefault("asf_auth", {})["cookie"] = result["cookie"]
            save_config(config)
            logger.info("POST /api/asf-auth — login successful, cookie saved")
        return jsonify(result)

    # Option 2: Manual cookie paste
    if "cookie" in data:
        cookie = data["cookie"].strip()
        if not cookie:
            # Clear authentication
            config.setdefault("asf_auth", {})["cookie"] = ""
            save_config(config)
            logger.info("POST /api/asf-auth — cleared ASF cookie")
            return jsonify({"ok": True, "message": "Authentication cleared."})

        result = asf_auth.validate_cookie(cookie)
        if result["ok"]:
            config.setdefault("asf_auth", {})["cookie"] = cookie
            save_config(config)
            logger.info("POST /api/asf-auth — manual cookie saved, user=%s", result.get("uid", ""))
        return jsonify(result)

    return jsonify({"ok": False, "message": "Provide 'username'+'password' or 'cookie'."}), 400


# --- Test Connection API ---

@app.route("/api/test-connection", methods=["POST"])
def api_test_connection():
    data = request.get_json()
    if not data or "type" not in data or "config" not in data:
        logger.warning("POST /api/test-connection — missing type or config")
        return jsonify({"error": "type and config are required"}), 400
    logger.info("POST /api/test-connection — type=%s", data["type"])
    try:
        config = load_config()
        cookie = config.get("asf_auth", {}).get("cookie", "")
        fetcher = get_fetcher(data["type"])
        result = fetcher.test_connection(data["config"], cookie=cookie)
        logger.info("POST /api/test-connection — result: ok=%s, message=%s", result.get("ok"), result.get("message"))
        return jsonify(result)
    except Exception as e:
        logger.exception("POST /api/test-connection — error")
        return jsonify({"ok": False, "message": str(e)})


# --- GitHub API ---

@app.route("/api/github/repos")
def api_github_repos():
    """Return configured GitHub repos."""
    config = load_config()
    repos = config.get("github", {}).get("repos", [])
    logger.debug("GET /api/github/repos — returning %d repos", len(repos))
    return jsonify(repos)


@app.route("/api/github/activity")
def api_github_activity():
    """Fetch recent PR and Issue activity for a repo."""
    repo_id = request.args.get("repo_id", "")
    try:
        days = int(request.args.get("days", "3"))
    except ValueError:
        days = 3
    if days not in (1, 3, 7):
        days = 3

    if not repo_id:
        return jsonify({"error": "repo_id is required"}), 400

    config = load_config()
    gh_config = config.get("github", {})
    repos = gh_config.get("repos", [])
    repo = None
    for r in repos:
        if r["id"] == repo_id:
            repo = r
            break
    if not repo:
        return jsonify({"error": f"Repo '{repo_id}' not found"}), 404

    logger.info("GET /api/github/activity — repo=%s/%s, days=%d", repo["owner"], repo["repo"], days)
    try:
        from sources.github import GitHubSource
        gh = GitHubSource()
        token = gh_config.get("token", "")
        activity = gh.fetch_activity(repo["owner"], repo["repo"], days=days, token=token)
        return jsonify(activity)
    except Exception as e:
        logger.exception("GET /api/github/activity — error")
        return jsonify({"error": str(e)}), 500


@app.route("/api/github/digest", methods=["GET", "POST"])
def api_github_digest():
    """Generate or retrieve a GitHub activity digest."""
    repo_id = request.args.get("repo_id", "")
    try:
        days = int(request.args.get("days", "3"))
    except ValueError:
        days = 3

    if not repo_id:
        return jsonify({"error": "repo_id is required"}), 400

    config = load_config()
    gh_config = config.get("github", {})
    repos = gh_config.get("repos", [])
    repo = None
    for r in repos:
        if r["id"] == repo_id:
            repo = r
            break
    if not repo:
        return jsonify({"error": f"Repo '{repo_id}' not found"}), 404

    today = datetime.now().strftime("%Y-%m-%d")
    cache_key = f"github__{repo_id}__{today}__{days}d"

    if request.method == "GET":
        cached = summarizer.load_digest(cache_key, "")
        if cached:
            return jsonify(cached)
        return jsonify({"summary": None})

    # POST — generate digest
    logger.info("POST /api/github/digest — repo=%s/%s, days=%d", repo["owner"], repo["repo"], days)
    try:
        from sources.github import GitHubSource
        gh = GitHubSource()
        token = gh_config.get("token", "")
        activity = gh.fetch_activity(repo["owner"], repo["repo"], days=days, token=token)

        llm_config = config.get("llm", {})
        digest = summarizer.generate_github_digest(
            activity, repo_id, f"{repo['owner']}/{repo['repo']}", days, llm_config, cache_key
        )
        return jsonify(digest)
    except Exception as e:
        logger.exception("POST /api/github/digest — error")
        return jsonify({"error": str(e)}), 500


# --- GitHub SSE streaming endpoints ---


def _sse_event(data: dict) -> str:
    """Format a dict as an SSE event line."""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.route("/api/github/activity/stream")
def api_github_activity_stream():
    """SSE endpoint: stream progress while fetching GitHub activity."""
    repo_id = request.args.get("repo_id", "")
    try:
        days = int(request.args.get("days", "3"))
    except ValueError:
        days = 3
    if days not in (1, 3, 7):
        days = 3

    if not repo_id:
        def err_gen():
            yield _sse_event({"type": "error", "message": "repo_id is required"})
        return Response(err_gen(), mimetype="text/event-stream")

    config = load_config()
    gh_config = config.get("github", {})
    repos = gh_config.get("repos", [])
    repo = None
    for r in repos:
        if r["id"] == repo_id:
            repo = r
            break
    if not repo:
        def err_gen():
            yield _sse_event({"type": "error", "message": f"Repo '{repo_id}' not found"})
        return Response(err_gen(), mimetype="text/event-stream")

    logger.info("SSE /api/github/activity/stream — repo=%s/%s, days=%d", repo["owner"], repo["repo"], days)

    q = queue.Queue()

    def progress_cb(event_type, message, **kwargs):
        event = {"type": event_type, "message": message}
        event.update(kwargs)
        q.put(event)

    def worker():
        try:
            from sources.github import GitHubSource
            gh = GitHubSource()
            token = gh_config.get("token", "")
            activity = gh.fetch_activity(
                repo["owner"], repo["repo"], days=days, token=token,
                progress_cb=progress_cb,
            )
            q.put({"type": "done", "data": activity})
        except Exception as e:
            logger.exception("SSE /api/github/activity/stream — error")
            q.put({"type": "error", "message": str(e)})

    t = threading.Thread(target=worker, daemon=True)
    t.start()

    def generate():
        while True:
            try:
                event = q.get(timeout=120)
            except queue.Empty:
                yield _sse_event({"type": "error", "message": "操作超时"})
                return
            yield _sse_event(event)
            if event["type"] in ("done", "error"):
                return

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/api/github/digest/stream")
def api_github_digest_stream():
    """SSE endpoint: stream progress while generating GitHub digest."""
    repo_id = request.args.get("repo_id", "")
    start_date = request.args.get("start_date", "")
    end_date = request.args.get("end_date", "")
    try:
        days = int(request.args.get("days", "3"))
    except ValueError:
        days = 3
    if not start_date and days not in (1, 3, 7):
        days = 3
    lang = request.args.get("lang", "zh")
    if lang not in ("zh", "en"):
        lang = "zh"

    # Compute effective days from start_date/end_date if provided
    since_date = None
    if start_date and end_date:
        try:
            sd = datetime.strptime(start_date, "%Y-%m-%d")
            ed = datetime.strptime(end_date, "%Y-%m-%d")
            days = (ed - sd).days + 1
            since_date = start_date
        except ValueError:
            pass

    if not repo_id:
        def err_gen():
            yield _sse_event({"type": "error", "message": "repo_id is required"})
        return Response(err_gen(), mimetype="text/event-stream")

    config = load_config()
    gh_config = config.get("github", {})
    repos = gh_config.get("repos", [])
    repo = None
    for r in repos:
        if r["id"] == repo_id:
            repo = r
            break
    if not repo:
        def err_gen():
            yield _sse_event({"type": "error", "message": f"Repo '{repo_id}' not found"})
        return Response(err_gen(), mimetype="text/event-stream")

    today = datetime.now().strftime("%Y-%m-%d")
    range_label = f"{start_date}__{end_date}" if start_date else f"{days}d"
    cache_key = f"github__{repo_id}__{today}__{range_label}"

    logger.info("SSE /api/github/digest/stream — repo=%s/%s, days=%d, start_date=%s, end_date=%s",
                repo["owner"], repo["repo"], days, start_date, end_date)

    q = queue.Queue()

    def progress_cb(event_type, message, **kwargs):
        event = {"type": event_type, "message": message}
        event.update(kwargs)
        q.put(event)

    def worker():
        try:
            # Compute the full list of dates for this request
            if start_date and end_date:
                sd = datetime.strptime(start_date, "%Y-%m-%d")
                ed = datetime.strptime(end_date, "%Y-%m-%d")
            else:
                ed = datetime.now()
                sd = ed - timedelta(days=days - 1)
            date_list = []
            cur = sd
            while cur <= ed:
                date_list.append(cur.strftime("%Y-%m-%d"))
                cur += timedelta(days=1)

            # Check per-day cache
            cached_data, missing_dates = cache.load_github_cache_range(repo_id, date_list)
            if cached_data and not missing_dates:
                q.put({"type": "progress", "message": f"[缓存命中] 全部 {len(cached_data)} 天数据来自缓存"})
            elif cached_data:
                q.put({"type": "progress", "message": f"[部分缓存] 命中 {len(cached_data)} 天，需获取 {len(missing_dates)} 天"})

            # Fetch missing days from GitHub API
            fetched_activity = None
            if missing_dates:
                from sources.github import GitHubSource
                gh = GitHubSource()
                token = gh_config.get("token", "")
                fetch_since = min(missing_dates)
                fetch_until = max(missing_dates)
                fetched_activity = gh.fetch_activity(
                    repo["owner"], repo["repo"], days=len(missing_dates), token=token,
                    progress_cb=progress_cb,
                    since_date=fetch_since,
                    until_date=fetch_until,
                )
                # Save fetched data per-day (skips today automatically)
                cache.save_github_cache_days(repo_id, fetched_activity)

            # Merge cached + fetched data into a single activity dict
            all_pulls = []
            all_issues = []
            for date, day_data in cached_data.items():
                all_pulls.extend(day_data.get("pulls", []))
                all_issues.extend(day_data.get("issues", []))
            if fetched_activity:
                all_pulls.extend(fetched_activity.get("pulls", []))
                all_issues.extend(fetched_activity.get("issues", []))

            # Deduplicate by number (in case of overlap between cached and fetched)
            seen_pr = set()
            deduped_pulls = []
            for pr in all_pulls:
                if pr["number"] not in seen_pr:
                    seen_pr.add(pr["number"])
                    deduped_pulls.append(pr)
            seen_issue = set()
            deduped_issues = []
            for issue in all_issues:
                if issue["number"] not in seen_issue:
                    seen_issue.add(issue["number"])
                    deduped_issues.append(issue)

            # Build merged activity with fresh stats
            activity = {
                "pulls": deduped_pulls,
                "issues": deduped_issues,
                "stats": {
                    "total_prs": len(deduped_pulls),
                    "merged_prs": sum(1 for p in deduped_pulls if p.get("merged")),
                    "open_prs": sum(1 for p in deduped_pulls if p.get("state") == "open"),
                    "closed_prs": sum(1 for p in deduped_pulls if p.get("state") == "closed" and not p.get("merged")),
                    "total_issues": len(deduped_issues),
                    "open_issues": sum(1 for i in deduped_issues if i.get("state") == "open"),
                    "closed_issues": sum(1 for i in deduped_issues if i.get("state") == "closed"),
                },
                "repo": f"{repo['owner']}/{repo['repo']}",
                "days": days,
            }

            # Emit activity data so frontend can render it immediately
            q.put({"type": "activity_loaded", "data": activity})

            # Then generate digest
            llm_config = config.get("llm", {})
            # Compute date range label for LLM prompt
            digest_date_range = f"{date_list[0]} ~ {date_list[-1]}"
            digest = summarizer.generate_github_digest(
                activity, repo_id, f"{repo['owner']}/{repo['repo']}",
                days, llm_config, cache_key,
                progress_cb=progress_cb,
                force=True,
                lang=lang,
                date_range=digest_date_range,
            )
            q.put({"type": "done", "data": digest})
        except Exception as e:
            logger.exception("SSE /api/github/digest/stream — error")
            q.put({"type": "error", "message": str(e)})

    t = threading.Thread(target=worker, daemon=True)
    t.start()

    def generate():
        while True:
            try:
                event = q.get(timeout=300)  # 5 min timeout for LLM calls
            except queue.Empty:
                yield _sse_event({"type": "error", "message": "操作超时 (5 分钟)"})
                return
            yield _sse_event(event)
            if event["type"] in ("done", "error"):
                return

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# --- Summary History API ---


@app.route("/api/summaries")
def api_summaries():
    """List saved summary Markdown files. Optional ?type=email|github filter."""
    source_type = request.args.get("type", None)
    files = summarizer.list_summary_files(source_type)
    return jsonify(files)


@app.route("/api/summaries/<path:filename>")
def api_summary_file(filename):
    """Read a specific summary Markdown file."""
    # Basic security: prevent path traversal
    if ".." in filename or "/" in filename:
        return jsonify({"error": "Invalid filename"}), 400
    content = summarizer.read_summary_file(filename)
    if content is None:
        return jsonify({"error": "File not found"}), 404
    return jsonify({"filename": filename, "content": content})


# --- Feishu Webhook Push API ---


def _markdown_to_feishu_post(md_text: str, title: str = ""):
    """Convert markdown text to Feishu rich-text (post) message format.

    Splits the markdown by lines and creates text/link elements.
    """
    lines = md_text.strip().split("\n")
    content_lines = []
    for line in lines:
        elements = []
        # Convert markdown links [text](url) → link elements
        parts = re.split(r'\[([^\]]+)\]\(([^)]+)\)', line)
        for i, part in enumerate(parts):
            if i % 3 == 0:  # plain text
                cleaned = part.strip()
                if cleaned:
                    # Clean up markdown formatting characters
                    cleaned = re.sub(r'^#{1,6}\s*', '', cleaned)  # headers
                    cleaned = re.sub(r'\*\*(.+?)\*\*', r'\1', cleaned)  # bold
                    cleaned = re.sub(r'\*(.+?)\*', r'\1', cleaned)  # italic
                    cleaned = re.sub(r'`(.+?)`', r'\1', cleaned)  # inline code
                    if cleaned:
                        elements.append({"tag": "text", "text": cleaned})
            elif i % 3 == 1:  # link text (next part is url)
                url = parts[i + 1] if i + 1 < len(parts) else ""
                elements.append({"tag": "a", "text": part, "href": url})
            # i % 3 == 2 is the url, already consumed above
        if elements:
            content_lines.append(elements)
        elif line.strip() == "":
            # Preserve blank lines as empty text
            content_lines.append([{"tag": "text", "text": ""}])

    return {
        "msg_type": "post",
        "content": {
            "post": {
                "zh_cn": {
                    "title": "",
                    "content": content_lines,
                }
            }
        },
    }


@app.route("/api/feishu/push", methods=["POST"])
def api_feishu_push():
    """Push AI summary content to a Feishu group chat via webhook."""
    config = load_config()
    webhook_url = config.get("feishu", {}).get("webhook_url", "")
    if not webhook_url:
        logger.warning("POST /api/feishu/push — no webhook URL configured")
        return jsonify({"ok": False, "message": "飞书 Webhook URL 未配置。请在设置页面填写。"}), 400

    data = request.get_json()
    if not data or not data.get("content"):
        logger.warning("POST /api/feishu/push — missing content")
        return jsonify({"ok": False, "message": "推送内容不能为空"}), 400

    content = data["content"]
    title = data.get("title", "AI 摘要推送")
    logger.info("POST /api/feishu/push — pushing to Feishu, title=%s, content_len=%d", title, len(content))

    try:
        payload = _markdown_to_feishu_post(content, title)
        resp = http_requests.post(
            webhook_url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        result = resp.json()
        if result.get("code") == 0 or result.get("StatusCode") == 0:
            logger.info("POST /api/feishu/push — success")
            return jsonify({"ok": True, "message": "推送成功！摘要已发送到飞书群。"})
        else:
            msg = result.get("msg") or result.get("StatusMessage") or str(result)
            logger.warning("POST /api/feishu/push — Feishu returned error: %s", msg)
            return jsonify({"ok": False, "message": f"飞书返回错误: {msg}"})
    except http_requests.exceptions.Timeout:
        logger.error("POST /api/feishu/push — request timeout")
        return jsonify({"ok": False, "message": "请求飞书超时，请检查网络连接"})
    except Exception as e:
        logger.exception("POST /api/feishu/push — error")
        return jsonify({"ok": False, "message": f"推送失败: {str(e)}"})


@app.route("/api/feishu/create-doc", methods=["POST"])
def api_feishu_create_doc():
    """Create a Feishu document from AI summary content using Bot A (app credentials)."""
    config = load_config()
    bot_a = config.get("feishu", {}).get("bot_a", {})
    app_id = bot_a.get("app_id", "")
    app_secret = bot_a.get("app_secret", "")
    if not app_id or not app_secret:
        logger.warning("POST /api/feishu/create-doc — Bot A credentials not configured")
        return jsonify({"ok": False, "message": "飞书机器人 A（文档机器人）未配置。请在设置页面填写 App ID 和 App Secret。"}), 400

    data = request.get_json()
    if not data or not data.get("content"):
        logger.warning("POST /api/feishu/create-doc — missing content")
        return jsonify({"ok": False, "message": "文档内容不能为空"}), 400

    content = data["content"]
    title = data.get("title", "GitHub AI 摘要")
    date_range = data.get("date_range", "")
    sub_folder = data.get("sub_folder", "")
    if date_range:
        title = f"{title}（{date_range}）"
    folder_token = bot_a.get("folder_token", "")
    owner_email = bot_a.get("owner_email", "")
    logger.info("POST /api/feishu/create-doc — title=%s, content_len=%d", title, len(content))

    try:
        from sources.feishu import FeishuDocService
        svc = FeishuDocService()
        result = svc.create_doc_from_markdown(app_id, app_secret, title, content, folder_token, owner_email, sub_folder)
        return jsonify({"ok": True, "doc_url": result["doc_url"], "document_id": result["document_id"],
                        "message": f"文档创建成功！"})
    except Exception as e:
        logger.exception("POST /api/feishu/create-doc — error")
        return jsonify({"ok": False, "message": f"创建文档失败: {str(e)}"})


@app.route("/api/feishu/push-doc-link", methods=["POST"])
def api_feishu_push_doc_link():
    """Push a document link to a Feishu group chat via Bot B webhook."""
    config = load_config()
    webhook_url = config.get("feishu", {}).get("bot_b", {}).get("webhook_url", "")
    if not webhook_url:
        logger.warning("POST /api/feishu/push-doc-link — Bot B webhook not configured")
        return jsonify({"ok": False, "message": "飞书机器人 B（通知机器人）未配置。请在设置页面填写 Webhook URL。"}), 400

    data = request.get_json()
    doc_url = data.get("doc_url", "") if data else ""
    title = data.get("title", "GitHub AI 摘要") if data else ""
    if not doc_url:
        return jsonify({"ok": False, "message": "文档链接不能为空"}), 400

    logger.info("POST /api/feishu/push-doc-link — title=%s, doc_url=%s", title, doc_url)

    try:
        from sources.feishu import FeishuDocService
        result = FeishuDocService.push_link_to_webhook(webhook_url, title, doc_url)
        if result.get("code") == 0 or result.get("StatusCode") == 0:
            return jsonify({"ok": True, "message": "文档链接已推送到飞书群！"})
        else:
            msg = result.get("msg") or result.get("StatusMessage") or str(result)
            return jsonify({"ok": False, "message": f"飞书返回错误: {msg}"})
    except Exception as e:
        logger.exception("POST /api/feishu/push-doc-link — error")
        return jsonify({"ok": False, "message": f"推送失败: {str(e)}"})


@app.route("/api/feishu/create-and-push", methods=["POST"])
def api_feishu_create_and_push():
    """Combined: create a Feishu doc (Bot A) and push its link to group (Bot B)."""
    config = load_config()
    bot_a = config.get("feishu", {}).get("bot_a", {})
    bot_b_webhook = config.get("feishu", {}).get("bot_b", {}).get("webhook_url", "")
    app_id = bot_a.get("app_id", "")
    app_secret = bot_a.get("app_secret", "")

    if not app_id or not app_secret:
        return jsonify({"ok": False, "message": "飞书机器人 A（文档机器人）未配置。请在设置页面填写 App ID 和 App Secret。"}), 400

    data = request.get_json()
    if not data or not data.get("content"):
        return jsonify({"ok": False, "message": "文档内容不能为空"}), 400

    content = data["content"]
    title = data.get("title", "GitHub AI 摘要")
    date_range = data.get("date_range", "")
    sub_folder = data.get("sub_folder", "")
    if date_range:
        title = f"{title}（{date_range}）"
    folder_token = bot_a.get("folder_token", "")
    owner_email = bot_a.get("owner_email", "")
    logger.info("POST /api/feishu/create-and-push — title=%s, content_len=%d", title, len(content))

    try:
        from sources.feishu import FeishuDocService
        svc = FeishuDocService()

        # Step 1: Create document via Bot A
        doc_result = svc.create_doc_from_markdown(app_id, app_secret, title, content, folder_token, owner_email, sub_folder)
        doc_url = doc_result["doc_url"]
        logger.info("POST /api/feishu/create-and-push — doc created: %s", doc_url)

        # Step 2: Push link via Bot B (if configured)
        push_msg = ""
        if bot_b_webhook:
            try:
                push_result = FeishuDocService.push_link_to_webhook(bot_b_webhook, title, doc_url)
                if push_result.get("code") == 0 or push_result.get("StatusCode") == 0:
                    push_msg = "，链接已推送到飞书群"
                else:
                    push_msg = "，但推送链接到飞书群失败"
            except Exception as push_err:
                logger.warning("POST /api/feishu/create-and-push — push failed: %s", push_err)
                push_msg = "，但推送链接到飞书群失败"
        else:
            push_msg = "（机器人 B 未配置，链接未推送到群）"

        return jsonify({
            "ok": True,
            "doc_url": doc_url,
            "document_id": doc_result["document_id"],
            "message": f"文档创建成功{push_msg}！",
        })
    except Exception as e:
        logger.exception("POST /api/feishu/create-and-push — error")
        return jsonify({"ok": False, "message": f"创建文档失败: {str(e)}"})


@app.route("/api/feishu/create-batch-docs", methods=["POST"])
def api_feishu_create_batch_docs():
    """Create a single merged summary doc in a date-range subfolder."""
    import os

    config = load_config()
    bot_a = config.get("feishu", {}).get("bot_a", {})
    app_id = bot_a.get("app_id", "")
    app_secret = bot_a.get("app_secret", "")
    folder_token = bot_a.get("folder_token", "")
    owner_email = bot_a.get("owner_email", "")

    if not app_id or not app_secret:
        return jsonify({"ok": False, "message": "飞书机器人 A 未配置"}), 400
    if not folder_token:
        return jsonify({"ok": False, "message": "Folder Token 未配置"}), 400

    data = request.get_json()
    content = data.get("content", "")
    date_range = data.get("date_range", "") or "未知时间范围"

    if not content:
        return jsonify({"ok": False, "message": "没有文档内容"}), 400

    doc_title = f"Github 摘要（{date_range}）"
    logger.info("POST /api/feishu/create-batch-docs — title=%s", doc_title)

    try:
        # Save locally
        local_dir = os.path.join(os.path.dirname(__file__), "summaries")
        os.makedirs(local_dir, exist_ok=True)
        safe_name = date_range.replace("/", "-").replace("\\", "-")
        local_file = os.path.join(local_dir, f"Github 摘要（{safe_name}）.md")
        with open(local_file, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info("Saved local summary: %s", local_file)

        from sources.feishu import FeishuDocService
        svc = FeishuDocService()
        token = svc._get_tenant_access_token(app_id, app_secret)

        # Create date-range subfolder
        date_folder_token = svc.ensure_folder_path(token, folder_token, [date_range])

        # Delete existing doc with same title
        svc.delete_existing_doc(token, date_folder_token, doc_title)

        # Create merged document
        result = svc.create_doc_from_markdown(
            app_id, app_secret, doc_title,
            content, date_folder_token, owner_email,
        )
        doc_url = result["doc_url"]

        # Get folder URL
        folder_url = ""
        try:
            resp = requests.post(
                f"https://open.feishu.cn/open-apis/drive/v1/metas/batch_query",
                json={"request_docs": [{"doc_token": date_folder_token, "doc_type": "folder"}],
                      "with_url": True},
                headers=svc._auth_headers(token), timeout=15)
            metas = resp.json().get("data", {}).get("metas", [])
            if metas:
                folder_url = metas[0].get("url", "")
        except Exception:
            pass
        if not folder_url and date_folder_token:
            folder_url = f"https://bcntnaqps5sg.feishu.cn/drive/folder/{date_folder_token}"

        # Set folder public readable
        try:
            svc._set_public_readable(token, date_folder_token)
        except Exception:
            pass

        return jsonify({
            "ok": True,
            "message": "文档推送成功",
            "folder_url": folder_url,
            "doc_url": doc_url,
            "doc_title": doc_title,
        })
    except Exception as e:
        logger.exception("POST /api/feishu/create-batch-docs — error")
        return jsonify({"ok": False, "message": f"推送失败: {str(e)}"})


# --- Slack Push API ---


def _markdown_to_slack_blocks(md_text: str, title: str = "") -> list[dict]:
    """Convert Markdown text to Slack Block Kit blocks.

    Uses Header block for the title, Section blocks (mrkdwn) for content,
    and Divider blocks for visual separation.
    Each section block has a 3000 char limit, so we split as needed.
    """
    blocks = []

    # Header block
    if title:
        blocks.append({
            "type": "header",
            "text": {"type": "plain_text", "text": title[:150], "emoji": True},
        })
        blocks.append({"type": "divider"})

    # Convert Markdown formatting to Slack mrkdwn
    text = md_text.strip()

    # Convert markdown links [text](url) → <url|text>
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<\2|\1>', text)
    # Convert headings to bold (Slack doesn't support headings)
    text = re.sub(r'^#{1,6}\s+(.+)$', r'\n*\1*', text, flags=re.MULTILINE)
    # Convert bold **text** → *text*
    text = re.sub(r'\*\*(.+?)\*\*', r'*\1*', text)
    # Convert strikethrough ~~text~~ → ~text~
    text = re.sub(r'~~(.+?)~~', r'~\1~', text)
    # Convert horizontal rules
    text = re.sub(r'^---+$', '───────────────────', text, flags=re.MULTILINE)

    # Split into chunks of ~2900 chars (Slack limit is 3000 per section block)
    max_chunk = 2900
    lines = text.split('\n')
    current_chunk = ""

    for line in lines:
        # If adding this line would exceed the limit, flush current chunk
        if len(current_chunk) + len(line) + 1 > max_chunk and current_chunk:
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": current_chunk.strip()},
            })
            current_chunk = ""

        current_chunk += line + "\n"

    # Flush remaining
    if current_chunk.strip():
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": current_chunk.strip()},
        })

    return blocks


@app.route("/api/slack/push", methods=["POST"])
def api_slack_push():
    """Push AI summary content to a Slack channel via Incoming Webhook."""
    config = load_config()
    webhook_url = config.get("slack", {}).get("push_webhook_url", "")
    if not webhook_url:
        logger.warning("POST /api/slack/push — no webhook URL configured")
        return jsonify({"ok": False, "message": "Slack Webhook URL 未配置。请在设置页面填写。"}), 400

    data = request.get_json()
    if not data or not data.get("content"):
        logger.warning("POST /api/slack/push — missing content")
        return jsonify({"ok": False, "message": "推送内容不能为空"}), 400

    content = data["content"]
    title = data.get("title", "📊 AI 摘要推送")
    logger.info("POST /api/slack/push — pushing to Slack, title=%s, content_len=%d",
                title, len(content))

    try:
        blocks = _markdown_to_slack_blocks(content, title)

        # Append Doris community survey footer
        if "doris" in title.lower():
            blocks.append({"type": "divider"})
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        "We'd love to hear from you! Please help us improve and grow "
                        "the Apache Doris community by filling out this short survey 🙌\n"
                        "<https://docs.google.com/forms/d/e/"
                        "1FAIpQLSeSppR5JJyXIxNoPlG_hS8RTW8k2tsCkpC0h68WSN6CEUsWcA/viewform"
                        "|📝 Take the Survey>"
                    ),
                },
            })

        payload = {"blocks": blocks}
        resp = http_requests.post(
            webhook_url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        # Slack webhook returns "ok" as plain text on success
        if resp.status_code == 200 and resp.text == "ok":
            logger.info("POST /api/slack/push — success")
            return jsonify({"ok": True, "message": "推送成功！摘要已发送到 Slack 频道。"})
        else:
            msg = resp.text or f"HTTP {resp.status_code}"
            logger.warning("POST /api/slack/push — Slack returned error: %s", msg)
            return jsonify({"ok": False, "message": f"Slack 返回错误: {msg}"})
    except http_requests.exceptions.Timeout:
        logger.error("POST /api/slack/push — request timeout")
        return jsonify({"ok": False, "message": "请求 Slack 超时，请检查网络连接"})
    except Exception as e:
        logger.exception("POST /api/slack/push — error")
        return jsonify({"ok": False, "message": f"推送失败: {str(e)}"})


# --- Slack API ---

@app.route("/api/slack/status")
def api_slack_status():
    """Return Slack workspace connection status."""
    config = load_config()
    workspaces = config.get("slack", {}).get("workspaces", [])
    result = []
    for ws in workspaces:
        result.append({
            "id": ws["id"],
            "name": ws.get("name", ws["id"]),
            "connected": bool(ws.get("token", "")),
            "channels_count": len(ws.get("channels", [])),
        })
    return jsonify({"workspaces": result})


@app.route("/api/slack/channels")
def api_slack_channels():
    """Return configured workspaces and their channels."""
    config = load_config()
    workspaces = config.get("slack", {}).get("workspaces", [])
    result = []
    for ws in workspaces:
        result.append({
            "id": ws["id"],
            "name": ws.get("name", ws["id"]),
            "connected": bool(ws.get("token", "")),
            "channels": ws.get("channels", []),
        })
    return jsonify(result)


@app.route("/api/slack/channels/fetch")
def api_slack_channels_fetch():
    """Fetch available channels from Slack API for a workspace."""
    workspace_id = request.args.get("workspace_id", "")
    if not workspace_id:
        return jsonify({"error": "workspace_id is required"}), 400

    config = load_config()
    workspaces = config.get("slack", {}).get("workspaces", [])
    ws = None
    for w in workspaces:
        if w["id"] == workspace_id:
            ws = w
            break
    if not ws:
        return jsonify({"error": f"Workspace '{workspace_id}' not found"}), 404

    token = ws.get("token", "")
    if not token:
        return jsonify({"error": "Slack token not configured for this workspace"}), 400

    try:
        from sources.slack import SlackSource
        slack = SlackSource()
        channels = slack.fetch_channels(token)
        return jsonify(channels)
    except Exception as e:
        logger.exception("GET /api/slack/channels/fetch — error")
        return jsonify({"error": str(e)}), 500


@app.route("/api/slack/digest/stream")
def api_slack_digest_stream():
    """SSE endpoint: stream progress while fetching Slack messages and generating digest."""
    workspace_id = request.args.get("workspace_id", "")
    channel_id = request.args.get("channel_id", "")
    start_date = request.args.get("start_date", "")
    end_date = request.args.get("end_date", "")
    try:
        days = int(request.args.get("days", "3"))
    except ValueError:
        days = 3
    if not start_date and days not in (1, 3, 7):
        days = 3
    lang = request.args.get("lang", "zh")
    if lang not in ("zh", "en"):
        lang = "zh"

    if not workspace_id or not channel_id:
        def err_gen():
            yield _sse_event({"type": "error", "message": "workspace_id and channel_id are required"})
        return Response(err_gen(), mimetype="text/event-stream")

    config = load_config()
    workspaces = config.get("slack", {}).get("workspaces", [])
    ws = None
    for w in workspaces:
        if w["id"] == workspace_id:
            ws = w
            break
    if not ws:
        def err_gen():
            yield _sse_event({"type": "error", "message": f"Workspace '{workspace_id}' not found"})
        return Response(err_gen(), mimetype="text/event-stream")

    token = ws.get("token", "")
    if not token:
        def err_gen():
            yield _sse_event({"type": "error", "message": "Slack token not configured"})
        return Response(err_gen(), mimetype="text/event-stream")

    # Find channel name
    channel_name = channel_id
    for ch in ws.get("channels", []):
        if ch["id"] == channel_id:
            channel_name = ch.get("name", channel_id)
            break

    # Compute effective dates
    since_date = None
    if start_date and end_date:
        try:
            sd = datetime.strptime(start_date, "%Y-%m-%d")
            ed = datetime.strptime(end_date, "%Y-%m-%d")
            days = (ed - sd).days + 1
            since_date = start_date
        except ValueError:
            pass

    channel_key = f"{workspace_id}__{channel_id}"
    today = datetime.now().strftime("%Y-%m-%d")
    range_label = f"{start_date}__{end_date}" if start_date else f"{days}d"
    cache_key = f"slack__{channel_key}__{today}__{range_label}"

    logger.info("SSE /api/slack/digest/stream — ws=%s, channel=%s (%s), days=%d",
                workspace_id, channel_id, channel_name, days)

    q = queue.Queue()

    def progress_cb(event_type, message, **kwargs):
        event = {"type": event_type, "message": message}
        event.update(kwargs)
        q.put(event)

    def worker():
        try:
            # Compute the full list of dates
            if start_date and end_date:
                sd = datetime.strptime(start_date, "%Y-%m-%d")
                ed = datetime.strptime(end_date, "%Y-%m-%d")
            else:
                ed = datetime.now()
                sd = ed - timedelta(days=days - 1)
            date_list = []
            cur = sd
            while cur <= ed:
                date_list.append(cur.strftime("%Y-%m-%d"))
                cur += timedelta(days=1)

            # Check per-day cache
            cached_data, missing_dates = cache.load_slack_cache_range(channel_key, date_list)
            if cached_data and not missing_dates:
                q.put({"type": "progress", "message": f"[缓存命中] 全部 {len(cached_data)} 天数据来自缓存"})
            elif cached_data:
                q.put({"type": "progress", "message": f"[部分缓存] 命中 {len(cached_data)} 天，需获取 {len(missing_dates)} 天"})

            # Fetch missing days from Slack API
            fetched_messages = []
            if missing_dates:
                from sources.slack import SlackSource
                slack = SlackSource()
                fetch_since = min(missing_dates)
                fetch_until = max(missing_dates)
                fetched_messages = slack.fetch_messages(
                    token, channel_id, days=len(missing_dates),
                    progress_cb=progress_cb,
                    since_date=fetch_since,
                    until_date=fetch_until,
                )
                # Save fetched data per-day
                cache.save_slack_cache_days(channel_key, fetched_messages)

            # Merge cached + fetched
            all_messages = []
            for date, day_msgs in cached_data.items():
                all_messages.extend(day_msgs)
            all_messages.extend(fetched_messages)

            # Deduplicate by ts
            seen_ts = set()
            deduped = []
            for msg in all_messages:
                if msg["ts"] not in seen_ts:
                    seen_ts.add(msg["ts"])
                    deduped.append(msg)
            deduped.sort(key=lambda m: m["ts"])

            # Build stats
            stats = {
                "total_messages": len(deduped),
                "threaded_messages": sum(1 for m in deduped if m.get("thread_reply_count", 0) > 0),
            }

            # Emit messages data
            q.put({"type": "messages_loaded", "data": {
                "messages": deduped,
                "stats": stats,
                "channel": channel_name,
                "days": days,
            }})

            # Generate digest
            llm_config = config.get("llm", {})
            digest_date_range = f"{date_list[0]} ~ {date_list[-1]}"
            digest = summarizer.generate_slack_digest(
                deduped, channel_key, channel_name,
                days, llm_config, cache_key,
                progress_cb=progress_cb,
                force=True,
                lang=lang,
                date_range=digest_date_range,
            )
            q.put({"type": "done", "data": digest})
        except Exception as e:
            logger.exception("SSE /api/slack/digest/stream — error")
            q.put({"type": "error", "message": str(e)})

    t = threading.Thread(target=worker, daemon=True)
    t.start()

    def generate():
        while True:
            try:
                event = q.get(timeout=300)  # 5 min timeout
            except queue.Empty:
                yield _sse_event({"type": "error", "message": "操作超时 (5 分钟)"})
                return
            yield _sse_event(event)
            if event["type"] in ("done", "error"):
                return

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})



# --- Helpers ---

def _find_list(config: dict, list_id: str) -> dict | None:
    for ml in config.get("mailing_lists", []):
        if ml["id"] == list_id:
            return ml
    return None


def _get_cookie_for_list(config: dict, ml: dict) -> str:
    """Get the auth cookie for a mailing list if needed."""
    if ml.get("type") == "ponymail":
        return config.get("asf_auth", {}).get("cookie", "")
    return ""


def auto_login_asf():
    """Auto-login to ASF if credentials are configured but cookie is missing or invalid.

    This is called at startup so users don't need to manually log in through
    the Settings page each time the app starts.
    """
    config = load_config()
    asf_cfg = config.get("asf_auth", {})
    username = asf_cfg.get("username", "")
    password = asf_cfg.get("password", "")

    if not username or not password:
        logger.debug("[Auto-Login] No ASF credentials configured, skipping auto-login")
        return

    # Check if existing cookie is still valid
    cookie = asf_cfg.get("cookie", "")
    if cookie:
        result = asf_auth.validate_cookie(cookie)
        if result["ok"]:
            logger.info(
                "[Auto-Login] Existing ASF cookie is valid: %s (%s)",
                result.get("fullname", ""), result.get("uid", ""),
            )
            return
        logger.info("[Auto-Login] Existing ASF cookie is invalid/expired, re-logging in")

    # Attempt login
    logger.info("[Auto-Login] Attempting ASF login for user '%s'", username)
    result = asf_auth.login(username, password)
    if result["ok"] and result.get("cookie"):
        config.setdefault("asf_auth", {})["cookie"] = result["cookie"]
        save_config(config)
        logger.info(
            "[Auto-Login] ASF login successful: %s (%s) — cookie saved",
            result.get("fullname", ""), result.get("uid", ""),
        )
    else:
        logger.warning(
            "[Auto-Login] ASF login failed: %s", result.get("message", "Unknown error")
        )


if __name__ == "__main__":
    setup_logging()
    auto_login_asf()
    logger.info("Starting What's Going On in development mode on port 5000")
    app.run(debug=True, port=5000)
