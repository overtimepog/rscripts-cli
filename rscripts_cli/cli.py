"""Click CLI for browsing Roblox script sources from the terminal.

Supports two sources:
  rscripts   — rscripts.net (default)
  scriptblox — scriptblox.com
"""
import html
import re
import sys
import textwrap

import click
from rich.console import Console
from rich.markup import escape
from rich.table import Table
from rich import box

from . import api
from . import scriptblox
from . import hunter

# Force UTF-8 on Windows to handle emoji in script titles
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

console = Console()

SOURCES = ["rscripts", "scriptblox"]


# ---------------------------------------------------------------------------
# Source normalisation
# ---------------------------------------------------------------------------

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
        "rawScript": None,  # scriptblox embeds Lua inline, no URL
        # scriptblox-specific extras surfaced as pseudo-fields
        "_sbx_script": s.get("script", ""),
        "_sbx_universal": s.get("isUniversal", False),
        "_sbx_patched": s.get("isPatched", False),
        "_sbx_verified": s.get("verified", False),
    }


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _slug_cli(text):  # slug for out-dir naming
    return re.sub(r'[^A-Za-z0-9._-]+', '_', text).strip('_') or "all"


def _fmt_script_row(script: dict) -> tuple[str, str, str, str, str]:
    title = escape(script.get("title", "")[:60])
    creator = escape(api.resolve_creator(script))
    views = str(script.get("views", 0))
    likes = str(script.get("likes", 0))
    tags = []
    if script.get("keySystem"):
        tags.append("[red]KEY[/red]")
    if script.get("paid"):
        tags.append("[yellow]PAID[/yellow]")
    if script.get("mobileReady"):
        tags.append("[green]MOBILE[/green]")
    if script.get("_sbx_universal"):
        tags.append("[blue]UNIV[/blue]")
    if script.get("_sbx_verified"):
        tags.append("[green]VRF[/green]")
    if script.get("_sbx_patched"):
        tags.append("[red]PTCH[/red]")
    if not tags:
        tags.append("[dim]free[/dim]")
    return title, creator, views, likes, " ".join(tags)


def _clean_description(raw: str, max_chars: int | None = None) -> str:
    """Normalize a script description for terminal display."""
    import re
    text = html.unescape(raw).strip()
    text = re.sub(r"\s*[•·]\s*", "\n• ", text)
    if max_chars and len(text) > max_chars:
        text = text[:max_chars].rstrip() + "…"
    return text


def _print_scripts_table(
    scripts: list[dict],
    title: str = "Scripts",
    show_desc: bool = False,
) -> None:
    if show_desc:
        _print_scripts_with_desc(scripts, title)
        return

    table = Table(
        title=title,
        box=box.SIMPLE_HEAVY,
        show_lines=False,
        highlight=True,
        expand=False,
    )
    table.add_column("ID", style="dim", no_wrap=True, width=26)
    table.add_column("Title", style="cyan", max_width=52)
    table.add_column("Creator", style="yellow", max_width=20)
    table.add_column("Views", justify="right", style="white")
    table.add_column("Likes", justify="right", style="green")
    table.add_column("Tags", no_wrap=True)

    for s in scripts:
        row = _fmt_script_row(s)
        table.add_row(s.get("_id", ""), *row)

    console.print(table)


def _print_scripts_with_desc(scripts: list[dict], title: str) -> None:
    console.print()
    console.rule(f"[bold]{escape(title)}[/bold]")
    width = min(100, console.width - 6)

    for s in scripts:
        sid = s.get("_id", "")
        script_title = escape(s.get("title", ""))
        creator = escape(api.resolve_creator(s))
        views = s.get("views", 0)
        likes = s.get("likes", 0)

        tags = []
        if s.get("keySystem"):
            tags.append("[red]KEY[/red]")
        if s.get("paid"):
            tags.append("[yellow]PAID[/yellow]")
        if s.get("mobileReady"):
            tags.append("[green]MOBILE[/green]")
        if s.get("_sbx_universal"):
            tags.append("[blue]UNIV[/blue]")
        if s.get("_sbx_verified"):
            tags.append("[green]VRF[/green]")
        tag_str = " ".join(tags) if tags else "[dim]free[/dim]"

        console.print(f"  [bold cyan]{script_title}[/bold cyan]  {tag_str}")
        console.print(f"  [dim]{sid}[/dim]  by [yellow]{creator}[/yellow]"
                      f"  • views: {views:,}  likes: {likes:,}")

        raw_desc = s.get("description", "").strip()
        if raw_desc:
            desc = _clean_description(raw_desc, max_chars=300)
            console.print()
            for line in desc.split("\n"):
                line = line.strip()
                if not line:
                    continue
                if len(line) > width:
                    line = textwrap.fill(line, width=width)
                console.print(f"    {escape(line)}")

        console.print()


