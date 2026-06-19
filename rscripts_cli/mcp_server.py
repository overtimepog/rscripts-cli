"""MCP server for rscripts.net — exposes script browsing as MCP tools."""
import html
import re
from typing import Annotated

from mcp.server.fastmcp import FastMCP

from . import api

mcp = FastMCP("rscripts", description="Browse and fetch Roblox scripts from rscripts.net")


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
        "tested_executors": [
            e.get("title", e.get("name", str(e))) if isinstance(e, dict) else str(e)
            for e in (script.get("testedExecutors") or [])
        ],
    }


@mcp.tool()
def search_scripts(
    query: str | None = None,
    page: int = 1,
    order_by: Annotated[str, "Sort field: date, views, likes, id"] = "date",
    sort: Annotated[str, "Sort direction: asc or desc"] = "desc",
    no_key_system: bool = False,
    mobile_only: bool = False,
    free_only: bool = False,
    unpatched_only: bool = False,
    verified_only: bool = False,
    username: str | None = None,
) -> dict:
    """Search or list scripts on rscripts.net. Returns paginated results with script metadata."""
    data = api.get_scripts(
        page=page,
        q=query,
        order_by=order_by,
        sort=sort,
        no_key_system=no_key_system,
        mobile_only=mobile_only,
        not_paid=free_only,
        unpatched=unpatched_only,
        verified_only=verified_only,
        username=username,
    )
    scripts = [_format_script(s) for s in data.get("scripts", [])]
    info = data.get("info", {})
    return {
        "scripts": scripts,
        "page": info.get("currentPage", page),
        "max_pages": info.get("maxPages", 1),
        "total": len(scripts),
    }


@mcp.tool()
def get_script(script_id: str) -> dict:
    """Get detailed info for a single script by its 24-character hex ID."""
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
def get_trending() -> list[dict]:
    """Get the top trending Roblox scripts from the last 48 hours."""
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
def get_raw_script(script_id: str) -> str:
    """Fetch the raw Lua source code of a script by its 24-character hex ID."""
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
