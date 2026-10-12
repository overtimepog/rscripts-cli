"""rscripts.net session auth (better-auth cookie).

The token lives in ~/.config/rscripts-cli/session.json (override the dir with
RS_CONFIG_DIR, or the token itself with RS_SESSION_TOKEN). It is never written
anywhere else.

better-auth sessions slide: calling /api/auth/get-session extends expiresAt,
and if the server rotates the token it comes back in Set-Cookie. `ensure()`
does that check when it's due (daily, or when expiry is near) and persists any
rotated token, so a session used at least once every ~90 days never dies.
When it does die, the CLI asks for a fresh cookie; non-interactive callers
(MCP) just fall back to anonymous requests.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import unquote

import requests

SITE = "https://rscripts.net"
DOMAIN = "rscripts.net"
COOKIE_NAME = "__Secure-better-auth.session_token"
CONFIG_DIR = Path(os.environ.get("RS_CONFIG_DIR") or Path.home() / ".config" / "rscripts-cli")
SESSION_FILE = CONFIG_DIR / "session.json"

CHECK_EVERY = 24 * 3600          # renew/validate at most daily...
RENEW_BEFORE = 7 * 24 * 3600     # ...or whenever expiry is within a week

HOW_TO = (
    "Get it from a logged-in browser: rscripts.net -> DevTools -> Application ->\n"
    f"Cookies -> https://rscripts.net -> copy the value of {COOKIE_NAME}"
)


class AuthError(Exception):
    pass


class SessionRejected(AuthError):
    """The server answered and said the session is invalid (vs. a network or
    Cloudflare hiccup, which must not cost the user their saved session)."""


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def load() -> dict:
    try:
        d = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    env = os.environ.get("RS_SESSION_TOKEN")
    if env:
        d = {**d, "token": parse_token(env), "from_env": True}
    return d


def save(d: dict) -> None:
    if d.get("from_env"):
        return  # never persist an env override
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    d = {k: v for k, v in d.items() if k != "from_env"}
    d.setdefault("cookie_name", COOKIE_NAME)
    tmp = SESSION_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=1), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    tmp.replace(SESSION_FILE)


def clear() -> bool:
    try:
        SESSION_FILE.unlink()
        return True
    except FileNotFoundError:
        return False


def parse_token(raw: str) -> str:
    """Accept the bare value, `name=value`, or a whole Cookie header."""
    raw = raw.strip().strip('"').strip("'")
    m = re.search(re.escape(COOKIE_NAME) + r"=([^;\s]+)", raw)
    if m:
        return m.group(1)
    if ";" in raw:
        raise AuthError(f"no {COOKIE_NAME} in that cookie string")
    return raw


def _cookie_value(token: str) -> str:
    # Browsers show the value URL-encoded (%2B, %3D) and send it that way;
    # normalise a pasted decoded value back to the encoded form.
    return token if "%" in token else requests.utils.quote(unquote(token), safe=".")


# ---------------------------------------------------------------------------
# Session plumbing
# ---------------------------------------------------------------------------

def attach(session: requests.Session) -> bool:
    """Put the saved cookie on a requests session and persist any rotation
    the server sends back. Returns False when there is no token."""
    d = load()
    token = d.get("token")
    if not token:
        return False
    session.cookies.set(COOKIE_NAME, _cookie_value(token), domain=DOMAIN, path="/", secure=True)

    def capture(resp, *a, **k):
        new = resp.cookies.get(COOKIE_NAME)
        if new and new != load().get("token"):
            cur = load()
            cur.update(token=new, rotated_at=time.time())
            save(cur)
        return resp

    if capture.__name__ not in [h.__name__ for h in session.hooks["response"]]:
        session.hooks["response"].append(capture)
    return True


def check(token: str | None = None) -> dict:
    """Validate (and thereby renew) a session. Returns the session info;
    raises AuthError when the token is missing or dead."""
    d = load()
    token = token or d.get("token")
    if not token:
        raise AuthError("not logged in")
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    s.cookies.set(COOKIE_NAME, _cookie_value(token), domain=DOMAIN, path="/", secure=True)
    try:
        r = s.get(f"{SITE}/api/auth/get-session", timeout=20)
    except requests.RequestException as e:
        raise AuthError(f"network error: {e}") from e
    is_json = "json" in r.headers.get("content-type", "")
    if r.status_code == 401 or (r.ok and is_json and not (r.json() or {}).get("session")):
        raise SessionRejected("session expired or invalid")
    if not (r.ok and is_json):
        raise AuthError(f"couldn't check session (HTTP {r.status_code})")  # e.g. CF challenge
    data = r.json()
    sess, user = data["session"], data.get("user") or {}
    info = {
        "token": r.cookies.get(COOKIE_NAME) or token,   # rotated token wins
        "username": user.get("username") or user.get("name"),
        "tier": user.get("subscriptionTier"),
        "expires_at": sess.get("expiresAt"),
        "checked_at": time.time(),
    }
    if info["token"] != token:
        info["rotated_at"] = time.time()
    return info


def _expires_in(d: dict) -> float:
    try:
        exp = datetime.fromisoformat(d["expires_at"].replace("Z", "+00:00"))
        return (exp - datetime.now(timezone.utc)).total_seconds()
    except (KeyError, AttributeError, ValueError):
        return 0


def due(d: dict) -> bool:
    return (time.time() - d.get("checked_at", 0) > CHECK_EVERY
            or _expires_in(d) < RENEW_BEFORE)


def login(raw: str) -> dict:
    """Validate a pasted cookie and save it."""
    info = check(parse_token(raw))
    cur = {k: v for k, v in load().items() if k != "from_env"}
    cur.update(info)
    save(cur)
    return info


def ensure(prompt: Callable[[str], str] | None = None,
           warn: Callable[[str], None] = lambda m: print(m, file=sys.stderr)) -> dict | None:
    """Renew the session if due. If it's dead and `prompt` is given (an
    interactive terminal), ask for a new cookie; otherwise warn and carry on
    anonymously. Returns the session info, or None when anonymous."""
    d = load()
    if not d.get("token"):
        return None
    if not due(d):
        return d
    try:
        info = check()
    except SessionRejected:
        if d.get("from_env"):
            warn("rscripts: RS_SESSION_TOKEN was rejected; continuing anonymously")
            return None
        if prompt is None:
            warn("rscripts: saved session expired — run `rs login`; continuing anonymously")
            return None
        warn(f"rscripts: your session expired.\n{HOW_TO}")
        for _ in range(3):
            raw = prompt("New session cookie (blank to skip)")
            if not raw.strip():
                return None
            try:
                return login(raw)
            except AuthError as e2:
                warn(f"  {e2}")
        return None
    except AuthError:
        return d  # network/Cloudflare hiccup: keep the session, retry next run
    d.update(info)
    save(d)
    return d
