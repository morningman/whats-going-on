"""ASF OAuth login helper — automates lists.apache.org authentication."""

import logging
import re
import uuid

import requests

logger = logging.getLogger("asf_auth")

# PonyMail Foal at lists.apache.org
PONYMAIL_BASE = "https://lists.apache.org"
ASF_OAUTH_AUTH = "https://oauth.apache.org/auth"
ASF_OAUTH_GATEWAY = "https://oauth.apache.org/gateway"


def login(username: str, password: str) -> dict:
    """Log in to lists.apache.org using ASF LDAP credentials via OAuth.

    Returns dict with keys:
        ok (bool): True if login succeeded
        message (str): Human-readable status
        cookie (str): Session cookie string (only if ok)
        uid (str): ASF user ID (only if ok)
        fullname (str): Full name (only if ok)
    """
    if not username or not password:
        return {"ok": False, "message": "Username and password are required."}

    session = requests.Session()
    session.headers.update({"User-Agent": "EmailWatcher/1.0"})

    try:
        # ------------------------------------------------------------------
        # Step 1: Initiate the OAuth flow via PonyMail's frontend
        # PonyMail's oauth.html page lists OAuth providers and each has a
        # link like: /api/oauth?key=apache&redirect_uri=...
        # We need to find the correct redirect URL that PonyMail uses for
        # the ASF OAuth provider.
        #
        # The PonyMail Foal OAuth JS typically redirects to:
        #   {oauth_portal}?state={state}&redirect_uri={ponymail_callback}
        # where:
        #   oauth_portal = https://oauth.apache.org/
        #   ponymail_callback = https://lists.apache.org/oauth.html
        #
        # After ASF OAuth authenticates, it redirects back to:
        #   https://lists.apache.org/oauth.html?code=...&state=...
        #
        # The PonyMail JS then POSTs the code+state+key to /api/oauth
        # which exchanges it with ASF OAuth for user info and creates a session.
        # ------------------------------------------------------------------

        state_id = str(uuid.uuid4())
        # PonyMail's JS sets redirect_uri to include key and state, like:
        #   oauth.html?key=apache&state=XXXXX
        # When ASF OAuth redirects back, it appends &code=YYYY, giving:
        #   oauth.html?key=apache&state=XXXXX&code=YYYY
        # The JS then sends ALL these params to /api/oauth.lua
        ponymail_callback = (
            f"{PONYMAIL_BASE}/oauth.html?key=apache&state={state_id}"
        )

        # Step 2: Visit ASF OAuth login page
        logger.info("[ASF Auth] Starting OAuth flow (state=%s)", state_id[:8])
        auth_url = (
            f"{ASF_OAUTH_AUTH}?state={state_id}"
            f"&redirect_uri={requests.utils.quote(ponymail_callback, safe='')}"
        )
        resp = session.get(auth_url, timeout=15, allow_redirects=True)

        if resp.status_code != 200:
            logger.warning("[ASF Auth] OAuth login page returned HTTP %d", resp.status_code)
            return {"ok": False, "message": f"Cannot reach ASF OAuth (HTTP {resp.status_code})."}

        # Step 3: Parse the login form to extract session token
        form_session = _extract_form_session(resp.text)
        if not form_session:
            logger.warning("[ASF Auth] Could not find session token in OAuth form")
            return {"ok": False, "message": "Could not parse ASF OAuth login form."}

        # Step 4: Submit credentials to /gateway
        logger.info("[ASF Auth] Submitting credentials for user '%s'", username)
        resp = session.post(
            ASF_OAUTH_GATEWAY,
            data={
                "username": username,
                "password": password,
                "session": form_session,
                "options": "",
            },
            timeout=15,
            allow_redirects=False,  # Don't follow - we need the redirect URL
        )

        if resp.status_code not in (301, 302, 303, 307):
            # Login likely failed
            if "credentials" in resp.text.lower() or "invalid" in resp.text.lower():
                return {"ok": False, "message": "Invalid username or password."}
            logger.warning("[ASF Auth] Unexpected response from /gateway: HTTP %d", resp.status_code)
            return {"ok": False, "message": f"ASF OAuth returned unexpected response (HTTP {resp.status_code})."}

        # Step 5: Extract the code from the redirect URL
        # Redirect URL will be: oauth.html?key=apache&state=XXX&code=YYY
        redirect_url = resp.headers.get("Location", "")
        logger.debug("[ASF Auth] OAuth redirect: %s", redirect_url)

        code = _extract_param(redirect_url, "code")
        if not code:
            error_msg = _extract_param(redirect_url, "error") or "no code returned"
            logger.warning("[ASF Auth] OAuth did not return a code: %s", error_msg)
            return {"ok": False, "message": f"Authentication failed: {error_msg}"}

        # Step 6: Exchange the code with PonyMail to create a session
        # The production lists.apache.org uses a modified oauth.js that adds
        # &oauth_token=<token_url> to the API call. This tells PonyMail's
        # backend where to POST the code for exchange. Without this parameter,
        # PonyMail doesn't know where to exchange the code and fails.
        query_string = redirect_url.split("?", 1)[1] if "?" in redirect_url else ""
        oauth_token_url = "https://oauth.apache.org/token"
        full_url = f"{PONYMAIL_BASE}/api/oauth.lua?{query_string}&oauth_token={oauth_token_url}"
        logger.info("[ASF Auth] Exchanging OAuth code with PonyMail")
        logger.debug("[ASF Auth] API URL: %s", full_url[:120])
        resp = session.get(full_url, timeout=15, allow_redirects=True)

        logger.debug(
            "[ASF Auth] PonyMail OAuth response: status=%d, body=%s, set-cookie=%s",
            resp.status_code,
            resp.text[:200] if resp.text else "(empty)",
            resp.headers.get("Set-Cookie", "(none)")[:100],
        )

        # Check if PonyMail confirmed the login
        try:
            oauth_result = resp.json()
        except Exception:
            oauth_result = {}

        if not oauth_result.get("okay"):
            msg = oauth_result.get("message", "Unknown error")
            logger.warning("[ASF Auth] PonyMail OAuth failed: %s", msg)
            return {"ok": False, "message": f"PonyMail login failed: {msg}"}

        # Extract cookie from Set-Cookie header directly
        # (requests.Session may not store it due to domain/path cookie policy)
        set_cookie_header = resp.headers.get("Set-Cookie", "")
        cookie_str = ""

        if set_cookie_header:
            # Parse "name=value; Path=/; HttpOnly; ..." → "name=value"
            cookie_str = _parse_set_cookie(set_cookie_header)
            logger.debug("[ASF Auth] Extracted cookie from Set-Cookie header: %s", cookie_str[:30] if cookie_str else "(empty)")

        # Also try session cookies as fallback
        if not cookie_str:
            cookie_str = "; ".join(f"{c.name}={c.value}" for c in session.cookies)
            if cookie_str:
                logger.debug("[ASF Auth] Using session cookie jar: %s", cookie_str[:30])

        if not cookie_str:
            logger.warning("[ASF Auth] PonyMail said okay=true but no cookie was set")
            return {"ok": False, "message": "Login succeeded but no session cookie was returned. Please try manual cookie paste."}

        # Step 7: Verify the session
        logger.info("[ASF Auth] Verifying session cookie")
        result = validate_cookie(cookie_str)

        if result["ok"]:
            result["cookie"] = cookie_str
            logger.info("[ASF Auth] Login successful: %s (%s)", result.get("fullname", ""), result.get("uid", ""))
            return result
        else:
            return {"ok": False, "message": "Session cookie was set but could not authenticate. Please try manual cookie paste."}

    except requests.exceptions.ConnectionError as e:
        logger.warning("[ASF Auth] Connection error: %s", e)
        return {"ok": False, "message": "Cannot connect to ASF OAuth. Please check your network."}
    except requests.exceptions.Timeout:
        logger.warning("[ASF Auth] Request timed out")
        return {"ok": False, "message": "Request timed out. Please try again."}
    except Exception as e:
        logger.exception("[ASF Auth] Unexpected error during login")
        return {"ok": False, "message": f"Login error: {str(e)}"}


