#!/usr/bin/env python3
"""
R&D Credit Issue Scanner
Scans GitHub or GitLab issues and evaluates them for R&D tax credit qualification.
https://github.com/yourusername/rd-credit-scanner
"""

import argparse
import csv
import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime


# ── API helpers ───────────────────────────────────────────────────────────────

def fetch_json(url, headers):
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read()), dict(r.headers)
    except urllib.error.HTTPError as e:
        print(f"  Error {e.code} fetching {url}: {e.reason}")
        return None, {}


def fetch_github_issues(repo, token, since=None, until=None):
    """Fetch all issues from a GitHub repo."""
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "rd-credit-scanner"
    }
    issues = []
    page = 1
    print(f"  Fetching GitHub issues from {repo}...")
    while True:
        url = f"https://api.github.com/repos/{repo}/issues?state=all&per_page=100&page={page}"
        if since:
            url += f"&since={since}T00:00:00Z"
        data, _ = fetch_json(url, headers)
        if not data:
            break
        # Filter pull requests
        batch = [i for i in data if "pull_request" not in i]
        if not batch:
            break
        for issue in batch:
            created = issue.get("created_at", "")[:10]
            if until and created > until:
                continue
            assignees = ", ".join(a["login"] for a in issue.get("assignees", []))
            issues.append({
                "id": str(issue["number"]),
                "title": issue.get("title", ""),
                "description": issue.get("body", "") or "",
                "url": issue.get("html_url", ""),
                "created_at": created,
                "state": issue.get("state", ""),
                "assignees": assignees,
                "reviewers": "",
                "time_spent_hours": None,
            })
        if len(data) < 100:
            break
        page += 1
    print(f"  Found {len(issues)} issues")
    return issues


def fetch_gitlab_issues(project, token, since=None, until=None):
    """Fetch all issues from a GitLab project (group/project or project ID)."""
    headers = {
        "PRIVATE-TOKEN": token,
        "User-Agent": "rd-credit-scanner"
    }
    # URL-encode the project path
    encoded = urllib.request.quote(project, safe="")
    base = f"https://gitlab.com/api/v4/projects/{encoded}"
    issues = []
    page = 1
    print(f"  Fetching GitLab issues from {project}...")
    while True:
        url = f"{base}/issues?state=all&per_page=100&page={page}"
        if since:
            url += f"&created_after={since}T00:00:00Z"
        if until:
            url += f"&created_before={until}T23:59:59Z"
        data, headers_resp = fetch_json(url, headers)
        if not data:
            break
        for issue in data:
            created = issue.get("created_at", "")[:10]
            assignees = ", ".join(
                a.get("username", "") for a in issue.get("assignees", [])
            )
            # Fetch time stats
            time_hours = None
            iid = issue.get("iid")
            time_data, _ = fetch_json(f"{base}/issues/{iid}/time_stats", headers)
            if time_data:
                seconds = time_data.get("total_time_spent", 0)
                if seconds and seconds > 0:
                    time_hours = round(seconds / 3600, 2)

            issues.append({
                "id": str(iid),
                "title": issue.get("title", ""),
                "description": issue.get("description", "") or "",
                "url": issue.get("web_url", ""),
                "created_at": created,
                "state": issue.get("state", ""),
                "assignees": assignees,
                "reviewers": "",
                "time_spent_hours": time_hours,
            })
        next_page = headers_resp.get("X-Next-Page", "")
        if not next_page:
            break
        page += 1
    print(f"  Found {len(issues)} issues")
    return issues


# ── Claude evaluator ──────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are an R&D tax credit specialist. Evaluate each GitHub/GitLab issue
against the IRS 4-part test for qualifying research (IRC Section 41):

1. Technological in nature (based on engineering, CS, science)
2. Permitted purpose (developing/improving a product, process, or software)
3. Technical uncertainty (outcome or method was not known in advance)
4. Experimentation (testing, iterating, evaluating alternatives)

Respond with ONLY a JSON object — no markdown, no explanation:
{
  "verdict": "Qualifying" | "Needs Review" | "Not Qualifying",
  "confidence": 0-100,
  "reason": "one sentence max"
}

