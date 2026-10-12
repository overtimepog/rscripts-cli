"""Script-gap finder: popular Roblox games with few scripts.

Pulls candidate games from Roblox's explore sorts, then counts the scripts each
game's root place has on rscripts.net and scriptblox. Only rows whose linked
place matches count — universal hubs (no place link) never pad a game's total.

Per-game results are cached with the matching rows' dates, so a re-run inside
the TTL is instant and changing the "recent" window needs no re-fetch.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import requests

from . import api
from . import scriptblox

EXPLORE = "https://apis.roblox.com/explore-api/v1"
EXPLORE_PARAMS = {"sessionId": "rscripts-cli", "device": "computer", "country": "all"}
DEEP_SORTS = ("top-playing-now", "up-and-coming", "top-trending")

RS_PAGES = 6        # rscripts: 16 rows/page, primary query
RS_ALT_PAGES = 3    # rscripts: per alternate-name query
SB_PAGES = 5        # scriptblox fetch-by-place: 20 rows/page
CACHE_VERSION = 2
DEFAULT_CACHE = Path(os.environ.get("RS_CACHE_DIR")
                     or Path.home() / ".cache" / "rscripts-cli") / "gaps.json"

_rbx = requests.Session()
_rbx.headers["User-Agent"] = "Mozilla/5.0"


# ---------------------------------------------------------------------------
# Candidate games
# ---------------------------------------------------------------------------

def _add_game(games: dict, g: dict, sort: str) -> None:
    uid = g.get("universeId")
    if not uid or not g.get("rootPlaceId"):
        return
    e = games.setdefault(uid, {
        "universeId": uid, "rootPlaceId": g["rootPlaceId"],
        "name": g.get("name") or "", "playing": 0, "sorts": [],
    })
    e["playing"] = max(e["playing"], g.get("playerCount") or 0)
    if sort not in e["sorts"]:
        e["sorts"].append(sort)


def roblox_games(deep_pages: int = 8, log: Callable[[str], None] = lambda m: None) -> list[dict]:
    """Every game on the explore page, plus deeper pages of DEEP_SORTS.
    Sorted by current player count, descending."""
    games: dict = {}
    tok = None
    for _ in range(20):
        p = dict(EXPLORE_PARAMS, **({"sortsPageToken": tok} if tok else {}))
        d = _rbx.get(f"{EXPLORE}/get-sorts", params=p, timeout=20).json()
        for s in d.get("sorts") or []:
            if s.get("contentType") == "Games":
                for g in s.get("games") or []:
                    _add_game(games, g, s["sortId"])
        tok = d.get("nextSortsPageToken")
        if not tok:
            break
    for sid in DEEP_SORTS:
        tok = None
        for _ in range(deep_pages):
            p = dict(EXPLORE_PARAMS, sortId=sid, **({"pageToken": tok} if tok else {}))
            r = _rbx.get(f"{EXPLORE}/get-sort-content", params=p, timeout=20)
            if r.status_code != 200:
                log(f"explore {sid}: HTTP {r.status_code}")
                break
            d = r.json()
            for g in d.get("games") or []:
                _add_game(games, g, sid)
            tok = d.get("nextPageToken")
            if not tok:
                break
            time.sleep(0.3)
    log(f"{len(games)} candidate games from explore")
    return sorted(games.values(), key=lambda e: -e["playing"])


def games_for_places(place_ids: list[int]) -> list[dict]:
    """Resolve explicit place ids to game entries (name, live player count).
    Uses the root place of each id's universe, since that's what script sites link."""
    out: dict = {}
    for pid in place_ids:
        for i in range(4):
            r = _rbx.get(f"https://apis.roblox.com/universes/v1/places/{pid}/universe", timeout=20)
            if r.status_code != 429:
                break
            time.sleep(3 + 3 * i)  # rate-limited: retry, never treat as "not a game"
        uid = r.json().get("universeId") if r.ok else None
        if uid:
            out[uid] = None
        else:
            raise ValueError(f"place {pid}: no universe (HTTP {r.status_code})")
    ids = list(out)
    games = []
    for i in range(0, len(ids), 40):
        chunk = ",".join(map(str, ids[i:i + 40]))
        d = _rbx.get("https://games.roblox.com/v1/games", params={"universeIds": chunk}, timeout=20).json()
        for g in d.get("data") or []:
            games.append({"universeId": g["id"], "rootPlaceId": g["rootPlaceId"],
                          "name": g.get("name") or "", "playing": g.get("playing") or 0,
                          "sorts": ["explicit"], **_genre_fields(g)})
    return games


# ---------------------------------------------------------------------------
# Genres
# ---------------------------------------------------------------------------

GENRE_KEYS = ("genre", "genre_l1", "genre_l2")  # legacy (RPG, FPS), L1 (Shooter), L2 (subgenre)
GENRE_TTL = 7 * 86400


def _genre_fields(g: dict) -> dict:
    return {k: (g.get(k) or "") for k in GENRE_KEYS}


def fill_genres(games: list[dict], cache_path: Path = None,
                log: Callable[[str], None] = lambda m: None) -> None:
    """Attach genre/genre_l1/genre_l2 to each game (cached for a week)."""
    cache_path = cache_path or DEFAULT_CACHE
    data = _load(cache_path)
    gc = data.setdefault("genres", {})
    now = time.time()
    missing = [g["universeId"] for g in games
               if now - gc.get(str(g["universeId"]), {}).get("at", 0) > GENRE_TTL]
    for i in range(0, len(missing), 40):
        chunk = ",".join(map(str, missing[i:i + 40]))
        r = _retry(lambda: _rbx.get("https://games.roblox.com/v1/games",
                                    params={"universeIds": chunk}, timeout=20))
        for g in (r.json().get("data") or []) if r.ok else []:
            gc[str(g["id"])] = dict(_genre_fields(g), at=now)
        time.sleep(0.3)
    if missing:
        log(f"genres: looked up {len(missing)} games")
        _save(cache_path, data)
    for g in games:
        g.update({k: v for k, v in gc.get(str(g["universeId"]), {}).items() if k in GENRE_KEYS})


# Shorthand -> genre substrings. Legacy genre is "All" for most games, so
# "fps" alone would only hit the few still tagged FPS.
GENRE_ALIASES = {
    "fps": ["fps", "shooter"],
    "rp": ["roleplay"],
    "td": ["tower defense"],
    "pvp": ["battlegrounds", "fighting", "shooter"],
    "obby": ["obby"],
    "sim": ["simulat"],
}


def genre_match(game: dict, terms: list[str]) -> bool:
    """True if any term (or its alias expansion) is a case-insensitive
    substring of any genre level: "rpg", "roleplay", "fps", "tycoon" all work."""
    hay = " | ".join(game.get(k) or "" for k in GENRE_KEYS).lower()
    subs = [x for t in terms for x in GENRE_ALIASES.get(t.lower(), [t.lower()])]
    return any(x in hay for x in subs)


def genre_label(game: dict) -> str:
    l1, l2 = game.get("genre_l1") or "", game.get("genre_l2") or ""
    return f"{l1} / {l2}" if l1 and l2 else l1 or l2 or game.get("genre") or "-"


# ---------------------------------------------------------------------------
# Counting
# ---------------------------------------------------------------------------

def search_query(name: str) -> str:
    """Game title -> search query: drop [UPD]/(x2) tags, emoji and decoration."""
    n = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", name)
    n = n.encode("ascii", "ignore").decode()
    n = re.sub(r"[^A-Za-z0-9'&!+ .-]", " ", n)
    return re.sub(r"\s+", " ", n).strip(" .-!") or name


def _retry(fn, tries: int = 4):
    err = None
    for i in range(tries):
        try:
            return fn()
        except Exception as e:  # rate limits, timeouts
            err = e
            time.sleep(2 + 3 * i)
    raise err


def _rs_rows(queries: list[str], pid: int) -> tuple[list[dict], bool]:
    """rscripts has no place filter: search each name, keep rows linked to pid.
    Search is fuzzy (descriptions match too), so a capped primary query means
    the real total is higher."""
    rows: dict = {}
    capped = False
    for qi, q in enumerate(queries):
        limit = RS_PAGES if qi == 0 else RS_ALT_PAGES
        for p in range(1, limit + 1):
            d = _retry(lambda: api.get_scripts(page=p, q=q))
            for s in d.get("scripts") or []:
                if str((s.get("game") or {}).get("placeId")) == str(pid):
                    rows[s.get("_id")] = {
                        "id": s.get("_id"), "title": s.get("title", ""),
                        "createdAt": s.get("createdAt", ""), "views": s.get("views") or 0,
                        "key": bool(s.get("keySystem")), "paid": bool(s.get("paid"))}
            if p >= ((d.get("info") or {}).get("maxPages") or 1):
                break
            if qi == 0 and p == limit:
                capped = True
            time.sleep(0.25)
    return list(rows.values()), capped


def _sb_rows(pid: int) -> tuple[list[dict], bool, set[str]]:
    """scriptblox filters by place exactly. Also returns the game names the
    rows were posted under — older titles that rscripts search needs."""
    rows, names, capped = [], set(), False
    for p in range(1, SB_PAGES + 1):
        d = _retry(lambda: scriptblox.fetch_by_place(pid, page=p))
        res = d.get("result") or {}
        for s in res.get("scripts") or []:
            g = s.get("game") or {}
            if str(g.get("gameId")) == str(pid):  # fetch also mixes in universals
                names.add(g.get("name") or "")
                rows.append({"id": s.get("_id"), "title": s.get("title", ""),
                             "createdAt": s.get("createdAt", ""), "views": s.get("views") or 0,
                             "key": bool(s.get("key")), "patched": bool(s.get("isPatched"))})
        if p >= (res.get("totalPages") or 1):
            break
        capped = p == SB_PAGES
        time.sleep(0.4)
    return rows, capped, names


def _alt_queries(name: str, sb_names: set[str]) -> list[str]:
    """Primary query first, then names the game was scripted under and the
    title's segments ("Vanguards: 2nd Anniversary" -> "Vanguards")."""
    out = [search_query(name)]
    cands = sorted(sb_names) + re.split(r"[:|\-]", name)
    for c in cands:
        q = search_query(c)
        if len(q) >= 4 and q.lower() not in (o.lower() for o in out):
            out.append(q)
    return out[:4]


