#!/bin/bash
# Scan all postgres-ai GitLab projects for R&D credit qualifying issues
set -e

TOKEN="$1"
GROUP="postgres-ai"
OUTPUT_DIR="/Users/inga/rd-credit-scanner/results"
mkdir -p "$OUTPUT_DIR"

# Get all project paths with issues
echo "Fetching project list from $GROUP..."
PROJECTS=$(python3 -c "
import json, urllib.request

headers = {'PRIVATE-TOKEN': '$TOKEN', 'User-Agent': 'rd-credit-scanner'}
projects = []
page = 1
while True:
    url = f'https://gitlab.com/api/v4/groups/$GROUP/projects?per_page=100&include_subgroups=true&page={page}'
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req) as r:
        data = json.loads(r.read())
    if not data:
        break
    for p in data:
        if p.get('open_issues_count', 0) > 0:
            projects.append(p['path_with_namespace'])
    page += 1
for p in sorted(projects):
    print(p)
")

TOTAL=$(echo "$PROJECTS" | wc -l | tr -d ' ')
echo "Found $TOTAL projects with issues"
echo ""

COUNT=0
for PROJECT in $PROJECTS; do
    COUNT=$((COUNT + 1))
    SAFE_NAME=$(echo "$PROJECT" | tr '/' '_')
    echo "=== [$COUNT/$TOTAL] Scanning: $PROJECT ==="
    python3 /Users/inga/rd-credit-scanner/scanner.py \
        --platform gitlab \
        --repo "$PROJECT" \
        --token "$TOKEN" \
        --output "$OUTPUT_DIR/$SAFE_NAME" \
        2>&1 || echo "  FAILED: $PROJECT"
    echo ""
done

# Combine all CSVs into one master file
echo "Combining results..."
FIRST=true
for CSV in "$OUTPUT_DIR"/*.csv; do
    if [ "$FIRST" = true ]; then
        cat "$CSV" > "$OUTPUT_DIR/ALL_COMBINED.csv"
        FIRST=false
    else
        tail -n +2 "$CSV" >> "$OUTPUT_DIR/ALL_COMBINED.csv"
    fi
done

echo ""
echo "=== DONE ==="
echo "Individual reports: $OUTPUT_DIR/<project>.{csv,md,html}"
echo "Combined CSV: $OUTPUT_DIR/ALL_COMBINED.csv"
echo ""

# Print summary
python3 -c "
import csv
with open('$OUTPUT_DIR/ALL_COMBINED.csv') as f:
    rows = list(csv.DictReader(f))
q = [r for r in rows if r['verdict'] == 'Qualifying']
nr = [r for r in rows if r['verdict'] == 'Needs Review']
nq = [r for r in rows if r['verdict'] == 'Not Qualifying']
print(f'Total issues scanned: {len(rows)}')
print(f'Qualifying:           {len(q)}')
print(f'Needs Review:         {len(nr)}')
print(f'Not Qualifying:       {len(nq)}')
hours = sum(float(r.get('time_spent_hours') or 0) for r in q)
print(f'Logged hours (qual):  {hours:.1f}h')
"
