# R&D Credit Issue Scanner

Scan your GitHub or GitLab issues and automatically evaluate which ones qualify for **R&D tax credits** (IRC Section 41) using Claude AI.

Outputs a report with issue links, assignees, reviewers, logged hours, and AI verdict — ready to share with your R&D tax specialist.

---

## What it does

1. Connects to your GitHub or GitLab repo using a personal access token
2. Fetches all issues (optionally filtered by date range)
3. Evaluates each issue against the IRS 4-part test using Claude AI
4. Outputs three files: `.csv`, `.md`, and `.html` report

### Report columns

| Column | Description |
|---|---|
| Issue link | Direct link to the issue |
| Title | Issue title |
| Assignees | Who was assigned |
| Reviewers | Who reviewed (fill in manually or via API) |
| Has Time | Yes/No — whether time was logged |
| Hours | Logged hours (GitLab only — auto-fetched) |
| Verdict | Qualifying / Needs Review / Not Qualifying |
| Confidence | AI confidence score 0–100% |
| Reason | One-sentence explanation |

> **Note on rates:** Hourly rates (W-2 or contractor) are not included — add them yourself in the CSV to calculate QRE value and estimated credit (QRE × 6–8%).

---

## Requirements

- Python 3.8+ (no external dependencies — standard library only)
- A GitHub or GitLab personal access token
- [Claude Code](https://claude.ai/code) installed locally

---

## Setup

```bash
# Clone the repo
git clone https://github.com/yourusername/rd-credit-scanner
cd rd-credit-scanner

# Set your git token (keeps it out of shell history)
export GIT_TOKEN=your_github_or_gitlab_token
```

Evaluation runs through Claude Code locally — no API key needed.

### Creating a personal access token

**GitHub:** Settings → Developer settings → Personal access tokens → New token  
Scopes needed: `repo` (for private repos) or `public_repo` (for public repos)

**GitLab:** User Settings → Access Tokens → Add new token  
Scopes needed: `read_api`

---

## Usage

```bash
# GitHub — scan all issues
python scanner.py --platform github --repo owner/repo

# GitLab — scan all issues
python scanner.py --platform gitlab --repo group/project

# Filter by date range (IRS lookback — up to 3 years)
python scanner.py --platform github --repo owner/repo --since 2022-01-01 --until 2024-12-31

# Custom output filename
python scanner.py --platform gitlab --repo group/project --output my_report_2024

# Skip Not Qualifying issues from output
python scanner.py --platform github --repo owner/repo --skip-not-qualifying

# Pass token inline (not recommended — stays in shell history)
python scanner.py --platform github --repo owner/repo --token ghp_xxx
```

---

## Output

Three files are created (default prefix `rd_report`):

- `rd_report.csv` — share with your R&D tax specialist or accountant
- `rd_report.md` — Markdown version for GitHub/GitLab wikis
- `rd_report.html` — open in browser for a clean visual report

---

## How the AI evaluation works

Each issue title and description (up to 1000 chars) is sent to Claude with this prompt:

> Evaluate against the IRS 4-part test:
> 1. Technological in nature
> 2. Permitted purpose (improving a product/process/software)
> 3. Technical uncertainty (outcome not known in advance)
> 4. Experimentation (testing, iterating, evaluating alternatives)

Claude returns: `Qualifying`, `Needs Review`, or `Not Qualifying` with a confidence score and one-sentence reason.

**Important:** This is a screening tool, not a substitute for professional tax advice. Always have a qualified R&D tax specialist review the final list before filing.

---

## Cost

Free. Evaluation runs locally through Claude Code — no API costs.

---

## Privacy

- Your token and issues never leave your machine except to call the GitHub/GitLab API
- Issue content is passed to Claude Code locally for evaluation — nothing is sent to external servers
- No data is stored or logged by this tool

---

## Contributing

PRs welcome. Ideas for improvement:

- [ ] Support self-hosted GitLab instances (`--gitlab-url`)
- [ ] Fetch GitHub PR reviewers automatically
- [ ] Add `--dry-run` mode (fetch issues, skip AI evaluation)
- [ ] Support Jira and Linear

---

## License

MIT — free to use, modify, and distribute.

---

## Disclaimer

This tool is for informational purposes only and does not constitute tax advice. Consult a qualified R&D tax credit specialist before filing. The IRS 4-part test involves nuanced judgment — AI evaluation is a starting point, not a final determination.
