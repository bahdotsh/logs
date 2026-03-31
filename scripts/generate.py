#!/usr/bin/env python3
"""
Fetch merged PRs from GitHub and build a static site.

Usage:
    python generate.py --fetch --date 2026-04-22
    python generate.py --build
    python generate.py --fetch --date 2026-04-22 --build
"""

import argparse
import json
import os
import shutil
import sys
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
TEMPLATES_DIR = ROOT / "templates"
SITE_DIR = ROOT / "_site"

IST = timezone(timedelta(hours=5, minutes=30))


def fetch_prs(date_str: str) -> dict | None:
    """Fetch PRs merged on the given IST date. Returns None if no PRs found."""
    username = os.environ.get("GITHUB_USERNAME")
    if not username:
        print("Error: GITHUB_USERNAME env var not set", file=sys.stderr)
        sys.exit(1)

    token = os.environ.get("GITHUB_TOKEN", "")

    # Convert IST date boundaries to UTC
    # IST 00:00 = previous day 18:30 UTC
    # IST 23:59:59 = current day 18:29:59 UTC
    date = datetime.strptime(date_str, "%Y-%m-%d")
    utc_start = (date - timedelta(hours=5, minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    utc_end = (date + timedelta(hours=18, minutes=29, seconds=59)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    query = f"is:pr is:merged is:public author:{username} merged:{utc_start}..{utc_end}"
    url = f"https://api.github.com/search/issues?q={urllib.parse.quote(query)}&per_page=100&sort=updated&order=desc"

    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "logs-generator",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    print(f"Fetching PRs for {date_str} (UTC range: {utc_start} .. {utc_end})")

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        print(f"GitHub API error: {e.code} {e.reason}", file=sys.stderr)
        body = e.read().decode()
        print(body, file=sys.stderr)
        sys.exit(1)

    items = data.get("items", [])
    if not items:
        print(f"No PRs found for {date_str}")
        return None

    prs = []
    for item in items:
        # Extract repo from the URL: https://api.github.com/repos/owner/repo/...
        repo_url = item.get("repository_url", "")
        repo = "/".join(repo_url.rstrip("/").split("/")[-2:]) if repo_url else ""
        html_repo_url = f"https://github.com/{repo}" if repo else ""

        body = item.get("body") or ""
        # Truncate body to first 200 chars
        if len(body) > 200:
            body = body[:200].rsplit(" ", 1)[0] + "..."

        labels = [l["name"] for l in item.get("labels", [])]

        prs.append(
            {
                "title": item["title"],
                "url": item["html_url"],
                "repo": repo,
                "repo_url": html_repo_url,
                "body": body,
                "labels": labels,
                "merged_at": item.get("pull_request", {}).get("merged_at", ""),
            }
        )

    print(f"Found {len(prs)} PR(s) across {len(set(pr['repo'] for pr in prs))} repo(s)")

    result = {"date": date_str, "prs": prs}

    # Save to data directory
    DATA_DIR.mkdir(exist_ok=True)
    out_path = DATA_DIR / f"{date_str}.json"
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)
    print(f"Saved to {out_path}")

    return result


def load_all_data() -> list[dict]:
    """Load all JSON data files, sorted by date descending."""
    entries = []
    if not DATA_DIR.exists():
        return entries
    for path in sorted(DATA_DIR.glob("*.json"), reverse=True):
        with open(path) as f:
            entries.append(json.load(f))
    return entries


def format_date_display(date_str: str) -> str:
    """Convert 2026-04-22 to 'April 22, 2026'."""
    date = datetime.strptime(date_str, "%Y-%m-%d")
    return date.strftime("%B %d, %Y").replace(" 0", " ")


def plural(n: int) -> str:
    return "s" if n != 1 else ""


def build_index(entries: list[dict], template: str) -> str:
    """Build the index.html page."""
    if not entries:
        entries_html = '<div class="empty-state"><p>No log entries yet. Check back soon.</p></div>'
        repo_filter = ""
    else:
        # Collect all unique repos across all entries with PR counts
        all_repos = sorted(set(pr["repo"] for entry in entries for pr in entry["prs"]))
        repo_pr_counts = {}
        for repo in all_repos:
            repo_pr_counts[repo] = sum(
                1 for entry in entries for pr in entry["prs"] if pr["repo"] == repo
            )
        repo_data = json.dumps(
            [{"name": r, "count": repo_pr_counts[r]} for r in all_repos]
        )

        # Build searchable repo filter
        n = len(all_repos)
        repo_filter = (
            f'<div class="repo-filter" id="repoFilter">'
            f'<div class="filter-input-wrap">'
            f'<input type="text" class="filter-input" id="filterInput" '
            f'placeholder="Filter by repository..." autocomplete="off" spellcheck="false">'
            f'<span class="filter-count" id="filterCount">{n} repo{"s" if n != 1 else ""}</span>'
            f'<button class="filter-clear" id="filterClear">&times;</button>'
            f'</div>'
            f'<div class="filter-dropdown" id="filterDropdown"></div>'
            f'</div>'
            f'<script>var REPO_DATA={repo_data};</script>'
        )

        parts = []
        for entry in entries:
            date_str = entry["date"]
            prs = entry["prs"]
            repos = sorted(set(pr["repo"] for pr in prs))
            repo_tags = "".join(f'<a class="repo-tag" href="#" data-repo="{r}">{r}</a>' for r in repos)
            repos_attr = " ".join(repos)

            parts.append(
                f"""<div class="day-entry" data-repos="{repos_attr}">
    <a class="day-link" href="entries/{date_str}.html">{format_date_display(date_str)}</a>
    <div class="day-meta">{len(prs)} PR{plural(len(prs))} merged</div>
    <div class="day-repos">{repo_tags}</div>
</div>"""
            )
        entries_html = "\n".join(parts)

    html = template.replace("{{entries}}", entries_html)
    html = html.replace("{{repo_filter}}", repo_filter if entries else "")
    return html


def build_entry(entry: dict, template: str, prev_date: str | None, next_date: str | None) -> str:
    """Build an individual entry page."""
    date_str = entry["date"]
    prs = entry["prs"]

    # Group PRs by repo
    repos: dict[str, list[dict]] = {}
    for pr in prs:
        repos.setdefault(pr["repo"], []).append(pr)

    repo_sections = []
    for repo in sorted(repos.keys()):
        pr_items = []
        for pr in repos[repo]:
            labels_html = ""
            if pr["labels"]:
                label_spans = "".join(
                    f'<span class="pr-label">{l}</span>' for l in pr["labels"]
                )
                labels_html = f'<div class="pr-labels">{label_spans}</div>'

            body_html = ""
            if pr["body"]:
                body_html = f'<p class="pr-body">{escape_html(pr["body"])}</p>'

            pr_items.append(
                f"""<div class="pr-item">
    <div class="pr-title"><a href="{pr['url']}">{escape_html(pr['title'])}</a></div>
    {body_html}
    {labels_html}
</div>"""
            )

        repo_url = repos[repo][0]["repo_url"]
        repo_sections.append(
            f"""<section class="repo-section" data-repo="{repo}">
    <h3><a href="{repo_url}">{repo}</a></h3>
    {"".join(pr_items)}
</section>"""
        )

    # Navigation links
    prev_link = f'<a href="{prev_date}.html">&larr; {prev_date}</a>' if prev_date else "<span></span>"
    next_link = f'<a href="{next_date}.html">{next_date} &rarr;</a>' if next_date else "<span></span>"

    html = template
    html = html.replace("{{date}}", date_str)
    html = html.replace("{{date_display}}", format_date_display(date_str))
    html = html.replace("{{pr_count}}", str(len(prs)))
    html = html.replace("{{pr_plural}}", plural(len(prs)))
    html = html.replace("{{repo_count}}", str(len(repos)))
    html = html.replace("{{repo_plural}}", plural(len(repos)))
    html = html.replace("{{repo_sections}}", "\n".join(repo_sections))
    html = html.replace("{{prev_link}}", prev_link)
    html = html.replace("{{next_link}}", next_link)

    return html


def escape_html(text: str) -> str:
    """Basic HTML escaping."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def build_site():
    """Build the full static site from data files."""
    entries = load_all_data()

    # Read templates
    index_template = (TEMPLATES_DIR / "index.html").read_text()
    entry_template = (TEMPLATES_DIR / "entry.html").read_text()

    # Clean and create output directory
    if SITE_DIR.exists():
        shutil.rmtree(SITE_DIR)
    SITE_DIR.mkdir()
    (SITE_DIR / "entries").mkdir()

    # Copy CSS
    shutil.copy(TEMPLATES_DIR / "style.css", SITE_DIR / "style.css")

    # Copy CNAME if it exists
    cname_path = ROOT / "CNAME"
    if cname_path.exists():
        shutil.copy(cname_path, SITE_DIR / "CNAME")

    # Build index
    index_html = build_index(entries, index_template)
    (SITE_DIR / "index.html").write_text(index_html)

    # Build entry pages
    for i, entry in enumerate(entries):
        # entries are sorted newest first
        next_date = entries[i - 1]["date"] if i > 0 else None
        prev_date = entries[i + 1]["date"] if i < len(entries) - 1 else None
        entry_html = build_entry(entry, entry_template, prev_date, next_date)
        (SITE_DIR / "entries" / f"{entry['date']}.html").write_text(entry_html)

    print(f"Built site: {len(entries)} entries -> {SITE_DIR}")


SAMPLE_DATA = [
    {
        "date": "2026-03-31",
        "prs": [
            {
                "title": "Fix deadlock in async task scheduler",
                "url": "https://github.com/bahdotsh/dash/pull/87",
                "repo": "bahdotsh/dash",
                "repo_url": "https://github.com/bahdotsh/dash",
                "body": "Resolved a deadlock that occurred when multiple tasks competed for the same mutex during shutdown. Switched to a lock-free queue for the hot path.",
                "labels": ["bug", "critical"],
                "merged_at": "2026-03-31T09:15:00Z",
            },
            {
                "title": "Add support for TOML config files",
                "url": "https://github.com/bahdotsh/dash/pull/88",
                "repo": "bahdotsh/dash",
                "repo_url": "https://github.com/bahdotsh/dash",
                "body": "Users can now use TOML as an alternative to YAML for configuration. Autodetects format based on file extension.",
                "labels": ["enhancement"],
                "merged_at": "2026-03-31T14:20:00Z",
            },
            {
                "title": "Implement streaming JSON parser",
                "url": "https://github.com/bahdotsh/piko/pull/12",
                "repo": "bahdotsh/piko",
                "repo_url": "https://github.com/bahdotsh/piko",
                "body": "Added a zero-copy streaming JSON parser that handles newline-delimited JSON. Benchmarks show 3x throughput improvement over the previous buffered approach.",
                "labels": ["performance", "enhancement"],
                "merged_at": "2026-03-31T11:30:00Z",
            },
        ],
    },
    {
        "date": "2026-03-29",
        "prs": [
            {
                "title": "Add WebSocket support for real-time events",
                "url": "https://github.com/bahdotsh/piko/pull/10",
                "repo": "bahdotsh/piko",
                "repo_url": "https://github.com/bahdotsh/piko",
                "body": "Introduces a WebSocket server that pushes events to connected clients in real-time. Supports filtering by event type via query params.",
                "labels": ["feature"],
                "merged_at": "2026-03-29T08:45:00Z",
            },
            {
                "title": "Fix off-by-one in pagination cursor",
                "url": "https://github.com/bahdotsh/piko/pull/11",
                "repo": "bahdotsh/piko",
                "repo_url": "https://github.com/bahdotsh/piko",
                "body": "The cursor-based pagination was skipping the last item on each page. Root cause was using > instead of >= in the SQL query.",
                "labels": ["bug"],
                "merged_at": "2026-03-29T13:10:00Z",
            },
        ],
    },
    {
        "date": "2026-03-27",
        "prs": [
            {
                "title": "Initial project setup with CI pipeline",
                "url": "https://github.com/bahdotsh/termsync/pull/1",
                "repo": "bahdotsh/termsync",
                "repo_url": "https://github.com/bahdotsh/termsync",
                "body": "Scaffolded the project with Cargo, added GitHub Actions CI for tests and linting, and set up release workflow.",
                "labels": [],
                "merged_at": "2026-03-27T10:00:00Z",
            },
            {
                "title": "Add --json flag for machine-readable output",
                "url": "https://github.com/bahdotsh/dash/pull/85",
                "repo": "bahdotsh/dash",
                "repo_url": "https://github.com/bahdotsh/dash",
                "body": "All commands now support a --json flag that outputs structured JSON instead of human-readable text. Useful for scripting and piping.",
                "labels": ["enhancement"],
                "merged_at": "2026-03-27T19:15:00Z",
            },
        ],
    },
]


def write_sample_data():
    """Write sample data to data/ for local preview."""
    DATA_DIR.mkdir(exist_ok=True)
    paths = []
    for entry in SAMPLE_DATA:
        path = DATA_DIR / f"{entry['date']}.json"
        with open(path, "w") as f:
            json.dump(entry, f, indent=2)
        paths.append(path)
    print(f"Wrote {len(paths)} sample data files")
    return paths


def remove_sample_data():
    """Remove sample data files from data/."""
    for entry in SAMPLE_DATA:
        path = DATA_DIR / f"{entry['date']}.json"
        if path.exists():
            path.unlink()
    print("Cleaned up sample data files")


def main():
    parser = argparse.ArgumentParser(description="Open source activity log generator")
    parser.add_argument("--fetch", action="store_true", help="Fetch PRs from GitHub")
    parser.add_argument("--date", type=str, help="Date to fetch (YYYY-MM-DD)")
    parser.add_argument("--build", action="store_true", help="Build static site")
    parser.add_argument("--demo", action="store_true", help="Build site with sample data for local preview")

    args = parser.parse_args()

    if not args.fetch and not args.build and not args.demo:
        parser.print_help()
        sys.exit(1)

    if args.fetch:
        if not args.date:
            # Default to yesterday IST
            now_ist = datetime.now(IST)
            yesterday = now_ist - timedelta(days=1)
            args.date = yesterday.strftime("%Y-%m-%d")
            print(f"No date specified, using yesterday IST: {args.date}")
        fetch_prs(args.date)

    if args.demo:
        sample_paths = write_sample_data()
        build_site()
        remove_sample_data()
        print("Demo site ready at _site/")
        return

    if args.build:
        build_site()


if __name__ == "__main__":
    main()
