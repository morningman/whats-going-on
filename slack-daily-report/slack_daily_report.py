#!/usr/bin/env python3
"""Slack Daily Report — fetch all-channel messages and archive to GitHub.

Usage:
    python3 slack_daily_report.py                          # 抓取昨天的数据并推送
    python3 slack_daily_report.py --date 2026-03-26        # 指定日期
    python3 slack_daily_report.py --dry-run                # 只抓取保存，不推送 GitHub
    python3 slack_daily_report.py --config /path/to/cfg    # 指定配置文件

Crontab example:
    # 每天早上 8:00 运行
    0 8 * * * cd /path/to/slack-daily-report && python3 slack_daily_report.py >> /var/log/slack-daily-report.log 2>&1
"""

import argparse
import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timedelta

from slack_client import SlackClient

logger = logging.getLogger("slack_daily_report")


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_config(path: str) -> dict:
    """Load configuration from JSON file."""
    if not os.path.exists(path):
        logger.error("Config file not found: %s", path)
        logger.error("Copy config.example.json to config.json and fill in your values.")
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------

def render_message_markdown(msg: dict) -> str:
    """Render a single message as Markdown."""
    dt = msg.get("datetime", "")
    try:
        # Format datetime for readability
        dt_obj = datetime.fromisoformat(dt)
        time_str = dt_obj.strftime("%H:%M:%S UTC")
    except (ValueError, TypeError):
        time_str = dt

    user = msg.get("user", "unknown")
    text = msg.get("text", "").strip()

    lines = []
    lines.append(f"### 💬 {user}  `{time_str}`")
    lines.append("")
    if text:
        lines.append(text)
    else:
        lines.append("*(empty message)*")
    lines.append("")

    # Reactions
    reactions = msg.get("reactions", [])
    if reactions:
        lines.append(f"**Reactions:** {', '.join(reactions)}")
        lines.append("")

    # Thread replies
    replies = msg.get("replies", [])
    if replies:
        lines.append(f"**Thread** ({len(replies)} replies):")
        lines.append("")
        for reply in replies:
            r_user = reply.get("user", "unknown")
            r_text = reply.get("text", "").strip()
            r_dt = reply.get("datetime", "")
            try:
                r_dt_obj = datetime.fromisoformat(r_dt)
                r_time = r_dt_obj.strftime("%H:%M:%S UTC")
            except (ValueError, TypeError):
                r_time = r_dt
            lines.append(f"> **{r_user}** `{r_time}`")
            lines.append(f">")
            # Indent reply text within blockquote
            if r_text:
                for line in r_text.split("\n"):
                    lines.append(f"> {line}")
            else:
                lines.append("> *(empty)*")
            lines.append(">")
            lines.append("")

    lines.append("---")
    lines.append("")
    return "\n".join(lines)


def render_channel_markdown(channel_name: str, messages: list[dict], date: str) -> str:
    """Render all messages for a channel as a complete Markdown document."""
    lines = []
    lines.append(f"# #{channel_name}")
    lines.append("")
    lines.append(f"**Date:** {date}")
    lines.append(f"**Total messages:** {len(messages)}")
    thread_count = sum(1 for m in messages if m.get("thread_reply_count", 0) > 0)
    if thread_count:
        lines.append(f"**Threads:** {thread_count}")
    lines.append("")
    lines.append("---")
    lines.append("")

    for msg in messages:
        lines.append(render_message_markdown(msg))

    return "\n".join(lines)


def render_daily_index(date: str, workspace_name: str,
                       channel_stats: list[dict]) -> str:
    """Render the daily README.md index file."""
    total_msgs = sum(ch["message_count"] for ch in channel_stats)
    total_threads = sum(ch["thread_count"] for ch in channel_stats)

    lines = []
    lines.append(f"# {workspace_name} — Slack Daily Report")
    lines.append("")
    lines.append(f"**Date:** {date}")
    lines.append(f"**Active channels:** {len(channel_stats)}")
    lines.append(f"**Total messages:** {total_msgs}")
    lines.append(f"**Total threads:** {total_threads}")
    lines.append(f"**Generated at:** {datetime.now().isoformat()}")
    lines.append("")
    lines.append("## Channels")
    lines.append("")
    lines.append("| Channel | Messages | Threads |")
    lines.append("|---------|----------|---------|")
    for ch in sorted(channel_stats, key=lambda c: c["message_count"], reverse=True):
        name = ch["name"]
        lines.append(f"| [#{name}](./{name}/messages.md) | {ch['message_count']} | {ch['thread_count']} |")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Git operations
# ---------------------------------------------------------------------------