def _print_script_detail(script: dict) -> None:
    sid = script.get("_id", "")
    title = escape(script.get("title", "Untitled"))
    creator = escape(api.resolve_creator(script))
    description = _clean_description(script.get("description", ""))
    views = script.get("views", 0)
    likes = script.get("likes", 0)
    dislikes = script.get("dislikes", 0)
    game = script.get("game") or {}
    game_name = escape(game.get("name", "Unknown") if game else "Unknown")
    created = script.get("createdAt", "")[:10]
    updated = script.get("lastUpdated", "")[:10]

    flags = []
    if script.get("keySystem"):
        flags.append("[red]Key System[/red]")
    if script.get("paid"):
        flags.append("[yellow]Paid[/yellow]")
    if script.get("mobileReady"):
        flags.append("[green]Mobile Ready[/green]")
    if script.get("private"):
        flags.append("[dim]Private[/dim]")
    if script.get("_sbx_universal"):
        flags.append("[blue]Universal[/blue]")
    if script.get("_sbx_verified"):
        flags.append("[green]Verified[/green]")
    if script.get("_sbx_patched"):
        flags.append("[red]Patched[/red]")

    console.print()
    console.print(f"  [bold cyan]{title}[/bold cyan]  [dim]({sid})[/dim]")
    console.print(f"  Creator : [yellow]{creator}[/yellow]")
    console.print(f"  Game    : {game_name}")
    console.print(f"  Views   : {views:,}  |  [green]Likes: {likes:,}[/green]  |  [red]Dislikes: {dislikes:,}[/red]")
    console.print(f"  Created : {created}  |  Updated: {updated}")
    if flags:
        console.print(f"  Tags    : {' '.join(flags)}")

    if description:
        console.print()
        width = min(100, console.width - 6)
        for para in description.split("\n"):
            para = para.strip()
            if not para:
                continue
            if len(para) > width:
                para = textwrap.fill(para, width=width)
            console.print(f"  {escape(para)}")

    console.print()

    executors = script.get("testedExecutors") or []
    if executors:
        names = [e.get("title", e.get("name", "?")) if isinstance(e, dict) else str(e) for e in executors]
        console.print(f"  Tested executors: [dim]{escape(', '.join(names))}[/dim]")
        console.print()


# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------


@click.group()
@click.version_option(version="0.3.0", prog_name="rs")
def cli():
    """rs — browse Roblox scripts from the terminal.

    \b
    Commands:
      scripts             Browse / search scripts
      script  <id>        View a script's details
      trending            Show trending scripts
      raw     <id>        Print the raw Lua code of a script

    \b
    Use --source rscripts|scriptblox on any command to switch sources
    (default: rscripts).
    """


# ---------------------------------------------------------------------------
# scripts
# ---------------------------------------------------------------------------


@cli.command("scripts")
@click.option("--source", "-s", type=click.Choice(SOURCES), default="rscripts",
              show_default=True, help="Script source")
@click.option("--page", "-p", default=1, show_default=True, help="Page number")
@click.option("--search", "-q", default=None, help="Search query")
@click.option("--order-by", default="date", show_default=True,
              type=click.Choice(["date", "views", "likes", "id"], case_sensitive=False),
              help="Sort field (rscripts only)")
@click.option("--sort", default="desc", show_default=True,
              type=click.Choice(["asc", "desc"], case_sensitive=False),
              help="Sort direction (rscripts only)")
