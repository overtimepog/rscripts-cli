"""API client for scriptblox.com."""
import requests

BASE_URL = "https://scriptblox.com/api"

_session: requests.Session | None = None


def _get_session() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update({
            "User-Agent": "rscripts-cli/0.2.0",
            "Accept": "application/json",
        })
    return _session


def search_scripts(
    q: str | None = None,
    page: int = 1,
    mode: str | None = None,
    no_key: bool = False,
    unpatched: bool = False,
    max_results: int | None = None,
) -> dict:
    """Search scripts on scriptblox.com. Returns the raw API response."""
    params: dict = {"page": page}
    if max_results:
        params["max"] = max_results  # server accepts up to 100
    if q:
        params["q"] = q
    if mode:
        params["mode"] = mode
    if no_key:
        params["key"] = "0"
    if unpatched:
        params["patched"] = "0"

    session = _get_session()
    resp = session.get(f"{BASE_URL}/script/search", params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


def fetch_by_place(place_id: int, page: int = 1) -> dict:
    """Scripts for one place (20/page). Universal scripts are mixed in —
    filter on game.gameId."""
    session = _get_session()
    resp = session.get(f"{BASE_URL}/script/fetch",
                       params={"placeId": place_id, "page": page}, timeout=15)
    resp.raise_for_status()
    return resp.json()


def get_script(script_id: str) -> dict:
    """Fetch a single script by ID."""
    session = _get_session()
    resp = session.get(f"{BASE_URL}/script/{script_id}", timeout=15)
    resp.raise_for_status()
    return resp.json()


def get_trending() -> dict:
    """Fetch trending scripts."""
    session = _get_session()
    resp = session.get(f"{BASE_URL}/script/trending", timeout=15)
    resp.raise_for_status()
    return resp.json()