def count_game(game: dict) -> dict:
    """Fetch the matching script rows for one game from both sources."""
    pid = game["rootPlaceId"]
    entry = {"rootPlaceId": pid, "counted_at": time.time()}
    sb_names: set[str] = set()
    try:
        entry["sb"], entry["sb_capped"], sb_names = _sb_rows(pid)
    except Exception as e:
        entry["sb_err"] = str(e)[:160]
    entry["queries"] = _alt_queries(game["name"], sb_names)
    try:
        entry["rs"], entry["rs_capped"] = _rs_rows(entry["queries"], pid)
    except Exception as e:
        entry["rs_err"] = str(e)[:160]
    return entry


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

def _load(path: Path) -> dict:
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        return d if d.get("version") == CACHE_VERSION else {"version": CACHE_VERSION}
    except (OSError, ValueError):
        return {"version": CACHE_VERSION}


def _save(path: Path, data: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    tmp.replace(path)


# ---------------------------------------------------------------------------
# Scan + score
# ---------------------------------------------------------------------------

def known_ids(paths: list[str]) -> set[str]:
    """Place ids already worked on. A file contributes every 8+ digit number
    in its text; a directory contributes the numbers in its entries' names."""
    ids: set[str] = set()
    for p in map(Path, paths):
        text = (" ".join(c.name for c in p.iterdir()) if p.is_dir()
                else p.read_text(encoding="utf-8", errors="ignore"))
        ids.update(re.findall(r"\b\d{8,17}\b", text))
    return ids


def _ts(s: str) -> datetime | None:
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def score(game: dict, entry: dict, days: int) -> dict:
    """Merge a game with its cached rows; recompute window-dependent stats."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rs, sb = entry.get("rs") or [], entry.get("sb") or []
    recent = lambda rows: sum(1 for r in rows if (t := _ts(r["createdAt"])) and t >= cutoff)
    newest = max((t for r in rs + sb if (t := _ts(r["createdAt"]))), default=None)
    row = dict(game)
    row.update({
        "queries": entry.get("queries"),
        "rs_total": len(rs), "rs_recent": recent(rs), "rs_capped": entry.get("rs_capped", False),
        "sb_total": len(sb), "sb_recent": recent(sb), "sb_capped": entry.get("sb_capped", False),
        "sb_alive": sum(1 for r in sb if not r.get("patched")),
        "keyless": sum(1 for r in rs + sb if not r.get("key")),
        "views": sum(r["views"] for r in rs + sb),
        "newest": newest.date().isoformat() if newest else None,
        "errors": [entry[k] for k in ("rs_err", "sb_err") if k in entry],
    })
    row["recent"] = row["rs_recent"] + row["sb_recent"]
    row["total"] = row["rs_total"] + row["sb_total"]
    row["score"] = round(game["playing"] / (row["recent"] + 1))  # players per recent script
    return row


@dataclass
class GapReport:
    rows: list[dict] = field(default_factory=list)
    fetched: int = 0
    cached: int = 0
    errors: int = 0


def scan(
    games: list[dict],
    days: int = 60,
    cache_path: Path = DEFAULT_CACHE,
    ttl_hours: float = 12,
    refresh: bool = False,
    workers: int = 4,
    log: Callable[[str], None] = lambda m: None,
) -> GapReport:
    """Count scripts for every game (cache first), return scored rows."""
    data = _load(cache_path)
    cache = data.setdefault("games", {})
    fresh = lambda e: (not refresh and e and "rs_err" not in e and "sb_err" not in e
                       and time.time() - e.get("counted_at", 0) < ttl_hours * 3600)
    todo = [g for g in games if not fresh(cache.get(str(g["rootPlaceId"])))]
    report = GapReport(cached=len(games) - len(todo))
    log(f"{len(games)} games: {report.cached} cached, {len(todo)} to fetch")

    lock = threading.Lock()

    def work(g: dict) -> None:
        e = count_game(g)
        with lock:
            cache[str(g["rootPlaceId"])] = e
            report.fetched += 1
            if report.fetched % 25 == 0:
                log(f"  {report.fetched}/{len(todo)} counted")
                _save(cache_path, data)  # survive an interrupt

    if todo:
        with ThreadPoolExecutor(max(1, workers)) as ex:
            list(ex.map(work, todo))
        _save(cache_path, data)

    for g in games:
        row = score(g, cache.get(str(g["rootPlaceId"]), {}), days)
        report.errors += bool(row["errors"])
        report.rows.append(row)
    return report
