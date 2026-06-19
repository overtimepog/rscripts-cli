"""Click CLI for rscripts.net — browse, search, and view Roblox scripts."""
import html
import sys
import textwrap

import click
from rich.console import Console
from rich.markup import escape
from rich.table import Table
from rich import box

from . import api

# Force UTF-8 on Windows to handle emoji in script titles
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

console = Console()


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

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
    if not tags:
        tags.append("[dim]free[/dim]")
    return title, creator, views, likes, " ".join(tags)


def _clean_description(raw: str, max_chars: int | None = None) -> str:
    """Normalize a script description for terminal display.

    Descriptions from the API often have no newlines; bullet characters (•)
    are used as separators. This splits on them so each feature reads as its
    own line.
    """
    import re
    text = html.unescape(raw).strip()
    # Split on bullet chars used as inline separators
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
@click.version_option(version="0.1.0", prog_name="rs")
def cli():
    """rs — browse rscripts.net from the terminal.

    \b
    Commands:
      scripts             Browse / search scripts
      script  <id>        View a script's details
      trending            Show trending scripts (last 48 h)
      raw     <id>        Print the raw Lua code of a script
    """


# ---------------------------------------------------------------------------
# scripts
# ---------------------------------------------------------------------------


@cli.command("scripts")
@click.option("--page", "-p", default=1, show_default=True, help="Page number")
@click.option("--search", "-q", default=None, help="Search query")
@click.option("--order-by", default="date", show_default=True,
              type=click.Choice(["date", "views", "likes", "id"], case_sensitive=False),
              help="Sort field")
@click.option("--sort", default="desc", show_default=True,
              type=click.Choice(["asc", "desc"], case_sensitive=False),
              help="Sort direction")
@click.option("--no-key", is_flag=True, help="Exclude key-system scripts")
@click.option("--mobile", is_flag=True, help="Mobile-ready scripts only")
@click.option("--free", is_flag=True, help="Free scripts only")
@click.option("--unpatched", is_flag=True, help="Unpatched scripts only")
@click.option("--verified", is_flag=True, help="Verified creators only")
@click.option("--user", "-u", default=None, help="Filter by creator username")
@click.option("--desc", "-d", is_flag=True, help="Show script descriptions")
def scripts_cmd(page, search, order_by, sort, no_key, mobile, free, unpatched, verified, user, desc):
    """Browse or search scripts on rscripts.net."""
    console.print(f"[dim]Fetching scripts (page {page})…[/dim]")
    try:
        data = api.get_scripts(
            page=page,
            q=search,
            order_by=order_by,
            sort=sort,
            no_key_system=no_key,
            mobile_only=mobile,
            not_paid=free,
            unpatched=unpatched,
            verified_only=verified,
            username=user,
        )
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        return

    script_list = data.get("scripts", [])
    info = data.get("info", {})
    current = info.get("currentPage", page)
    max_pages = info.get("maxPages", "?")

    if not script_list:
        console.print("[yellow]No scripts found.[/yellow]")
        return

    title = f"Scripts — page {current}/{max_pages}"
    if search:
        title += f' — search: "{search}"'
    _print_scripts_table(script_list, title=title, show_desc=desc)
    console.print(f"  [dim]Use --page {current + 1} to see the next page.[/dim]\n")


# ---------------------------------------------------------------------------
# script
# ---------------------------------------------------------------------------


@cli.command("script")
@click.argument("script_id")
@click.option("--raw", "-r", is_flag=True, help="Also print the raw Lua code")
def script_cmd(script_id, raw):
    """View details for a specific script by ID."""
    console.print(f"[dim]Fetching script {script_id}…[/dim]")
    try:
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

    _print_script_detail(script)

    if raw:
        raw_url = script.get("rawScript")
        if not raw_url:
            console.print("[yellow]No raw script URL available.[/yellow]")
            return
        console.print("[dim]Fetching raw Lua…[/dim]")
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
def trending_cmd():
    """Show the top trending scripts from the last 48 hours."""
    console.print("[dim]Fetching trending scripts…[/dim]")
    try:
        data = api.get_trending()
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        return

    entries = data.get("success", [])
    if not entries:
        console.print("[yellow]No trending scripts found.[/yellow]")
        return

    table = Table(
        title="Trending Scripts (last 48 h)",
        box=box.SIMPLE_HEAVY,
        show_lines=False,
        highlight=True,
    )
    table.add_column("#", style="dim", width=3, justify="right")
    table.add_column("ID", style="dim", width=26, no_wrap=True)
    table.add_column("Title", style="cyan", max_width=52)
    table.add_column("Creator", style="yellow", max_width=20)
    table.add_column("Views (48h)", justify="right", style="white")

    for rank, entry in enumerate(entries, 1):
        sid = entry.get("_id", "")
        views_48h = str(entry.get("views", 0))
        script_info = entry.get("script") or {}
        title = escape(script_info.get("title", "")[:52])
        user_info = entry.get("user") or {}
        creator = escape(user_info.get("username", "Unknown"))
        table.add_row(str(rank), sid, title, creator, views_48h)

    console.print(table)


# ---------------------------------------------------------------------------
# raw
# ---------------------------------------------------------------------------


@cli.command("raw")
@click.argument("script_id")
def raw_cmd(script_id):
    """Print the raw Lua source code of a script."""
    console.print(f"[dim]Fetching script {script_id}…[/dim]")
    try:
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
