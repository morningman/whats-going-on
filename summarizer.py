"""AI summarizer module - generates daily email digests using LLM APIs.

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


def _build_prompt(emails: list[dict], list_name: str, date: str) -> str:
    """Build the prompt for LLM API."""
    threads = _organize_threads(emails)

    email_text = ""
    for i, thread in enumerate(threads, 1):
        email_text += f"\n### Thread {i}: {thread['subject']}\n"
        for msg in thread["messages"]:
            body = msg["body"][:2000]  # Truncate long bodies
            email_text += f"\nFrom: {msg['from']}\n{body}\n---\n"

    return f"""You are an email digest assistant. Summarize the following mailing list emails from "{list_name}" on {date}.

Provide a structured summary in Markdown format with:
1. **Overview**: A 2-3 sentence high-level summary of the day's activity
2. **Key Discussions**: List the main topics discussed, with brief summaries for each thread
3. **Action Items**: Any decisions made, patches submitted, or tasks assigned
4. **Notable**: Anything particularly interesting or important

Use the same language as the emails (if emails are in Chinese, summarize in Chinese; if in English, use English).
Keep it concise but informative.

---

Emails ({len(emails)} total, {len(threads)} threads):

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
) -> dict:
    """Generate an AI digest for the given emails.

    Args:
        llm_config: The full 'llm' section from config, containing
                    'active_provider' and 'providers' list.

    Returns {"summary": str, "generated_at": str, "email_count": int}
    """
    # Check cache first
    cached = load_digest(list_id, date)
    if cached:
        logger.info("Returning cached digest for list=%s, date=%s", list_id, date)
        return cached

    if not emails:
        logger.info("No emails found for list=%s, date=%s", list_id, date)
        return {"summary": "No emails found for this date.", "generated_at": "", "email_count": 0}

    logger.info("Generating digest for list=%s (%s), date=%s, emails=%d", list_id, list_name, date, len(emails))
    provider = _get_active_provider(llm_config)
    prompt = _build_prompt(emails, list_name, date)
    summary_text = _call_llm(prompt, provider)

    digest = {
        "summary": summary_text,
        "generated_at": datetime.now().isoformat(),
        "email_count": len(emails),
    }

    save_digest(list_id, date, digest)
    logger.info("Digest generation complete for list=%s, date=%s", list_id, date)
    return digest