Be practical. Real-world software issues often qualify even if they don't use academic language.
If the title/description suggests figuring out HOW to do something technical — lean toward Qualifying.
If it's clearly admin, docs, bug fix on known code, or support — mark Not Qualifying."""


def evaluate_issue(issue):
    """Evaluate an issue using the local Claude Code CLI."""
    import subprocess
    content = (
        f"{SYSTEM_PROMPT}\n\n"
        f"Title: {issue['title']}\n\n"
        f"Description: {issue['description'][:4000]}\n\n"
        f"Respond with ONLY a JSON object, no markdown."
    )
    try:
        result = subprocess.run(
            ["claude", "--print"],
            input=content,
            capture_output=True,
            text=True,
            timeout=30
        )
        text = result.stdout.strip()
        text = text.replace("```json", "").replace("```", "").strip()
        return json.loads(text)
    except FileNotFoundError:
        print("\n  Error: 'claude' command not found.")
        print("  Make sure Claude Code is installed: https://claude.ai/code")
        sys.exit(1)
    except Exception as e:
        return {"verdict": "Needs Review", "confidence": 0, "reason": f"Evaluation error: {e}"}


# ── Output writers ────────────────────────────────────────────────────────────

COLUMNS = [
    "id", "title", "url", "created_at", "state",
    "assignees", "reviewers",
    "verdict", "confidence", "reason",
    "has_time", "time_spent_hours"
]


def write_csv(issues, path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(issues)
    print(f"  CSV  → {path}")


def write_markdown(issues, path, platform, repo, since, until):
    qualifying = [i for i in issues if i["verdict"] == "Qualifying"]
    needs_review = [i for i in issues if i["verdict"] == "Needs Review"]
    total_hours = sum(i["time_spent_hours"] or 0 for i in qualifying)

    lines = [
        f"# R&D Credit Issue Report",
        f"",
        f"**Platform:** {platform}  ",
        f"**Repository:** {repo}  ",
        f"**Date range:** {since or 'all time'} → {until or 'today'}  ",
        f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"",
        f"## Summary",
        f"",
        f"| | Count |",
        f"|---|---|",
        f"| Qualifying issues | {len(qualifying)} |",
        f"| Needs review | {len(needs_review)} |",
        f"| Not qualifying | {len([i for i in issues if i['verdict'] == 'Not Qualifying'])} |",
        f"| Total issues scanned | {len(issues)} |",
        f"| Total logged hours (qualifying) | {total_hours:.1f}h |",
        f"",
        f"> Add your hourly rates to calculate QRE value and estimated credit (×6-8%)",
        f"",
    ]

    for verdict, label in [("Qualifying", "Qualifying Issues"), ("Needs Review", "Needs Review")]:
        group = [i for i in issues if i["verdict"] == verdict]
        if not group:
            continue
        lines += [f"## {label} ({len(group)})", ""]
        lines += ["| Issue | Assignees | Reviewers | Has Time | Hours | Confidence | Reason |",
                  "|---|---|---|---|---|---|---|"]
        for i in group:
            hours = f"{i['time_spent_hours']:.1f}" if i["time_spent_hours"] else "—"
            lines.append(
                f"| [{i['title'][:60]}]({i['url']}) "
                f"| {i['assignees'] or '—'} "
                f"| {i['reviewers'] or '—'} "
                f"| {i['has_time']} "
                f"| {hours} "
                f"| {i['confidence']}% "
                f"| {i['reason']} |"
            )
        lines.append("")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"  MD   → {path}")


