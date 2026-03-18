"""LinkedIn CLI — post impressions, reactions, profile views."""

import json
import sys

import click
from rich.console import Console
from rich.table import Table

from .browser import (
    login as browser_login,
    clear_session,
    has_session,
    SESSION_FILE,
)
from .scraper import scrape_posts, scrape_profile_views, dump_page

console = Console()


# ── root ──────────────────────────────────────────────────────────────────

@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx):
    """LinkedIn analytics CLI — post impressions & profile views."""
    if ctx.invoked_subcommand is None:
        # No subcommand → show status like gcloud
        _print_status()


def _print_status():
    """Print current configuration/status."""
    console.print("\n[bold]linkedin-cli[/bold]  v0.1.0\n")
    if has_session():
        console.print("  Status:   [green]authenticated[/green]")
        import os
        from datetime import datetime
        mtime = os.path.getmtime(SESSION_FILE)
        age = datetime.now() - datetime.fromtimestamp(mtime)
        console.print(f"  Session:  {SESSION_FILE}")
        console.print(f"  Age:      {age.days}d {age.seconds // 3600}h")
    else:
        console.print("  Status:   [yellow]not authenticated[/yellow]")
        console.print("\n  Run [bold]linkedin login[/bold] to get started.")
    console.print()
    console.print("  Commands:")
    console.print("    linkedin login      Authenticate (opens browser)")
    console.print("    linkedin posts      Post impressions & engagement")
    console.print("    linkedin views      Profile viewers")
    console.print()


# ── auth ─────────────────────────────────────────────────────────────────

@cli.command()
def login():
    """Login to LinkedIn (opens a browser window)."""
    console.print("Opening browser — please log in to LinkedIn…")
    try:
        browser_login()
        console.print("[green]Login successful. Session saved.[/green]")
    except Exception as e:
        console.print(f"[red]Login failed: {e}[/red]")
        sys.exit(1)


@cli.command()
def logout():
    """Clear saved session."""
    clear_session()
    console.print("Session cleared.")


# ── posts ─────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--days", default=90, show_default=True, help="How many days back to look")
@click.option("--json", "as_json", is_flag=True, help="Output raw JSON")
@click.option("--debug", is_flag=True, help="Print debug info")
def posts(days, as_json, debug):
    """List your posts with impression & engagement stats."""
    _require_auth()
    try:
        data = scrape_posts(days=days, debug=debug)
    except RuntimeError as e:
        console.print(f"[red]{e}[/red]")
        sys.exit(1)

    if as_json:
        click.echo(json.dumps(data, indent=2, default=str, ensure_ascii=False))
        return

    summary = data.get("summary", {})
    post_list = data.get("posts", [])

    if not post_list:
        console.print("[yellow]No post data found. Try: linkedin dump posts[/yellow]")
        return

    # Summary line
    if summary:
        parts = []
        if summary.get("impressions"):
            s = f'{summary["impressions"]:,} impressions'
            if summary.get("impressions_change"):
                s += f' ({summary["impressions_change"]} vs prior)'
            parts.append(s)
        if summary.get("members_reached"):
            s = f'{summary["members_reached"]:,} members reached'
            if summary.get("members_reached_change"):
                s += f' ({summary["members_reached_change"]} vs prior)'
            parts.append(s)
        if parts:
            console.print(f"\n[bold]{' | '.join(parts)}[/bold]\n")

    table = Table(title=f"Post Analytics (past {days} days)", show_lines=True)
    table.add_column("Date", style="cyan", no_wrap=True)
    table.add_column("Post", max_width=60)
    table.add_column("Impressions", justify="right", style="green")
    table.add_column("Reactions", justify="right", style="yellow")
    table.add_column("Comments", justify="right", style="blue")
    table.add_column("Reposts", justify="right", style="magenta")

    for p in post_list:
        pub = p.get("published_at", "")
        if pub:
            from datetime import datetime as _dt
            try:
                date_str = _dt.fromisoformat(pub).strftime("%Y-%m-%d %H:%M")
            except ValueError:
                date_str = pub
        else:
            date_str = p.get("timeago", "")
        table.add_row(
            date_str,
            p.get("text", "")[:60],
            f'{p.get("impressions", 0):,}',
            f'{p.get("reactions", 0):,}',
            f'{p.get("comments", 0):,}',
            f'{p.get("reposts", 0):,}',
        )

    console.print(table)


# ── profile views ─────────────────────────────────────────────────────────

@cli.command()
@click.option("--json", "as_json", is_flag=True, help="Output raw JSON")
@click.option("--debug", is_flag=True, help="Print debug info")
def views(as_json, debug):
    """Show who viewed your profile."""
    _require_auth()
    try:
        data = scrape_profile_views(debug=debug)
    except RuntimeError as e:
        console.print(f"[red]{e}[/red]")
        sys.exit(1)

    if as_json:
        click.echo(json.dumps(data, indent=2, default=str, ensure_ascii=False))
        return

    if data.get("total_views"):
        console.print(f"\nProfile views: [bold green]{data['total_views']:,}[/bold green]\n")

    if data.get("daily_views"):
        dt = Table(title="Daily Views")
        dt.add_column("Date", style="cyan")
        dt.add_column("Views", justify="right", style="green")
        for dv in data["daily_views"]:
            dt.add_row(dv["date"], str(dv["views"]))
        console.print(dt)

    if data.get("viewers"):
        vt = Table(title="Viewers")
        vt.add_column("Name", style="green")
        vt.add_column("Headline", max_width=60)
        vt.add_column("Viewed", style="cyan")
        for v in data["viewers"]:
            vt.add_row(v["name"], v["headline"], v.get("viewed_at", ""))
        console.print(vt)

    if not data.get("total_views") and not data.get("viewers"):
        console.print("[yellow]No profile view data found. Try: linkedin dump views[/yellow]")


# ── dump (debug) ──────────────────────────────────────────────────────────

DUMP_URLS = {
    "posts": "https://www.linkedin.com/analytics/creator/content/",
    "views": "https://www.linkedin.com/me/profile-views/",
    "feed": "https://www.linkedin.com/feed/",
    "analytics": "https://www.linkedin.com/analytics/",
}


@cli.command()
@click.argument("page", type=click.Choice(list(DUMP_URLS.keys())))
def dump(page):
    """Dump raw API responses from a LinkedIn page (for debugging)."""
    _require_auth()
    try:
        data = dump_page(DUMP_URLS[page])
    except RuntimeError as e:
        console.print(f"[red]{e}[/red]")
        sys.exit(1)

    click.echo(json.dumps(data, indent=2, default=str))


# ── helpers ───────────────────────────────────────────────────────────────

def _require_auth():
    if not has_session():
        console.print("[red]Not authenticated. Run: linkedin login[/red]")
        sys.exit(1)


if __name__ == "__main__":
    cli()
