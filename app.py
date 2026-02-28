"""Email Watcher - Flask application for mailing list monitoring and daily digests."""

import copy
import json
import logging
import logging.handlers
import os
import sys
from datetime import datetime, timedelta

from flask import Flask, jsonify, render_template, request

from fetchers import get_fetcher
import asf_auth
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
    """Mask auth tokens and cookies in config for safe API response."""
    safe = copy.deepcopy(config)
    for p in safe.get("llm", {}).get("providers", []):
        token = p.get("auth_token", "")
        if token and len(token) > 12:
            p["auth_token"] = token[:8] + "..." + token[-4:]
        elif token:
            p["auth_token"] = "***"
    # Mask centralized ASF auth cookie
    cookie = safe.get("asf_auth", {}).get("cookie", "")
    if cookie and len(cookie) > 12:
        safe["asf_auth"]["cookie"] = cookie[:8] + "..." + cookie[-4:]
    elif cookie:
        safe["asf_auth"]["cookie"] = "***"
    return safe


def _restore_masked_tokens(new_config: dict) -> dict:
    """Restore masked auth tokens and cookies from existing saved config."""
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
    cookie = new_config.get("asf_auth", {}).get("cookie", "")
    if cookie and ("..." in cookie or cookie == "***"):
        new_config["asf_auth"]["cookie"] = old_config.get("asf_auth", {}).get("cookie", "")
    return new_config


def save_config(config: dict):
    """Save config to config.json."""
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    logger.info("Config saved to %s", CONFIG_PATH)


# --- Page routes ---

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/settings")
def settings():
    return render_template("settings.html")


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


# --- Daily Summary API ---


@app.route("/api/daily-summary", methods=["GET", "POST"])
def api_daily_summary():
    """One-click daily summary across all mailing lists for the last 3 days."""
    config = load_config()
    today = datetime.now().strftime("%Y-%m-%d")

    if request.method == "GET":
        logger.debug("GET /api/daily-summary")
        cached = summarizer.load_daily_summary(today)
        if cached:
            return jsonify(cached)
        return jsonify({"summary": None, "total_emails": 0})

    # POST — generate new daily summary
    logger.info("POST /api/daily-summary — generating daily summary")

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

    # --- Fetch emails for last 3 days ---
    dates = []
    for i in range(3):
        d = datetime.now() - timedelta(days=i)
        dates.append(d.strftime("%Y-%m-%d"))
    dates.sort()  # oldest first

    all_data = {}  # {list_name: {date: [emails]}}
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
        try:
            fetcher = get_fetcher(ml["type"])
            for date in dates:
                logger.info("Fetching emails for %s on %s", list_name, date)
                emails = fetcher.fetch_emails(ml["config"], date, cookie=cookie)
                list_data[date] = emails
                logger.info("Fetched %d emails for %s on %s", len(emails), list_name, date)
        except Exception as e:
            logger.exception("Error fetching emails for %s", list_name)
            list_data = {date: [] for date in dates}

        all_data[list_name] = list_data

    # --- Generate summary ---
    try:
        result = summarizer.generate_daily_summary(all_data, dates, llm_config, today)
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


if __name__ == "__main__":
    setup_logging()
    logger.info("Starting Email Watcher in development mode on port 5000")
    app.run(debug=True, port=5000)
