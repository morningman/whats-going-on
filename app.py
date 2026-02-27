"""Email Watcher - Flask application for mailing list monitoring and daily digests."""

import json
import os

from flask import Flask, jsonify, render_template, request

from fetchers import get_fetcher
import summarizer

app = Flask(__name__)

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")
CONFIG_EXAMPLE_PATH = os.path.join(os.path.dirname(__file__), "config.example.json")


def load_config() -> dict:
    """Load config from config.json, falling back to example."""
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)
    if os.path.exists(CONFIG_EXAMPLE_PATH):
        with open(CONFIG_EXAMPLE_PATH, "r") as f:
            return json.load(f)
    return {"mailing_lists": [], "llm": {"provider": "claude", "api_key": "", "model": "claude-sonnet-4-20250514"}, "fetch_days": 7}


def save_config(config: dict):
    """Save config to config.json."""
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


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
        config = load_config()
        # Mask API key for security
        safe = dict(config)
        if safe.get("llm", {}).get("api_key"):
            safe["llm"] = dict(safe["llm"])
            key = safe["llm"]["api_key"]
            safe["llm"]["api_key"] = key[:8] + "..." + key[-4:] if len(key) > 12 else "***"
        return jsonify(safe)
    else:
        config = request.get_json()
        if not config:
            return jsonify({"error": "Invalid JSON"}), 400
        save_config(config)
        return jsonify({"ok": True})


# --- Lists API ---

@app.route("/api/lists")
def api_lists():
    config = load_config()
    lists = [{"id": ml["id"], "name": ml["name"], "type": ml["type"]} for ml in config.get("mailing_lists", [])]
    return jsonify(lists)


# --- Emails API ---

@app.route("/api/emails")
def api_emails():
    list_id = request.args.get("list_id", "")
    date = request.args.get("date", "")
    if not list_id or not date:
        return jsonify({"error": "list_id and date are required"}), 400

    config = load_config()
    ml = _find_list(config, list_id)
    if not ml:
        return jsonify({"error": f"List '{list_id}' not found"}), 404

    try:
        fetcher = get_fetcher(ml["type"])
        emails = fetcher.fetch_emails(ml["config"], date)
        return jsonify({"emails": emails, "count": len(emails)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# --- Digest API ---

@app.route("/api/digest", methods=["GET", "POST"])
def api_digest():
    list_id = request.args.get("list_id", "")
    date = request.args.get("date", "")
    if not list_id or not date:
        return jsonify({"error": "list_id and date are required"}), 400

    config = load_config()
    ml = _find_list(config, list_id)
    if not ml:
        return jsonify({"error": f"List '{list_id}' not found"}), 404

    if request.method == "GET":
        digest = summarizer.load_digest(list_id, date)
        if digest:
            return jsonify(digest)
        return jsonify({"summary": None, "email_count": 0})

    # POST - generate new digest
    try:
        fetcher = get_fetcher(ml["type"])
        emails = fetcher.fetch_emails(ml["config"], date)
        llm_config = config.get("llm", {})
        digest = summarizer.generate_digest(
            emails, list_id, ml["name"], date, llm_config
        )
        return jsonify(digest)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# --- Test Connection API ---

@app.route("/api/test-connection", methods=["POST"])
def api_test_connection():
    data = request.get_json()
    if not data or "type" not in data or "config" not in data:
        return jsonify({"error": "type and config are required"}), 400
    try:
        fetcher = get_fetcher(data["type"])
        result = fetcher.test_connection(data["config"])
        return jsonify(result)
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)})


# --- Helpers ---

def _find_list(config: dict, list_id: str) -> dict | None:
    for ml in config.get("mailing_lists", []):
        if ml["id"] == list_id:
            return ml
    return None


if __name__ == "__main__":
    app.run(debug=True, port=5000)
