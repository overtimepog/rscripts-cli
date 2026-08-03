"""MCP server exposing script browsing from rscripts.net and scriptblox.com."""
import html
import re
from typing import Annotated

from mcp.server.fastmcp import FastMCP

from . import api
from . import scriptblox

mcp = FastMCP("rscripts", instructions="Browse and fetch Roblox scripts from rscripts.net and scriptblox.com")


def _clean_description(raw: str) -> str:
    text = html.unescape(raw).strip()
    text = re.sub(r"\s*[•·]\s*", "\n• ", text)
    return text


def _format_script(script: dict) -> dict:
    game = script.get("game") or {}
    return {
        "id": script.get("_id", ""),
        "title": script.get("title", ""),
        "creator": api.resolve_creator(script),
        "game": game.get("name", "") if isinstance(game, dict) else "",
        "views": script.get("views", 0),
        "likes": script.get("likes", 0),
        "dislikes": script.get("dislikes", 0),
        "description": _clean_description(script.get("description", "")),
        "key_system": script.get("keySystem", False),
        "paid": script.get("paid", False),
        "mobile_ready": script.get("mobileReady", False),
        "private": script.get("private", False),
        "created_at": script.get("createdAt", "")[:10],
        "updated_at": script.get("lastUpdated", "")[:10],
        "raw_url": script.get("rawScript", ""),
        "inline_script": script.get("_sbx_script", ""),
        "tested_executors": [
            e.get("title", e.get("name", str(e))) if isinstance(e, dict) else str(e)
            for e in (script.get("testedExecutors") or [])
        ],
    }


def _sbx_to_rs(s: dict) -> dict:
    """Normalise a scriptblox script dict to the rscripts schema."""
    game = s.get("game") or {}
    return {
        "_id": s.get("_id", ""),
        "title": s.get("title", ""),
        "views": s.get("views", 0),
        "likes": s.get("likeCount", 0),
        "dislikes": s.get("dislikeCount", 0),
        "keySystem": s.get("key", False),
        "paid": s.get("scriptType") == "paid",
        "mobileReady": False,
        "description": s.get("features", ""),
        "game": {"name": game.get("name", "Unknown")} if game else None,
        "createdAt": s.get("createdAt", ""),
        "lastUpdated": s.get("lastBump", s.get("createdAt", "")),
        "rawScript": None,
        "_sbx_script": s.get("script", ""),
        "_sbx_universal": s.get("isUniversal", False),
        "_sbx_patched": s.get("isPatched", False),
        "_sbx_verified": s.get("verified", False),
    }


@mcp.tool()
def search_scripts(
    query: str | None = None,
    page: int = 1,
    order_by: Annotated[str, "Sort field (rscripts only): date, views, likes, id"] = "date",
    sort: Annotated[str, "Sort direction (rscripts only): asc or desc"] = "desc",
    no_key_system: bool = False,
    mobile_only: bool = False,
    free_only: bool = False,
    unpatched_only: bool = False,
    verified_only: bool = False,
    username: str | None = None,
    source: Annotated[str, "Source: 'rscripts' (default) or 'scriptblox'"] = "rscripts",
) -> dict:
    """Search or list scripts. Returns paginated results with script metadata."""
    if source == "scriptblox":
        raw = scriptblox.search_scripts(
            q=query, page=page,
            mode="free" if free_only else None,
            no_key=no_key_system, unpatched=unpatched_only,
        )
        result = raw.get("result", {})
        scripts = [_format_script(_sbx_to_rs(s)) for s in result.get("scripts", [])]
        return {
            "source": "scriptblox",
            "scripts": scripts,
            "page": page,
            "max_pages": result.get("totalPages", 1),
            "total": len(scripts),
        }

    data = api.get_scripts(
        page=page, q=query, order_by=order_by, sort=sort,
        no_key_system=no_key_system, mobile_only=mobile_only, not_paid=free_only,
        unpatched=unpatched_only, verified_only=verified_only, username=username,
    )
    scripts = [_format_script(s) for s in data.get("scripts", [])]
    info = data.get("info", {})
    return {
        "source": "rscripts",
        "scripts": scripts,
        "page": info.get("currentPage", page),
        "max_pages": info.get("maxPages", 1),
        "total": len(scripts),
    }


@mcp.tool()
def get_script(script_id: str,
               source: Annotated[str, "Source: 'rscripts' (default) or 'scriptblox'"] = "rscripts") -> dict:
    """Get detailed info for a single script by its ID."""
    if source == "scriptblox":
        data = scriptblox.get_script(script_id)
        s = data.get("script")
        if isinstance(s, list):
            s = s[0] if s else None
        if not s:
            return {"error": "Script not found"}
        return _format_script(_sbx_to_rs(s))

    data = api.get_script(script_id)
    if "error" in data:
        return {"error": data["error"]}
    script = data.get("script")
    if isinstance(script, list):
        script = script[0] if script else None
    if not script:
        return {"error": "Script not found"}
    return _format_script(script)


@mcp.tool()
def get_trending(source: Annotated[str, "Source: 'rscripts' (default) or 'scriptblox'"] = "rscripts") -> list[dict]:
    """Get the top trending Roblox scripts."""
    if source == "scriptblox":
        data = scriptblox.get_trending()
        results = []
        for rank, s in enumerate(data.get("result", {}).get("scripts", []), 1):
            ns = _sbx_to_rs(s)
            results.append({
                "rank": rank,
                "id": ns.get("_id", ""),
                "title": ns.get("title", ""),
                "views": ns.get("views", 0),
            })
        return results

    data = api.get_trending()
    results = []
    for rank, entry in enumerate(data.get("success", []), 1):
        script_info = entry.get("script") or {}
        user_info = entry.get("user") or {}
        results.append({
            "rank": rank,
            "id": entry.get("_id", ""),
            "title": script_info.get("title", ""),
            "creator": user_info.get("username", "Unknown"),
            "views_48h": entry.get("views", 0),
        })
    return results


@mcp.tool()
def get_raw_script(script_id: str,
                   source: Annotated[str, "Source: 'rscripts' (default) or 'scriptblox'"] = "rscripts") -> str:
    """Fetch the raw Lua source code of a script by its ID."""
    if source == "scriptblox":
        data = scriptblox.get_script(script_id)
        s = data.get("script")
        if isinstance(s, list):
            s = s[0] if s else None
        if not s:
            raise ValueError("Script not found")
        code = s.get("script", "")
        if not code:
            raise ValueError("No inline script available for this script")
        return code

    data = api.get_script(script_id)
    if "error" in data:
        raise ValueError(data["error"])
    script = data.get("script")
    if isinstance(script, list):
        script = script[0] if script else None
    if not script:
        raise ValueError("Script not found")
    raw_url = script.get("rawScript")
    if not raw_url:
        raise ValueError("No raw script URL available for this script")
    return api.fetch_raw_script(raw_url)


def main():
    mcp.run()


if __name__ == "__main__":
    main()
