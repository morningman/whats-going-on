"""AI summarizer module - generates digests using LLM APIs.

Supports email digests, GitHub activity summaries, and multi-source summaries.
Supports multiple LLM providers: Anthropic (Claude), OpenAI (GPT), Google (Gemini).
Each provider supports custom base_url and auth_token configuration.
"""

import json
import logging
import os
import time
from datetime import datetime

logger = logging.getLogger("summarizer")

DATA_DIR = os.path.join(os.path.dirname(__file__), "data", "digests")
SUMMARY_DIR = os.path.join(os.path.dirname(__file__), "data", "summaries")


def _digest_path(list_id: str, date: str) -> str:
    os.makedirs(DATA_DIR, exist_ok=True)
    return os.path.join(DATA_DIR, f"{list_id}_{date}.json")


def load_digest(list_id: str, date: str) -> dict | None:
    """Load cached digest if it exists."""
    path = _digest_path(list_id, date)
    if os.path.exists(path):
        logger.debug("Loading cached digest: %s", path)
        with open(path, "r") as f:
            return json.load(f)
    return None


def save_digest(list_id: str, date: str, digest: dict):
    """Save digest to cache."""
    path = _digest_path(list_id, date)
    with open(path, "w") as f:
        json.dump(digest, f, ensure_ascii=False, indent=2)
    logger.info("Digest saved to cache: %s", path)


def _organize_threads(emails: list[dict]) -> list[dict]:
    """Group emails into threads for better context."""
    threads = {}
    for em in emails:
        tid = em.get("thread_id", em["id"])
        if tid not in threads:
            threads[tid] = {"subject": em["subject"], "messages": []}
        threads[tid]["messages"].append(em)

    # Sort messages within each thread by epoch
    result = []
    for tid, thread in threads.items():
        thread["messages"].sort(key=lambda x: x.get("epoch", 0))
        result.append(thread)
    return result


def _inject_date_range(summary_text: str, date_range: str) -> str:
    """Inject date range into the first markdown heading of the summary.

    If the first line is a `# ...` heading, append the date range in parentheses.
    Otherwise, leave the text as-is (the card header will show the range).
    """
    range_suffix = f"（{date_range}）"
    lines = summary_text.split("\n", 1)
    first_line = lines[0].rstrip()
    if first_line.startswith("# "):
        # Only add if not already present
        if date_range not in first_line:
            lines[0] = first_line + range_suffix
        return "\n".join(lines)
    return summary_text


def _build_prompt(emails: list[dict], list_name: str, date: str, lang: str = "zh") -> str:
    """Build the prompt for LLM API."""
    threads = _organize_threads(emails)

    email_text = ""
    for i, thread in enumerate(threads, 1):
        email_text += f"\n### Thread {i}: {thread['subject']}\n"
        for msg in thread["messages"]:
            body = msg["body"][:2000]  # Truncate long bodies
            email_text += f"\nFrom: {msg['from']}\n{body}\n---\n"

    if lang == "en":
        return f"""You are an email digest assistant. Summarize the following mailing list emails from "{list_name}" on {date}.

Provide a structured summary in Markdown format with:
1. **Overview**: A 2-3 sentence high-level summary of the day's activity
2. **Key Discussions**: List the main topics discussed, with brief summaries for each thread
3. **Action Items**: Any decisions made, patches submitted, or tasks assigned
4. **Notable**: Anything particularly interesting or important

**Please output in English.**
Keep it concise but informative.

---

Emails ({len(emails)} total, {len(threads)} threads):

{email_text}"""
    else:
        return f"""You are an email digest assistant. Summarize the following mailing list emails from "{list_name}" on {date}.

Provide a structured summary in Markdown format with:
1. **概览**: 用 2-3 句话概括当天邮件的整体活动情况
2. **主要讨论**: 列出讨论的主要话题，对每个主题进行简要总结
3. **行动项**: 任何已做出的决定、提交的补丁或分配的任务
4. **值得关注**: 任何特别有趣或重要的内容

**请务必使用中文输出。**
保持简洁但信息丰富。

---

邮件 (共 {len(emails)} 封, {len(threads)} 个主题):

{email_text}"""


# --- LLM Provider Implementations ---


def _get_active_provider(llm_config: dict) -> dict:
    """Get the active provider configuration."""
    active_id = llm_config.get("active_provider", "")
    providers = llm_config.get("providers", [])

    for p in providers:
        if p["id"] == active_id:
            logger.info("Using active provider: %s (type=%s, model=%s)", p["name"], p["type"], p.get("model"))
            return p

    # Fallback: return first provider if active not found
    if providers:
        logger.warning("Active provider '%s' not found, falling back to first provider: %s", active_id, providers[0]["name"])
        return providers[0]

    raise ValueError("No LLM provider configured. Please add one in Settings.")