@click.option("--no-key", is_flag=True, help="Exclude key-system scripts")
@click.option("--mobile", is_flag=True, help="Mobile-ready scripts only (rscripts only)")
@click.option("--free", is_flag=True, help="Free scripts only")
@click.option("--unpatched", is_flag=True, help="Unpatched scripts only")
@click.option("--verified", is_flag=True, help="Verified creators only (rscripts only)")
@click.option("--user", "-u", default=None, help="Filter by creator username (rscripts only)")
@click.option("--desc", "-d", is_flag=True, help="Show script descriptions")
def scripts_cmd(source, page, search, order_by, sort, no_key, mobile, free, unpatched, verified, user, desc):
    """Browse or search scripts."""
    console.print(f"[dim]Fetching scripts from {source} (page {page})…[/dim]")
    try:
        if source == "scriptblox":
            raw = scriptblox.search_scripts(
                q=search, page=page,
                mode="free" if free else None,
                no_key=no_key, unpatched=unpatched,
            )
            result = raw.get("result", {})
            script_list = [_sbx_to_rs(s) for s in result.get("scripts", [])]
            current = page
            max_pages = result.get("totalPages", "?")
        else:
            data = api.get_scripts(
                page=page, q=search, order_by=order_by, sort=sort,
                no_key_system=no_key, mobile_only=mobile, not_paid=free,
                unpatched=unpatched, verified_only=verified, username=user,
            )
            script_list = data.get("scripts", [])
            info = data.get("info", {})
            current = info.get("currentPage", page)
            max_pages = info.get("maxPages", "?")
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        return

    if not script_list:
        console.print("[yellow]No scripts found.[/yellow]")
        return

    title = f"[{source}] Scripts — page {current}/{max_pages}"
    if search:
        title += f' — search: "{search}"'
    _print_scripts_table(script_list, title=title, show_desc=desc)
    console.print(f"  [dim]Use --page {current + 1} to see the next page.[/dim]\n")


# ---------------------------------------------------------------------------
# script
# ---------------------------------------------------------------------------


@cli.command("script")
@click.option("--source", "-s", type=click.Choice(SOURCES), default="rscripts",
              show_default=True, help="Script source")
@click.argument("script_id")
@click.option("--raw", "-r", is_flag=True, help="Also print the raw Lua code")
def script_cmd(source, script_id, raw):
    """View details for a specific script by ID."""
    console.print(f"[dim]Fetching script {script_id} from {source}…[/dim]")
    try:
        if source == "scriptblox":
            data = scriptblox.get_script(script_id)
        else:
            data = api.get_script(script_id)
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        return

    if "error" in data:
        console.print(f"[red]API error:[/red] {data['error']}")
        return

    script = data.get("script")
    if isinstance(script, list):
        script = script[0] if script else None
    if not script:
        console.print("[yellow]Script not found.[/yellow]")
        return

    if source == "scriptblox":
        script = _sbx_to_rs(script)

    _print_script_detail(script)

    if raw:
        if source == "scriptblox":
            code = script.get("_sbx_script", "")
            if not code:
                console.print("[yellow]No inline script available.[/yellow]")
                return
        else:
            raw_url = script.get("rawScript")
            if not raw_url:
                console.print("[yellow]No raw script URL available.[/yellow]")
                return
            console.print(f"[dim]Fetching raw Lua from {raw_url}…[/dim]")
            try:
                code = api.fetch_raw_script(raw_url)
            except Exception as e:
                console.print(f"[red]Error fetching raw script:[/red] {e}")
                return
        console.rule("Lua Source")
        console.print(code)
        console.rule()


# ---------------------------------------------------------------------------
# trending
# ---------------------------------------------------------------------------


@cli.command("trending")
@click.option("--source", "-s", type=click.Choice(SOURCES), default="rscripts",
              show_default=True, help="Script source")
def trending_cmd(source):
    """Show trending scripts."""
    console.print(f"[dim]Fetching trending scripts from {source}…[/dim]")
    try:
        if source == "scriptblox":
            data = scriptblox.get_trending()
            entries = data.get("result", {}).get("scripts", [])
            # Normalise to the row shape the table expects
            rows = []
            for rank, s in enumerate(entries, 1):
                ns = _sbx_to_rs(s)
                rows.append((rank, ns))
        else:
            data = api.get_trending()
            entries = data.get("success", [])
            rows = []
            for rank, entry in enumerate(entries, 1):
                si = entry.get("script") or {}
                ui = entry.get("user") or {}
                rows.append((rank, {
                    "title": si.get("title", ""),
                    "creator": ui.get("username", "Unknown"),
                    "views": entry.get("views", 0),
                    "raw": si.get("rawScript", ""),
                    "id": entry.get("_id", ""),
                }))
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        return

    if not rows:
        console.print("[yellow]No trending scripts found.[/yellow]")
        return

    table = Table(
        title=f"[{source}] Trending Scripts",
        box=box.SIMPLE_HEAVY,
        show_lines=False,
        highlight=True,
    )
    table.add_column("#", style="dim", width=3, justify="right")
    table.add_column("Title", style="cyan", max_width=40)
    table.add_column("Creator", style="yellow", max_width=20)
    table.add_column("Views", justify="right", style="white")

    for rank, row in rows:
        if source == "scriptblox":
            title = escape(row.get("title", "")[:40])
            creator = escape(api.resolve_creator(row))
            views = str(row.get("views", 0))
        else:
            title = escape(row.get("title", "")[:40])
            creator = escape(row.get("creator", "Unknown"))
            views = str(row.get("views", 0))
        table.add_row(str(rank), title, creator, views)

    console.print(table)
    if source == "rscripts":
        console.print(
            "  [dim]The rscripts trending endpoint doesn't expose a script ID — "
            "use `rs scripts --search` to find an ID for `rs script`/`rs raw`.[/dim]\n"
        )
    else:
        console.print(
            "  [dim]Use `rs script -s scriptblox <id>` for details, "
            "`rs raw -s scriptblox <id>` for the Lua code.[/dim]\n"
        )


