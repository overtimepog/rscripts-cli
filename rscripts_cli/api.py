"""API client for rscripts.net."""
import requests

BASE_URL = "https://rscripts.net/api/v2"

_session: requests.Session | None = None


def _get_session() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update({
            "User-Agent": "rscripts-cli/0.1.0",
            "Accept": "application/json",
        })
    return _session


def get_scripts(
    page: int = 1,
    q: str | None = None,
    order_by: str = "date",
    sort: str = "desc",
    no_key_system: bool = False,
    mobile_only: bool = False,
    not_paid: bool = False,
    unpatched: bool = False,
    verified_only: bool = False,
    username: str | None = None,
) -> dict:
    """Fetch a paginated list of scripts."""
    params: dict = {
        "page": page,
        "orderBy": order_by,
        "sort": sort,
    }
    if q:
        params["q"] = q
    if no_key_system:
        params["noKeySystem"] = "true"
    if mobile_only:
        params["mobileOnly"] = "true"
    if not_paid:
        params["notPaid"] = "true"
    if unpatched:
        params["unpatched"] = "true"
    if verified_only:
        params["verifiedOnly"] = "true"

    headers = {}
    if username:
        headers["Username"] = username

    session = _get_session()
    resp = session.get(f"{BASE_URL}/scripts", params=params, headers=headers, timeout=15)
    resp.raise_for_status()
    return resp.json()


def get_script(script_id: str) -> dict:
    """Fetch a single script by ID."""
    session = _get_session()
    resp = session.get(f"{BASE_URL}/script", params={"id": script_id}, timeout=15)
    resp.raise_for_status()
    return resp.json()


def get_trending() -> dict:
    """Fetch the top trending scripts (last 48 hours)."""
    session = _get_session()
    resp = session.get(f"{BASE_URL}/trending", timeout=15)
    resp.raise_for_status()
    return resp.json()


def fetch_raw_script(raw_url: str) -> str:
    """Fetch raw Lua script content from its URL."""
    session = _get_session()
    resp = session.get(raw_url, timeout=15)
    resp.raise_for_status()
    return resp.text


def resolve_creator(script: dict) -> str:
    """Return creator username, handling the legacy `creator` fallback."""
    user = script.get("user")
    if user and isinstance(user, dict):
        return user.get("username", "Unknown")
    return script.get("creator", "Unknown")