def _call_anthropic(prompt: str, provider: dict) -> str:
    """Call Anthropic Claude API."""
    try:
        import anthropic
    except ImportError:
        raise ImportError("Anthropic SDK not installed. Run: pip install anthropic")

    token = provider.get("auth_token", "")
    base_url = provider.get("base_url", "").strip()

    # Detect token type: OAuth tokens (sk-ant-oat*) use Bearer auth,
    # standard API keys (sk-ant-api*) use X-Api-Key header.
    is_oauth = any(p.startswith("oat") for p in token.split("-")[:4])
    if is_oauth:
        kwargs = {"auth_token": token, "api_key": "stub"}
        logger.debug("Using Bearer auth (OAuth token detected)")
    else:
        kwargs = {"api_key": token}
        logger.debug("Using X-Api-Key auth (standard API key)")

    if base_url:
        kwargs["base_url"] = base_url
        # Some proxies block the default Anthropic SDK User-Agent;
        # use a generic one when routing through a custom base_url.
        from anthropic._types import Omit
        kwargs["default_headers"] = {"User-Agent": "python-httpx"}
        if is_oauth:
            # Also suppress the X-Api-Key header so the proxy only sees Bearer auth.
            kwargs["default_headers"]["X-Api-Key"] = Omit()

    client = anthropic.Anthropic(**kwargs)
    model = provider.get("model", "claude-sonnet-4-20250514")

    logger.info("Calling Anthropic API — model=%s, base_url=%s, prompt_len=%d", model, base_url or "(default)", len(prompt))
    t0 = time.time()
    message = client.messages.create(
        model=model,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    elapsed = time.time() - t0
    result = message.content[0].text
    logger.info("Anthropic API responded — %.1fs, usage: input=%s output=%s, response_len=%d",
                elapsed, getattr(message.usage, 'input_tokens', '?'), getattr(message.usage, 'output_tokens', '?'), len(result))
    return result


def _call_openai(prompt: str, provider: dict) -> str:
    """Call OpenAI-compatible API (works with OpenAI, Azure, and compatible services)."""
    try:
        import openai
    except ImportError:
        raise ImportError("OpenAI SDK not installed. Run: pip install openai")

    kwargs = {"api_key": provider.get("auth_token", "")}
    base_url = provider.get("base_url", "").strip()
    if base_url:
        kwargs["base_url"] = base_url

    client = openai.OpenAI(**kwargs)
    model = provider.get("model", "gpt-4o")

    logger.info("Calling OpenAI API — model=%s, base_url=%s, prompt_len=%d", model, base_url or "(default)", len(prompt))
    t0 = time.time()
    response = client.chat.completions.create(
        model=model,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    elapsed = time.time() - t0
    result = response.choices[0].message.content
    usage = response.usage
    logger.info("OpenAI API responded — %.1fs, usage: input=%s output=%s, response_len=%d",
                elapsed, getattr(usage, 'prompt_tokens', '?') if usage else '?',
                getattr(usage, 'completion_tokens', '?') if usage else '?', len(result) if result else 0)
    return result


def _call_google(prompt: str, provider: dict) -> str:
    """Call Google Generative AI API."""
    try:
        import google.generativeai as genai
    except ImportError:
        raise ImportError(
            "Google Generative AI SDK not installed. Run: pip install google-generativeai"
        )

    api_key = provider.get("auth_token", "")
    base_url = provider.get("base_url", "").strip()

    configure_kwargs = {"api_key": api_key}
    if base_url:
        configure_kwargs["client_options"] = {"api_endpoint": base_url}

    model_name = provider.get("model", "gemini-2.0-flash")
    logger.info("Calling Google API — model=%s, base_url=%s, prompt_len=%d", model_name, base_url or "(default)", len(prompt))
    genai.configure(**configure_kwargs)
    model = genai.GenerativeModel(model_name)
    t0 = time.time()
    response = model.generate_content(prompt)
    elapsed = time.time() - t0
    result = response.text
    logger.info("Google API responded — %.1fs, response_len=%d", elapsed, len(result))
    return result


def _call_llm(prompt: str, provider: dict) -> str:
    """Route to the appropriate LLM provider."""
    provider_type = provider.get("type", "anthropic")

    auth_token = provider.get("auth_token", "")
    if not auth_token:
        raise ValueError(
            f"Auth token not configured for provider '{provider.get('name', provider.get('id', 'unknown'))}'."
        )

    try:
        if provider_type == "anthropic":
            return _call_anthropic(prompt, provider)
        elif provider_type == "openai":
            return _call_openai(prompt, provider)
        elif provider_type == "google":
            return _call_google(prompt, provider)
        else:
            raise ValueError(f"Unknown provider type: {provider_type}")
    except Exception:
        logger.exception("LLM call failed — provider=%s, type=%s", provider.get("name"), provider_type)
        raise


def generate_digest(
    emails: list[dict],
    list_id: str,
    list_name: str,
    date: str,
    llm_config: dict,
    progress_cb=None,
    force: bool = False,
    lang: str = "zh",
    date_range: str = "",
) -> dict:
    """Generate an AI digest for the given emails.

    Args:
        llm_config: The full 'llm' section from config, containing
                    'active_provider' and 'providers' list.
        progress_cb: Optional callback(event_type, message, **kwargs) for progress events.
        force: If True, skip cache and regenerate.

    Returns {"summary": str, "generated_at": str, "email_count": int}
    """
    # Check cache first (skip when force=True)
    if not force:
        if progress_cb:
            progress_cb("progress", "正在检查缓存...", step="cache_check")
        cached = load_digest(list_id, date)
        if cached:
            logger.info("Returning cached digest for list=%s, date=%s", list_id, date)
            if progress_cb:
                progress_cb("progress", "找到缓存的摘要，直接返回", step="cache_hit")
            return cached
    else:
        logger.info("Force regenerating digest for list=%s, date=%s (skipping cache)", list_id, date)

    if not emails:
        logger.info("No emails found for list=%s, date=%s", list_id, date)
        if progress_cb:
            progress_cb("progress", "没有找到邮件", step="no_emails")
        return {"summary": "No emails found for this date.", "generated_at": "", "email_count": 0}

    logger.info("Generating digest for list=%s (%s), date=%s, emails=%d", list_id, list_name, date, len(emails))

    if progress_cb:
        progress_cb("progress", "正在获取 LLM 配置...", step="llm_config")
    provider = _get_active_provider(llm_config)

    if progress_cb:
        progress_cb("progress", f"正在构建提示词 ({len(emails)} 封邮件)...", step="build_prompt")
    prompt = _build_prompt(emails, list_name, date, lang=lang)

    if progress_cb:
        provider_name = provider.get("name", provider.get("id", "unknown"))
        model = provider.get("model", "unknown")
        progress_cb(
            "progress",
            f"正在调用 LLM ({provider_name} / {model})，请耐心等待...",
            step="llm_call",
        )

    try:
        summary_text = _call_llm(prompt, provider)
    except Exception as e:
        if progress_cb:
            progress_cb("error", f"LLM 调用失败: {e}")
        raise

    # Inject date range into the first heading
    if date_range:
        summary_text = _inject_date_range(summary_text, date_range)

    if progress_cb:
        progress_cb("progress", "摘要生成完成，正在保存...", step="saving")

    digest = {
        "summary": summary_text,
        "generated_at": datetime.now().isoformat(),
        "email_count": len(emails),
    }

    save_digest(list_id, date, digest)

    # Export summary to Markdown file
    try:
        export_summary_markdown(
            source_type="email",
            source_id=list_id,
            content_date=date,
            lang=lang,
            summary_text=summary_text,
            metadata={"list_name": list_name, "email_count": len(emails)},
        )
    except Exception:
        logger.exception("Failed to export email summary to Markdown")

    logger.info("Digest generation complete for list=%s, date=%s", list_id, date)
    return digest


# --- Daily Summary (one-click, all lists, multi-day) ---

DAILY_SUMMARY_DIR = os.path.join(os.path.dirname(__file__), "data", "daily_summaries")


def _daily_summary_path(trigger_date: str) -> str:
    os.makedirs(DAILY_SUMMARY_DIR, exist_ok=True)
    return os.path.join(DAILY_SUMMARY_DIR, f"daily_summary_{trigger_date}.json")


def load_daily_summary(trigger_date: str) -> dict | None:
    """Load cached daily summary if it exists."""
    path = _daily_summary_path(trigger_date)
    if os.path.exists(path):
        logger.debug("Loading cached daily summary: %s", path)
        with open(path, "r") as f:
            return json.load(f)
    return None


def save_daily_summary(trigger_date: str, result: dict):
    """Save daily summary to cache."""
    path = _daily_summary_path(trigger_date)
    with open(path, "w") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    logger.info("Daily summary saved to cache: %s", path)


def delete_daily_summary(trigger_date: str) -> bool:
    """Delete cached daily summary. Returns True if a file was deleted."""
    path = _daily_summary_path(trigger_date)
    if os.path.exists(path):
        os.remove(path)
        logger.info("Deleted cached daily summary: %s", path)
        return True
    logger.debug("No cached daily summary to delete for %s", trigger_date)
    return False


def _build_per_list_prompt(list_name: str, date_emails: dict, dates: list[str]) -> str:
    """Build the prompt for a single mailing list's multi-day summary.

    Args:
        list_name: display name of the mailing list
        date_emails: {date: [emails]}
        dates: sorted list of date strings
    """
    sections = ""
    total = 0
    for date in dates:
        emails = date_emails.get(date, [])
        if not emails:
            sections += f"\n## {date}: 无邮件\n"
            continue
        total += len(emails)
        threads = _organize_threads(emails)
        sections += f"\n## {date} ({len(emails)} 封邮件, {len(threads)} 个讨论主题)\n"
        for i, thread in enumerate(threads, 1):
            sections += f"\n### 主题 {i}: {thread['subject']}\n"
            for msg in thread["messages"]:
                body = msg["body"][:1500]
                sections += f"\n发件人: {msg['from']}\n{body}\n---\n"

    num_days = len(dates)
    return f"""你是一个邮件摘要助手。请对以下来自邮件组 "{list_name}" 的最近 {num_days} 天的邮件进行分析。

**请务必使用中文输出。**

请严格按照以下 JSON 格式返回结果，不要输出任何其他文字，只输出 JSON：

{{
  "overview": "用 2-4 句话概括这 {num_days} 天该邮件组的整体活动情况、关键讨论和重要决定（Markdown 格式）",
  "days": [
    {{
      "date": "YYYY-MM-DD",
      "summary": "当天的详细摘要，包括讨论主题、关键观点、行动项等（Markdown 格式，使用 ### 标题和 - 列表）"
    }}
  ]
}}

注意：
- days 数组必须包含全部 {num_days} 天，即使某天无邮件也要包含（summary 写"无邮件活动"即可）
- overview 和 summary 内容都使用 Markdown 格式
- 只输出 JSON，不要有 ```json 标记或其他文字

日期范围: {dates[0]} 至 {dates[-1]}
邮件总数: {total}

---
{sections}"""


def _parse_list_summary(raw_text: str, list_name: str, dates: list[str]) -> dict:
    """Parse LLM response into structured per-list summary.

    Attempts JSON parse, falls back to returning raw text as overview.
    """
    text = raw_text.strip()
    # Strip markdown code fences if present
    if text.startswith("```"):
        first_nl = text.index("\n")
        text = text[first_nl + 1:]
    if text.endswith("```"):
        text = text[:-3].strip()

    try:
        data = json.loads(text)
        overview = data.get("overview", "")
        days = data.get("days", [])
        # Ensure all dates are present
        existing_dates = {d["date"] for d in days}
        for date in dates:
            if date not in existing_dates:
                days.append({"date": date, "summary": "无邮件活动"})
        days.sort(key=lambda d: d["date"])
        return {"name": list_name, "overview": overview, "days": days}
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        logger.warning("Failed to parse JSON for %s: %s. Using raw text.", list_name, e)
        # Fallback: use raw text as overview
        return {
            "name": list_name,
            "overview": text,
            "days": [{"date": d, "summary": "（解析失败，请查看总览）"} for d in dates],
        }


def generate_daily_summary(
    all_data: dict,
    dates: list[str],
    llm_config: dict,
    trigger_date: str,
    force: bool = False,
) -> dict:
    """Generate a daily summary across all mailing lists for the given dates.

    Args:
        all_data: {list_name: {date: [emails]}}
        dates: sorted list of date strings (e.g. last 3 days)
        llm_config: The full 'llm' section from config
        trigger_date: today's date, used for caching
        force: if True, skip cache and regenerate

    Returns structured result with per-list summaries.
    """
    # Check cache first (unless force regenerate)
    if not force:
        cached = load_daily_summary(trigger_date)
        if cached:
            logger.info("Returning cached daily summary for %s", trigger_date)
            return cached
    else:
        logger.info("Force regenerating daily summary for %s (skipping cache)", trigger_date)

    # Compute statistics
    total_emails = 0
    list_stats = {}
    for list_name, date_map in all_data.items():
        list_total = sum(len(emails) for emails in date_map.values())
        list_stats[list_name] = {
            "total": list_total,
            "per_day": {d: len(date_map.get(d, [])) for d in dates},
        }
        total_emails += list_total

    if total_emails == 0:
        logger.info("No emails found across all lists for dates %s", dates)
        empty_lists = [
            {"name": ln, "overview": "在所选日期范围内未找到任何邮件。",
             "days": [{"date": d, "summary": "无邮件活动"} for d in dates]}
            for ln in all_data
        ]
        return {
            "lists": empty_lists,
            "generated_at": "",
            "statistics": list_stats,
            "dates": dates,
            "total_emails": 0,
        }

    provider = _get_active_provider(llm_config)
    lists_result = []

    for list_name, date_map in all_data.items():
        list_total = list_stats[list_name]["total"]
        if list_total == 0:
            logger.info("Skipping LLM call for %s — no emails", list_name)
            lists_result.append({
                "name": list_name,
                "overview": "在所选日期范围内未找到任何邮件。",
                "days": [{"date": d, "summary": "无邮件活动"} for d in dates],
            })
            continue

        logger.info(
            "Generating per-list summary for %s — %d emails across %d days",
            list_name, list_total, len(dates),
        )
        try:
            prompt = _build_per_list_prompt(list_name, date_map, dates)
            raw = _call_llm(prompt, provider)
            parsed = _parse_list_summary(raw, list_name, dates)
            lists_result.append(parsed)
        except Exception:
            logger.exception("Failed to generate summary for %s", list_name)
            lists_result.append({
                "name": list_name,
                "overview": "生成摘要时出错，请稍后重试。",
                "days": [{"date": d, "summary": "生成失败"} for d in dates],
            })

    result = {
        "lists": lists_result,
        "generated_at": datetime.now().isoformat(),
        "statistics": list_stats,
        "dates": dates,
        "total_emails": total_emails,
    }

    save_daily_summary(trigger_date, result)
    logger.info("Daily summary generation complete for %s", trigger_date)
    return result


# --- GitHub Digest ---


def _build_github_prompt(activity: dict, repo_name: str, days: int, lang: str = "zh", date_range: str = "") -> str:
    """Build the prompt for GitHub activity summary."""
    prs = activity.get("pulls", [])
    issues = activity.get("issues", [])
    stats = activity.get("stats", {})

    sections = ""

    # PR section
    if prs:
        sections += f"\n## Pull Requests ({len(prs)})\n"
        for pr in prs:
            state = "Merged" if pr.get("merged") else ("Open" if pr["state"] == "open" else "Closed")
            draft = " [Draft]" if pr.get("draft") else ""
            labels = ", ".join(pr.get("labels", [])) if pr.get("labels") else ""
            label_text = f" Labels: {labels}" if labels else ""
            url = pr.get("html_url", "")
            sections += f"\n- #{pr['number']} {pr['title']}{draft}\n"
            sections += f"  URL: {url}\n"
            sections += f"  Author: {pr['user']} | Status: {state}{label_text}\n"
            sections += f"  Created: {pr.get('created_at', '')[:10]} | Updated: {pr.get('updated_at', '')[:10]}\n"

    # Issue section
    if issues:
        sections += f"\n## Issues ({len(issues)})\n"
        for issue in issues:
            state = "Open" if issue["state"] == "open" else "Closed"
            labels = ", ".join(issue.get("labels", [])) if issue.get("labels") else ""
            label_text = f" Labels: {labels}" if labels else ""
            url = issue.get("html_url", "")
            sections += f"\n- #{issue['number']} {issue['title']}\n"
            sections += f"  URL: {url}\n"
            sections += f"  Author: {issue['user']} | Status: {state} | {issue.get('comments', 0)} comments{label_text}\n"
            sections += f"  Created: {issue.get('created_at', '')[:10]} | Updated: {issue.get('updated_at', '')[:10]}\n"


    if lang == "en":
        return f"""You are a GitHub project activity analyst. Analyze and summarize the following PR and Issue activity for the repository "{repo_name}" over the last {days} days.

**Please output in English.**

Provide a structured Markdown summary containing:

1. **Trend Analysis**: Brief analysis of project activity, focus areas, etc.
2. **Overview**: 2-3 sentences summarizing the repository's recent activity
3. **Key PRs**: List the most important Pull Requests (merged first), briefly explaining their content and significance. Each PR must include a clickable link in the format [#number](URL)
4. **Active Issues**: List noteworthy Issues, especially those with many comments or important labels. Each Issue must include a clickable link in the format [#number](URL)

Note: When mentioning PRs or Issues, always use Markdown link format [#number](URL) to make them clickable to the GitHub page.
IMPORTANT: Use unordered bullet lists (- item) to present PRs and Issues. Do NOT use markdown tables.

Statistics:
- Total PRs: {stats.get('total_prs', 0)} (Merged: {stats.get('merged_prs', 0)}, Open: {stats.get('open_prs', 0)}, Closed: {stats.get('closed_prs', 0)})
- Total Issues: {stats.get('total_issues', 0)} (Open: {stats.get('open_issues', 0)}, Closed: {stats.get('closed_issues', 0)})

---
{sections}"""
    else:
        return f"""你是一个 GitHub 项目活动分析助手。请对以下仓库 "{repo_name}" 最近 {days} 天的 PR 和 Issue 活动进行分析和总结。

**请使用中文输出。**

请提供一个结构化的 Markdown 格式摘要，包含：

1. **趋势观察**: 对项目活跃度、关注领域等做简要分析
2. **总览**: 用 2-3 句话概括这个仓库最近的活动情况
3. **重要 PR**: 列出最重要的 Pull Request（已合并的优先），简要说明其内容和意义。每个 PR 必须包含可点击的链接，格式为 [#编号](链接地址)
4. **活跃 Issue**: 列出值得关注的 Issue，特别是评论较多或有重要标签的。每个 Issue 必须包含可点击的链接，格式为 [#编号](链接地址)

注意：在提到 PR 或 Issue 时，务必使用 Markdown 链接格式 [#编号](URL) 使其可点击跳转到 GitHub 页面。
**重要：请使用无序列表（- 列表项）来展示 PR 和 Issue，不要使用 Markdown 表格。**

统计数据:
- PR 总数: {stats.get('total_prs', 0)} (合并: {stats.get('merged_prs', 0)}, 开放: {stats.get('open_prs', 0)}, 关闭: {stats.get('closed_prs', 0)})
- Issue 总数: {stats.get('total_issues', 0)} (开放: {stats.get('open_issues', 0)}, 关闭: {stats.get('closed_issues', 0)})

---
{sections}"""


def generate_github_digest(
    activity: dict,
    repo_id: str,
    repo_name: str,
    days: int,
    llm_config: dict,
    cache_key: str,
    progress_cb=None,
    force: bool = False,
    lang: str = "zh",
    date_range: str = "",
) -> dict:
    """Generate an AI digest for GitHub activity.

    Returns {"summary": str, "generated_at": str, "stats": dict}
    """
    # Check cache (skip when force=True)
    if not force:
        if progress_cb:
            progress_cb("progress", "正在检查缓存...", step="cache_check")
        cached = load_digest(cache_key, "")
        if cached:
            logger.info("Returning cached GitHub digest for %s", cache_key)
            if progress_cb:
                progress_cb("progress", "找到缓存的摘要，直接返回", step="cache_hit")
            return cached
    else:
        logger.info("Force regenerating GitHub digest for %s (skipping cache)", cache_key)

    prs = activity.get("pulls", [])
    issues = activity.get("issues", [])
    if not prs and not issues:
        logger.info("No GitHub activity for %s (%s)", repo_id, repo_name)
        if progress_cb:
            progress_cb("progress", "没有找到 PR 或 Issue 活动", step="no_activity")
        return {
            "summary": "在所选时间范围内没有 PR 或 Issue 活动。",
            "generated_at": "",
            "stats": activity.get("stats", {}),
        }

    logger.info("Generating GitHub digest for %s (%s), days=%d, prs=%d, issues=%d",
                repo_id, repo_name, days, len(prs), len(issues))

    if progress_cb:
        progress_cb("progress", "正在获取 LLM 配置...", step="llm_config")
    provider = _get_active_provider(llm_config)

    if progress_cb:
        progress_cb(
            "progress",
            f"正在构建提示词 ({len(prs)} 个 PR, {len(issues)} 个 Issue)...",
            step="build_prompt",
        )
    prompt = _build_github_prompt(activity, repo_name, days, lang=lang, date_range=date_range)

    if progress_cb:
        provider_name = provider.get("name", provider.get("id", "unknown"))
        model = provider.get("model", "unknown")
        progress_cb(
            "progress",
            f"正在调用 LLM ({provider_name} / {model})，请耐心等待...",
            step="llm_call",
        )

    try:
        summary_text = _call_llm(prompt, provider)
    except Exception as e:
        if progress_cb:
            progress_cb("error", f"LLM 调用失败: {e}")
        raise

    # Inject date range into the first heading
    if date_range:
        summary_text = _inject_date_range(summary_text, date_range)

    if progress_cb:
        progress_cb("progress", "摘要生成完成，正在保存...", step="saving")

    digest = {
        "summary": summary_text,
        "generated_at": datetime.now().isoformat(),
        "stats": activity.get("stats", {}),
    }

    save_digest(cache_key, "", digest)

    # Export summary to Markdown file
    try:
        # content_date: use today as reference date for the digest range
        content_date = datetime.now().strftime("%Y-%m-%d")
        export_summary_markdown(
            source_type="github",
            source_id=repo_id,
            content_date=content_date,
            lang=lang,
            summary_text=summary_text,
            metadata={"repo_name": repo_name, "days": days,
                      "total_prs": len(prs), "total_issues": len(issues)},
        )
    except Exception:
        logger.exception("Failed to export GitHub summary to Markdown")

    logger.info("GitHub digest complete for %s", cache_key)
    return digest


# --- Slack Digest ---


def _build_slack_prompt(messages: list[dict], channel_name: str, days: int,
                        lang: str = "zh", date_range: str = "") -> str:
    """Build the prompt for Slack message summary."""
    # Group messages by date for clarity
    by_date: dict[str, list[dict]] = {}
    for msg in messages:
        date = msg.get("date", "unknown")
        by_date.setdefault(date, [])
        by_date[date].append(msg)

    sections = ""
    for date in sorted(by_date.keys()):
        day_msgs = by_date[date]
        sections += f"\n## {date} ({len(day_msgs)} messages)\n"
        for msg in day_msgs:
            text = msg.get("text", "")[:1500]
            user = msg.get("user", "unknown")
            reactions = " ".join(msg.get("reactions", []))
            reaction_text = f"  [Reactions: {reactions}]" if reactions else ""
            thread_count = msg.get("thread_reply_count", 0)
            thread_text = f"  [Thread: {thread_count} replies]" if thread_count else ""

            sections += f"\n- **{user}**: {text}{reaction_text}{thread_text}\n"

            # Include thread replies if available
            for reply in msg.get("replies_preview", []):
                reply_text = reply.get("text", "")[:500]
                reply_user = reply.get("user", "unknown")
                sections += f"  - ↳ **{reply_user}**: {reply_text}\n"

    total_msgs = len(messages)
    total_threads = sum(1 for m in messages if m.get("thread_reply_count", 0) > 0)
    range_desc = date_range if date_range else f"最近 {days} 天"

    if lang == "en":
        return f"""You are a Slack channel digest assistant. Analyze and summarize the following messages from the Slack channel "#{channel_name}" over {range_desc}.

**Please output in English.**

Provide a structured Markdown summary containing:

1. **Overview**: 2-3 sentences summarizing the channel's activity and main topics
2. **Key Discussions**: List the most important discussion threads and topics, summarizing key points and conclusions
3. **Decisions & Action Items**: Any decisions made or action items agreed upon
4. **Notable Highlights**: Any particularly important messages, widely-reacted messages, or trending topics
5. **Active Participants**: Note the most active contributors (if relevant)

Keep it concise but informative. Focus on substance over mechanics.

Statistics:
- Total messages: {total_msgs}
- Messages with threads: {total_threads}
- Time range: {range_desc}

---
{sections}"""
    else:
        return f"""你是一个 Slack 频道摘要助手。请对以下来自 Slack 频道 "#{channel_name}" {range_desc}的消息进行分析和总结。

**请使用中文输出。**

请提供一个结构化的 Markdown 格式摘要，包含：

1. **概览**: 用 2-3 句话概括频道的活动情况和主要话题
2. **主要讨论**: 列出最重要的讨论主题和内容，总结要点和结论
3. **决策与行动项**: 任何已做出的决定或达成的行动事项
4. **值得关注**: 任何特别重要的消息、获得较多反应的消息或热门话题
5. **活跃参与者**: 列出最活跃的贡献者（如果相关的话）

保持简洁但信息丰富。重点关注内容实质而非形式。

统计数据:
- 消息总数: {total_msgs}
- 包含讨论串的消息: {total_threads}
- 时间范围: {range_desc}

---
{sections}"""


def generate_slack_digest(
    messages: list[dict],
    channel_key: str,
    channel_name: str,
    days: int,
    llm_config: dict,
    cache_key: str,
    progress_cb=None,
    force: bool = False,
    lang: str = "zh",
    date_range: str = "",
) -> dict:
    """Generate an AI digest for Slack channel messages.

    Returns {"summary": str, "generated_at": str, "stats": dict}
    """
    # Check cache (skip when force=True)
    if not force:
        if progress_cb:
            progress_cb("progress", "正在检查缓存...", step="cache_check")
        cached = load_digest(cache_key, "")
        if cached:
            logger.info("Returning cached Slack digest for %s", cache_key)
            if progress_cb:
                progress_cb("progress", "找到缓存的摘要，直接返回", step="cache_hit")
            return cached
    else:
        logger.info("Force regenerating Slack digest for %s (skipping cache)", cache_key)

    if not messages:
        logger.info("No Slack messages for %s (%s)", channel_key, channel_name)
        if progress_cb:
            progress_cb("progress", "没有找到消息", step="no_messages")
        return {
            "summary": "在所选时间范围内没有频道消息。",
            "generated_at": "",
            "stats": {"total_messages": 0},
        }

    total_msgs = len(messages)
    total_threads = sum(1 for m in messages if m.get("thread_reply_count", 0) > 0)
    stats = {
        "total_messages": total_msgs,
        "threaded_messages": total_threads,
    }

    logger.info("Generating Slack digest for %s (%s), days=%d, messages=%d",
                channel_key, channel_name, days, total_msgs)

    if progress_cb:
        progress_cb("progress", "正在获取 LLM 配置...", step="llm_config")
    provider = _get_active_provider(llm_config)

    if progress_cb:
        progress_cb(
            "progress",
            f"正在构建提示词 ({total_msgs} 条消息)...",
            step="build_prompt",
        )
    prompt = _build_slack_prompt(messages, channel_name, days, lang=lang, date_range=date_range)

    if progress_cb:
        provider_name = provider.get("name", provider.get("id", "unknown"))
        model = provider.get("model", "unknown")
        progress_cb(
            "progress",
            f"正在调用 LLM ({provider_name} / {model})，请耐心等待...",
            step="llm_call",
        )

    try:
        summary_text = _call_llm(prompt, provider)
    except Exception as e:
        if progress_cb:
            progress_cb("error", f"LLM 调用失败: {e}")
        raise

    # Inject date range into the first heading
    if date_range:
        summary_text = _inject_date_range(summary_text, date_range)

    if progress_cb:
        progress_cb("progress", "摘要生成完成，正在保存...", step="saving")

    digest = {
        "summary": summary_text,
        "generated_at": datetime.now().isoformat(),
        "stats": stats,
    }

    save_digest(cache_key, "", digest)

    # Export summary to Markdown file
    try:
        content_date = datetime.now().strftime("%Y-%m-%d")
        export_summary_markdown(
            source_type="slack",
            source_id=channel_key,
            content_date=content_date,
            lang=lang,
            summary_text=summary_text,
            metadata={"channel_name": channel_name, "days": days,
                      "total_messages": total_msgs, "threaded_messages": total_threads},
        )
    except Exception:
        logger.exception("Failed to export Slack summary to Markdown")

    logger.info("Slack digest complete for %s", cache_key)
    return digest


# ---------------------------------------------------------------------------
# Summary Markdown export & listing
# ---------------------------------------------------------------------------

def export_summary_markdown(
    source_type: str,
    source_id: str,
    content_date: str,
    lang: str,
    summary_text: str,
    metadata: dict | None = None,
):
    """Export an AI summary to a Markdown file in data/summaries/.

    The file includes a YAML-like header and the summary body.
    Filename pattern: {source_type}__{source_id}__{gen_date}__{content_date}__{lang}.md
    """
    os.makedirs(SUMMARY_DIR, exist_ok=True)
    gen_date = datetime.now().strftime("%Y-%m-%d")
    gen_time = datetime.now().isoformat()
    filename = f"{source_type}__{source_id}__{gen_date}__{content_date}__{lang}.md"
    filepath = os.path.join(SUMMARY_DIR, filename)

    header_lines = [
        "---",
        f"source_type: {source_type}",
        f"source_id: {source_id}",
        f"generated_at: {gen_time}",
        f"content_date: {content_date}",
        f"language: {lang}",
    ]
    if metadata:
        for k, v in metadata.items():
            header_lines.append(f"{k}: {v}")
    header_lines.append("---")
    header_lines.append("")

    content = "\n".join(header_lines) + summary_text + "\n"

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    logger.info("Summary exported to Markdown: %s", filepath)


def list_summary_files(source_type: str | None = None) -> list[dict]:
    """List all saved summary Markdown files.

    Returns a list of dicts with keys: filename, source_type, source_id,
    gen_date, content_date, lang.
    """
    if not os.path.isdir(SUMMARY_DIR):
        return []

    results = []
    for fname in sorted(os.listdir(SUMMARY_DIR), reverse=True):
        if not fname.endswith(".md"):
            continue
        parts = fname[:-3].split("__")  # strip .md, split by __
        if len(parts) < 5:
            continue
        s_type, s_id, g_date, c_date, lang = parts[0], parts[1], parts[2], parts[3], parts[4]
        if source_type and s_type != source_type:
            continue
        results.append({
            "filename": fname,
            "source_type": s_type,
            "source_id": s_id,
            "gen_date": g_date,
            "content_date": c_date,
            "lang": lang,
        })
    return results


def read_summary_file(filename: str) -> str | None:
    """Read the contents of a summary Markdown file."""
    filepath = os.path.join(SUMMARY_DIR, filename)
    if not os.path.exists(filepath):
        return None
    with open(filepath, "r", encoding="utf-8") as f:
        return f.read()