def validate_cookie(cookie: str) -> dict:
    """Validate a lists.apache.org session cookie.

    Returns dict with keys:
        ok (bool): True if cookie is valid and user is authenticated
        uid (str): ASF user ID
        fullname (str): Full name
        message (str): Status message
    """
    if not cookie:
        return {"ok": False, "message": "No cookie provided.", "uid": "", "fullname": ""}

    try:
        resp = requests.get(
            f"{PONYMAIL_BASE}/api/preferences.lua",
            headers={"Cookie": cookie},
            timeout=15,
        )
        if resp.status_code != 200:
            return {"ok": False, "message": f"Verification failed (HTTP {resp.status_code}).", "uid": "", "fullname": ""}

        prefs = resp.json()
        login_info = prefs.get("login", {})
        credentials = login_info.get("credentials", {})
        uid = credentials.get("uid", "")
        fullname = credentials.get("fullname", "")

        if uid:
            display = f"{fullname} ({uid})" if fullname else uid
            return {"ok": True, "uid": uid, "fullname": fullname, "message": f"Authenticated as {display}"}
        else:
            return {"ok": False, "uid": "", "fullname": "", "message": "Cookie is invalid or expired."}

    except requests.exceptions.ConnectionError:
        return {"ok": False, "uid": "", "fullname": "", "message": "Cannot connect to lists.apache.org."}
    except Exception as e:
        return {"ok": False, "uid": "", "fullname": "", "message": f"Verification error: {str(e)}"}


def _extract_form_session(html: str) -> str:
    """Extract the hidden 'session' field value from the ASF OAuth login form."""
    match = re.search(r'name="session"\s+value="([^"]+)"', html)
    return match.group(1) if match else ""


def _extract_param(url: str, param: str) -> str:
    """Extract a query parameter value from a URL."""
    match = re.search(rf'[?&]{param}=([^&]+)', url)
    return match.group(1) if match else ""


def _parse_set_cookie(header: str) -> str:
    """Parse Set-Cookie header(s) to extract name=value pairs.

    Handles single and multiple Set-Cookie headers (comma-separated in
    some HTTP libraries). Returns a '; '-joined cookie string.
    """
    if not header:
        return ""

    # Set-Cookie can contain multiple cookies separated by commas (when
    # collapsed into a single header) or come as separate headers.
    # requests exposes multiple headers as comma-separated by default.
    # Each cookie looks like: name=value; Path=/; HttpOnly; Secure
    # We need to extract just name=value from each.
    cookies = []
    # Split on commas, but be careful with cookie values containing commas
    # A simple heuristic: split on ", " followed by token= (new cookie)
    parts = re.split(r',\s*(?=\w+=)', header)
    for part in parts:
        # Extract just the "name=value" portion (before first ";")
        nv = part.strip().split(";")[0].strip()
        if "=" in nv:
            cookies.append(nv)

    return "; ".join(cookies)