def git_push(local_dir: str, add_path: str, date: str, branch: str):
    """Add, commit, and push the daily report directory."""
    def run_git(*args):
        cmd = ["git", "-C", local_dir] + list(args)
        logger.info("Running: %s", " ".join(cmd))
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            logger.error("git command failed: %s\n%s", " ".join(cmd), result.stderr)
            raise RuntimeError(f"git {args[0]} failed: {result.stderr.strip()}")
        return result.stdout.strip()

    # Ensure we are on the right branch
    run_git("checkout", branch)
    run_git("pull", "--rebase", "origin", branch)

    # Add the date directory
    run_git("add", add_path)

    # Check if there are changes to commit
    status = run_git("status", "--porcelain")
    if not status:
        logger.info("No changes to commit for %s", date)
        return

    run_git("commit", "-m", f"Add Slack daily report for {date}")
    run_git("push", "origin", branch)
    logger.info("Successfully pushed daily report for %s", date)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Fetch Slack messages for all channels and archive to GitHub."
    )
    parser.add_argument(
        "--date", type=str, default=None,
        help="Date to fetch (YYYY-MM-DD). Defaults to yesterday.",
    )
    parser.add_argument(
        "--config", type=str, default=None,
        help="Path to config.json. Defaults to config.json in script directory.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Only fetch and save, do not push to GitHub.",
    )
    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Determine config path
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = args.config or os.path.join(script_dir, "config.json")
    config = load_config(config_path)

    # Parse date
    if args.date:
        target_date = args.date
    else:
        yesterday = datetime.now() - timedelta(days=1)
        target_date = yesterday.strftime("%Y-%m-%d")

    logger.info("=" * 60)
    logger.info("Slack Daily Report — %s", target_date)
    logger.info("=" * 60)

    # Read config
    slack_config = config.get("slack", {})
    token = slack_config.get("token", "")
    workspace_name = slack_config.get("workspace_name", "Workspace")

    if not token:
        logger.error("Slack token not configured in config.json")
        sys.exit(1)

    github_config = config.get("github", {})
    local_dir = github_config.get("local_dir", "")
    repo_url = github_config.get("repo_url", "")
    branch = github_config.get("branch", "main")
    sub_dir = github_config.get("sub_dir", "")

    if not local_dir:
        logger.error("github.local_dir not configured in config.json")
        sys.exit(1)

    # Ensure local repo exists
    if not os.path.isdir(local_dir):
        if repo_url:
            logger.info("Cloning repo %s to %s...", repo_url, local_dir)
            subprocess.run(
                ["git", "clone", "-b", branch, repo_url, local_dir],
                check=True, timeout=120,
            )
        else:
            logger.error("Local dir %s does not exist and no repo_url configured", local_dir)
            sys.exit(1)

    # Initialize Slack client
    client = SlackClient(token)

    # Step 1: Fetch all channels
    logger.info("Step 1: Fetching all channels...")
    channels = client.fetch_channels()
    logger.info("Found %d channels", len(channels))

    # Step 2: Fetch messages for each channel
    logger.info("Step 2: Fetching messages for date %s...", target_date)
    channel_data: dict[str, list[dict]] = {}
    total_messages = 0

    for i, ch in enumerate(channels, 1):
        ch_id = ch["id"]
        ch_name = ch.get("name", ch_id)
        logger.info("  [%d/%d] Fetching #%s...", i, len(channels), ch_name)

        try:
            messages = client.fetch_messages(ch_id, since_date=target_date, until_date=target_date)
            if messages:
                channel_data[ch_name] = messages
                total_messages += len(messages)
                logger.info("  [%d/%d] #%s: %d messages", i, len(channels), ch_name, len(messages))
            else:
                logger.info("  [%d/%d] #%s: no messages", i, len(channels), ch_name)
        except Exception as e:
            logger.warning("  [%d/%d] #%s: failed — %s", i, len(channels), ch_name, e)

    logger.info("Fetched %d messages from %d active channels", total_messages, len(channel_data))

    if not channel_data:
        logger.info("No messages found for %s. Nothing to save.", target_date)
        return

    # Step 3: Write Markdown files
    logger.info("Step 3: Writing Markdown files...")
    base_dir = os.path.join(local_dir, sub_dir) if sub_dir else local_dir
    date_dir = os.path.join(base_dir, target_date)
    os.makedirs(date_dir, exist_ok=True)

    channel_stats = []
    for ch_name, messages in sorted(channel_data.items()):
        # Create channel directory
        ch_dir = os.path.join(date_dir, ch_name)
        os.makedirs(ch_dir, exist_ok=True)

        # Write messages.md
        md_content = render_channel_markdown(ch_name, messages, target_date)
        md_path = os.path.join(ch_dir, "messages.md")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md_content)
        logger.info("  Written %s (%d messages)", md_path, len(messages))

        channel_stats.append({
            "name": ch_name,
            "message_count": len(messages),
            "thread_count": sum(1 for m in messages if m.get("thread_reply_count", 0) > 0),
        })

    # Write daily index README.md
    index_content = render_daily_index(target_date, workspace_name, channel_stats)
    index_path = os.path.join(date_dir, "README.md")
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(index_content)
    logger.info("  Written %s", index_path)

    logger.info("All files written to %s", date_dir)

    # Step 4: Git push
    if args.dry_run:
        logger.info("Dry run mode — skipping git push.")
    else:
        logger.info("Step 4: Pushing to GitHub...")
        add_path = os.path.join(sub_dir, target_date) if sub_dir else target_date
        try:
            git_push(local_dir, add_path, target_date, branch)
        except Exception as e:
            logger.error("Git push failed: %s", e)
            sys.exit(1)

    logger.info("=" * 60)
    logger.info("Done! Report for %s: %d channels, %d messages",
                target_date, len(channel_data), total_messages)
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