# ---------------------------------------------------------------------------
# hunt
# ---------------------------------------------------------------------------


@cli.command("hunt")
@click.option("--source", "-s", "sources", type=click.Choice(SOURCES),
              multiple=True, show_default=True, default=("rscripts",),
              help="Sources to scan (repeatable)")
@click.option("--query", "-q", "queries", multiple=True, default=(),
              help="Search query (repeatable; omit to browse popular pages)")
@click.option("--pages", "-p", default=3, show_default=True,
              help="Pages to scan per source/query")
@click.option("--order-by", default="views", show_default=True,
              type=click.Choice(["date", "views", "likes"], case_sensitive=False),
              help="Browse sort field (rscripts only)")
@click.option("--obf", "obf_filter", default=None,
              help="Only save scripts from this obfuscator (e.g. Luraph); "
                   "default saves all obfuscated")
@click.option("--out", "-o", "out_dir", default=None,
              help="Output dir [default: ./hunt-<obf|all>]")
def hunt_cmd(sources, queries, pages, order_by, obf_filter, out_dir):
    """Hunt obfuscated scripts; follow loader URLs to the real payload.

    \\b
    Examples:
      rs hunt -s rscripts -s scriptblox -q "hub" --obf Luraph -p 5
      rs hunt --obf Luraph --out luraph-hits
      rs hunt -q "infected lands" -q "infectedlands"
    """
    out_dir = out_dir or f"hunt-{_slug_cli(obf_filter) if obf_filter else 'all'}"
    console.print(f"[dim]Hunting {', '.join(sources)} -> {out_dir}/[/dim]")
    report = hunter.hunt(
        sources=list(sources), queries=list(queries), pages=pages,
        out_dir=out_dir, obf_filter=obf_filter, order_by=order_by.lower(),
        log=lambda msg: console.print(f"[dim]{escape(msg)}[/dim]"),
    )
    table = Table(title=f"Hunt results — {out_dir}/", box=box.SIMPLE_HEAVY)
    table.add_column("Obfuscator", style="cyan", no_wrap=True)
    table.add_column("Title", max_width=44)
    table.add_column("Size", justify="right")
    table.add_column("Provenance", max_width=48, style="dim")
    for r in report.rows:
        label = r["obf"] + (f" {r['ver']}" if r["ver"] else "")
        table.add_row(label, escape(r["title"][:44]), f"{r['size']:,}",
                      escape(r["provenance"]))
    console.print(table)
    console.print(
        f"  {len(report.rows)} saved, {report.fetched} payloads fetched, "
        f"{report.errors} fetch errors -> [cyan]{out_dir}/[/cyan]\n")


# ---------------------------------------------------------------------------
# raw
# ---------------------------------------------------------------------------


@cli.command("raw")
@click.option("--source", "-s", type=click.Choice(SOURCES), default="rscripts",
              show_default=True, help="Script source")
@click.argument("script_id")
def raw_cmd(source, script_id):
    """Print the raw Lua source code of a script."""
    console.print(f"[dim]Fetching script {script_id} from {source}…[/dim]")
    try:
        if source == "scriptblox":
            data = scriptblox.get_script(script_id)
        else:
            data = api.get_script(script_id)
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        return

    if "error" in data:
        console.print(f"[red]API error:[/red] {data['error']}")
        return

    script = data.get("script")
    if isinstance(script, list):
        script = script[0] if script else None
    if not script:
        console.print("[yellow]Script not found.[/yellow]")
        return

    if source == "scriptblox":
        code = script.get("script", "")
        if not code:
            console.print("[yellow]No inline script available.[/yellow]")
            return
        click.echo(code)
    else:
        raw_url = script.get("rawScript")
        if not raw_url:
            console.print("[yellow]No raw script URL available.[/yellow]")
            return
        console.print(f"[dim]Fetching raw Lua from {raw_url}…[/dim]")
        try:
            code = api.fetch_raw_script(raw_url)
        except Exception as e:
            console.print(f"[red]Error:[/red] {e}")
            return
        click.echo(code)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main():
    cli(prog_name="rs")