def write_html(issues, path, platform, repo, since, until):
    qualifying = [i for i in issues if i["verdict"] == "Qualifying"]
    needs_review = [i for i in issues if i["verdict"] == "Needs Review"]
    not_qualifying = [i for i in issues if i["verdict"] == "Not Qualifying"]
    total_hours = sum(i["time_spent_hours"] or 0 for i in qualifying)

    def badge(verdict):
        colors = {
            "Qualifying": ("#e8f5e9", "#2e7d32"),
            "Needs Review": ("#fff8e1", "#f57f17"),
            "Not Qualifying": ("#fce4ec", "#c62828"),
        }
        bg, fg = colors.get(verdict, ("#eee", "#333"))
        return f'<span style="background:{bg};color:{fg};padding:2px 8px;border-radius:4px;font-size:12px;font-weight:600">{verdict}</span>'

    def rows(group):
        if not group:
            return "<tr><td colspan='8' style='color:#999;text-align:center'>None</td></tr>"
        out = []
        for i in group:
            hours = f"{i['time_spent_hours']:.1f}h" if i["time_spent_hours"] else "—"
            out.append(f"""<tr>
              <td><a href="{i['url']}" target="_blank">#{i['id']}</a></td>
              <td><a href="{i['url']}" target="_blank">{i['title'][:70]}</a></td>
              <td>{i['created_at']}</td>
              <td>{i['assignees'] or '—'}</td>
              <td>{i['reviewers'] or '—'}</td>
              <td style="text-align:center">{i['has_time']}</td>
              <td style="text-align:center">{hours}</td>
              <td style="font-size:12px;color:#555">{i['reason']}</td>
            </tr>""")
        return "\n".join(out)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>R&D Credit Report — {repo}</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 0; padding: 24px; color: #1a1a1a; background: #f8f8f8; }}
  .card {{ background: #fff; border-radius: 8px; padding: 24px; margin-bottom: 24px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }}
  h1 {{ font-size: 22px; margin: 0 0 4px; color: #1f4e79; }}
  h2 {{ font-size: 16px; margin: 0 0 16px; color: #2e75b6; border-bottom: 2px solid #e8f0fe; padding-bottom: 8px; }}
  .meta {{ color: #666; font-size: 13px; margin-bottom: 0; }}
  .summary {{ display: flex; gap: 16px; flex-wrap: wrap; }}
  .stat {{ flex: 1; min-width: 120px; background: #f5f5f5; border-radius: 6px; padding: 12px 16px; }}
  .stat .n {{ font-size: 28px; font-weight: 700; color: #1f4e79; }}
  .stat .l {{ font-size: 12px; color: #666; margin-top: 2px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th {{ background: #1f4e79; color: #fff; padding: 8px 10px; text-align: left; font-weight: 500; }}
  td {{ padding: 8px 10px; border-bottom: 1px solid #f0f0f0; vertical-align: top; }}
  tr:hover td {{ background: #fafafa; }}
  a {{ color: #1565c0; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  .note {{ font-size: 12px; color: #888; margin-top: 12px; }}
</style>
</head>
<body>
<div class="card">
  <h1>R&D Credit Issue Report</h1>
  <p class="meta"><strong>Platform:</strong> {platform} &nbsp;|&nbsp;
  <strong>Repo:</strong> {repo} &nbsp;|&nbsp;
  <strong>Range:</strong> {since or 'all time'} → {until or 'today'} &nbsp;|&nbsp;
  <strong>Generated:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>
</div>

<div class="card">
  <h2>Summary</h2>
  <div class="summary">
    <div class="stat"><div class="n">{len(qualifying)}</div><div class="l">Qualifying</div></div>
    <div class="stat"><div class="n">{len(needs_review)}</div><div class="l">Needs Review</div></div>
    <div class="stat"><div class="n">{len(not_qualifying)}</div><div class="l">Not Qualifying</div></div>
    <div class="stat"><div class="n">{len(issues)}</div><div class="l">Total scanned</div></div>
    <div class="stat"><div class="n">{total_hours:.1f}h</div><div class="l">Logged hours (qualifying)</div></div>
  </div>
  <p class="note">Add assignee/reviewer hourly rates to calculate QRE value. Estimated credit = QRE × 6–8%.</p>
</div>

<div class="card">
  <h2>Qualifying Issues ({len(qualifying)})</h2>
  <table>
    <tr><th>#</th><th>Title</th><th>Created</th><th>Assignees</th><th>Reviewers</th><th>Has Time</th><th>Hours</th><th>Reason</th></tr>
    {rows(qualifying)}
  </table>
</div>

<div class="card">
  <h2>Needs Review ({len(needs_review)})</h2>
  <table>
    <tr><th>#</th><th>Title</th><th>Created</th><th>Assignees</th><th>Reviewers</th><th>Has Time</th><th>Hours</th><th>Reason</th></tr>
    {rows(needs_review)}
  </table>
</div>

<div class="card">
  <h2>Not Qualifying ({len(not_qualifying)})</h2>
  <table>
    <tr><th>#</th><th>Title</th><th>Created</th><th>Assignees</th><th>Reviewers</th><th>Has Time</th><th>Hours</th><th>Reason</th></tr>
    {rows(not_qualifying)}
  </table>
</div>

<p class="note" style="text-align:center">Generated by <a href="https://github.com/yourusername/rd-credit-scanner">rd-credit-scanner</a> — open source R&D tax credit tool</p>
</body>
</html>"""

    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  HTML → {path}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Scan GitHub/GitLab issues for R&D tax credit qualification"
    )
    parser.add_argument("--platform", choices=["github", "gitlab"], required=True,
                        help="github or gitlab")
    parser.add_argument("--repo", required=True,
                        help="Repository path, e.g. owner/repo or group/project")
    parser.add_argument("--token", default=os.environ.get("GIT_TOKEN"),
                        help="Personal access token (or set GIT_TOKEN env var)")
    parser.add_argument("--since", help="Start date YYYY-MM-DD (optional)")
    parser.add_argument("--until", help="End date YYYY-MM-DD (optional)")
    parser.add_argument("--output", default="rd_report",
                        help="Output file prefix (default: rd_report)")
    parser.add_argument("--skip-not-qualifying", action="store_true",
                        help="Exclude Not Qualifying issues from output")
    args = parser.parse_args()

    if not args.token:
        print("Error: provide --token or set GIT_TOKEN environment variable")
        sys.exit(1)

    print(f"\nR&D Credit Scanner")
    print(f"Platform : {args.platform}")
    print(f"Repo     : {args.repo}")
    print(f"Range    : {args.since or 'all time'} → {args.until or 'today'}")
    print()

    # Fetch issues
    print("Step 1: Fetching issues...")
    if args.platform == "github":
        issues = fetch_github_issues(args.repo, args.token, args.since, args.until)
    else:
        issues = fetch_gitlab_issues(args.repo, args.token, args.since, args.until)

    if not issues:
        print("No issues found. Check your token and repo path.")
        sys.exit(1)

    # Evaluate with Claude
    print(f"\nStep 2: Evaluating {len(issues)} issues with Claude...")
    for idx, issue in enumerate(issues, 1):
        print(f"  [{idx}/{len(issues)}] #{issue['id']} {issue['title'][:60]}")
        result = evaluate_issue(issue)
        issue["verdict"] = result.get("verdict", "Needs Review")
        issue["confidence"] = result.get("confidence", 0)
        issue["reason"] = result.get("reason", "")
        issue["has_time"] = "Yes" if issue["time_spent_hours"] else "No"

    # Filter if requested
    output_issues = issues
    if args.skip_not_qualifying:
        output_issues = [i for i in issues if i["verdict"] != "Not Qualifying"]

    # Write outputs
    print(f"\nStep 3: Writing reports...")
    write_csv(output_issues, f"{args.output}.csv")
    write_markdown(output_issues, f"{args.output}.md",
                   args.platform, args.repo, args.since, args.until)
    write_html(output_issues, f"{args.output}.html",
               args.platform, args.repo, args.since, args.until)

    # Summary
    qualifying = [i for i in issues if i["verdict"] == "Qualifying"]
    needs_review = [i for i in issues if i["verdict"] == "Needs Review"]
    total_hours = sum(i["time_spent_hours"] or 0 for i in qualifying)
    print(f"""
Done.
  Qualifying    : {len(qualifying)} issues
  Needs Review  : {len(needs_review)} issues
  Not Qualifying: {len([i for i in issues if i['verdict'] == 'Not Qualifying'])} issues
  Logged hours  : {total_hours:.1f}h (qualifying only)

Open {args.output}.html in your browser to review.
Share {args.output}.csv with your R&D tax specialist.
""")


if __name__ == "__main__":
    main()
