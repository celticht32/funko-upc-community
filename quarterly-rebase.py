#!/usr/bin/env python3
"""
quarterly-rebase.py

Validates funko_upc_community.json, flags problems for human review,
and writes a cleaned output file.

Two modes:
  LOCAL  (default)  — run from a git clone, outputs files for manual review.
  CI     (--ci)     — run in GitHub Actions, writes GITHUB_STEP_SUMMARY and
                      a rebase-summary.json for the workflow to consume.

Requirements: Python 3.8+ standard library only (no pip install needed).

Local usage:
    python3 quarterly-rebase.py
    python3 quarterly-rebase.py --master funko_upc_community.json --kenny funko_data.json

CI usage (called by quarterly-rebase.yml):
    python3 quarterly-rebase.py --ci

Local outputs:
    funko_upc_community_CLEANED.json   — cleaned master (review, then rename)
    REVIEW_invalid_upcs.json           — GS1 checksum failures
    REVIEW_junk.json                   — likely garbage / test records
    REVIEW_unknown_handle.json         — handles not in Kenny Chan (informational)

Local next steps after reviewing:
    cp funko_upc_community_CLEANED.json funko_upc_community.json
    git rm deltas/*.json
    echo '{}' > merge-state.json
    git add -A
    git commit -m "Quarterly rebase Q? YYYY — N records"
    git tag vYYYY-Q?
    git push --tags
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


# ── GS1 UPC-A check digit ─────────────────────────────────────────────────────

def upc_check_digit_valid(upc: str) -> bool:
    """Validate a 12-digit UPC-A using the GS1 check digit algorithm.
    GS1 spec: even-indexed positions (0,2,4,6,8,10) × 3, odd-indexed × 1.
    """
    if not re.fullmatch(r'\d{12}', upc):
        return False          # EAN-13 (13 digits) or non-numeric — skip
    digits = [int(d) for d in upc]
    total = sum(d * (3 if i % 2 == 0 else 1) for i, d in enumerate(digits[:11]))
    return (10 - (total % 10)) % 10 == digits[11]


# ── Junk / garbage detection ──────────────────────────────────────────────────

JUNK_NAME_RE = re.compile(
    r'^(test|asdf|xxx|aaa|bbb|ccc|123|foo|bar|funko\s*test)',
    re.IGNORECASE,
)
REPEATED_CHAR_RE = re.compile(r'^(.)\1+$')


def junk_reason(record: dict) -> str | None:
    name   = (record.get('name')   or '').strip()
    upc    = (record.get('upc')    or '')
    handle = (record.get('handle') or '')

    if JUNK_NAME_RE.match(name):                  return 'Junk name pattern'
    if len(name) < 3:                             return 'Name too short'
    if re.fullmatch(r'(\d)\1{11}', upc):         return 'Repeated-digit UPC'
    if REPEATED_CHAR_RE.match(handle):            return 'Repeated-character handle'
    return None


# ── Helpers ───────────────────────────────────────────────────────────────────

def source_breakdown(records: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in records:
        src = r.get('source', 'UNKNOWN')
        counts[src] = counts.get(src, 0) + 1
    return counts


def quarter_label() -> str:
    now = datetime.now(timezone.utc)
    q = (now.month - 1) // 3 + 1
    return f"Q{q} {now.year}"


# ── GitHub Actions helpers ────────────────────────────────────────────────────

def gha_summary(text: str) -> None:
    """Append markdown to the GitHub Actions step summary."""
    summary_file = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary_file:
        with open(summary_file, 'a') as f:
            f.write(text + '\n')


def gha_output(key: str, value: str) -> None:
    """Set a GitHub Actions output variable."""
    output_file = os.environ.get('GITHUB_OUTPUT')
    if output_file:
        with open(output_file, 'a') as f:
            f.write(f'{key}={value}\n')


def gha_notice(msg: str) -> None:
    print(f'::notice::{msg}')


def gha_warning(msg: str) -> None:
    print(f'::warning::{msg}')


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description='FunkoDex quarterly rebase tool')
    parser.add_argument('--master', default='funko_upc_community.json')
    parser.add_argument('--kenny',  default='funko_data.json')
    parser.add_argument('--ci',     action='store_true',
                        help='CI mode: write GitHub Actions summary + rebase-summary.json')
    args = parser.parse_args()

    ci          = args.ci
    master_path = Path(args.master)
    kenny_path  = Path(args.kenny)
    run_date    = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')

    # ── Load master ───────────────────────────────────────────────────────────
    if not master_path.exists():
        print(f'ERROR: {master_path} not found.', file=sys.stderr)
        sys.exit(1)

    with master_path.open() as f:
        master: list[dict] = json.load(f)

    # ── Load Kenny Chan handles ───────────────────────────────────────────────
    kenny_handles: set[str] = set()
    if kenny_path.exists():
        with kenny_path.open() as f:
            kenny_data: list[dict] = json.load(f)
        kenny_handles = {r['handle'] for r in kenny_data if r.get('handle')}

    # ── Validate and classify ─────────────────────────────────────────────────
    clean:           list[dict] = []
    invalid_upcs:    list[dict] = []
    junk_records:    list[dict] = []
    unknown_handles: list[dict] = []

    for record in master:
        upc = record.get('upc', '')

        if len(upc) == 12 and not upc_check_digit_valid(upc):
            invalid_upcs.append({**record, '_reason': 'GS1 check digit invalid'})
            continue

        reason = junk_reason(record)
        if reason:
            junk_records.append({**record, '_reason': reason})
            continue

        if kenny_handles and record.get('handle', '') not in kenny_handles:
            unknown_handles.append({
                **record,
                '_reason': 'Handle not in Kenny Chan dataset',
            })

        clean.append(record)

    # ── Sort for stable diffs ─────────────────────────────────────────────────
    clean.sort(key=lambda r: (
        (r.get('franchise') or '').lower(),
        (r.get('name')      or '').lower(),
    ))

    breakdown     = source_breakdown(clean)
    needs_review  = bool(invalid_upcs or junk_records)
    ql            = quarter_label()

    # ── Write output files (both modes) ──────────────────────────────────────
    with open('funko_upc_community_CLEANED.json', 'w') as f:
        json.dump(clean, f, indent=2)
    with open('REVIEW_invalid_upcs.json', 'w') as f:
        json.dump(invalid_upcs, f, indent=2)
    with open('REVIEW_junk.json', 'w') as f:
        json.dump(junk_records, f, indent=2)
    with open('REVIEW_unknown_handle.json', 'w') as f:
        json.dump(unknown_handles, f, indent=2)

    # ── CI mode: write structured summary for workflow ────────────────────────
    if ci:
        summary_data = {
            'run_date':       run_date,
            'quarter':        ql,
            'input_count':    len(master),
            'clean_count':    len(clean),
            'invalid_count':  len(invalid_upcs),
            'junk_count':     len(junk_records),
            'unknown_count':  len(unknown_handles),
            'needs_review':   needs_review,
            'source_breakdown': breakdown,
            'invalid_records':  invalid_upcs[:20],   # cap for PR comment size
            'junk_records':     junk_records[:20],
        }
        with open('rebase-summary.json', 'w') as f:
            json.dump(summary_data, f, indent=2)

        # Set output for workflow conditional steps
        gha_output('has_review', 'true' if needs_review else 'false')
        gha_output('clean_count', str(len(clean)))
        gha_output('quarter', ql)

        # Write GitHub Actions step summary (shows in Actions UI)
        gha_summary(f'## 🔄 Quarterly rebase — {ql}')
        gha_summary(f'**Run date:** {run_date}  ')
        gha_summary(f'**Records in:** {len(master):,}  |  **Records out (clean):** {len(clean):,}')
        gha_summary('')
        gha_summary('### Validation results')
        gha_summary('| Check | Count | Status |')
        gha_summary('|---|---|---|')
        gha_summary(f'| Clean records | {len(clean):,} | ✅ |')
        gha_summary(f'| Invalid UPCs removed | {len(invalid_upcs):,} | {"⚠️ review needed" if invalid_upcs else "✅ none"} |')
        gha_summary(f'| Junk records removed | {len(junk_records):,} | {"⚠️ review needed" if junk_records else "✅ none"} |')
        gha_summary(f'| Unknown handles (informational) | {len(unknown_handles):,} | ℹ️ |')
        gha_summary('')
        gha_summary('### Source breakdown')
        gha_summary('| Source | Count |')
        gha_summary('|---|---|')
        for src, count in sorted(breakdown.items(), key=lambda x: -x[1]):
            gha_summary(f'| `{src}` | {count:,} |')

        if invalid_upcs:
            gha_summary('')
            gha_summary('### ⚠️ Invalid UPCs (first 10)')
            gha_summary('| UPC | Handle | Name | Reason |')
            gha_summary('|---|---|---|---|')
            for r in invalid_upcs[:10]:
                gha_summary(f'| `{r.get("upc","")}` | {r.get("handle","")} | {r.get("name","")} | {r.get("_reason","")} |')

        if junk_records:
            gha_summary('')
            gha_summary('### ⚠️ Junk records (first 10)')
            gha_summary('| UPC | Handle | Name | Reason |')
            gha_summary('|---|---|---|---|')
            for r in junk_records[:10]:
                gha_summary(f'| `{r.get("upc","")}` | {r.get("handle","")} | {r.get("name","")} | {r.get("_reason","")} |')

        if needs_review:
            gha_warning(f'Quarterly rebase flagged {len(invalid_upcs)} invalid UPCs and {len(junk_records)} junk records — a PR has been opened for review.')
        else:
            gha_notice(f'Quarterly rebase complete — {len(clean):,} clean records, no issues. Committed directly to main.')

        print(f'CI mode: {len(clean):,} clean, {len(invalid_upcs)} invalid, {len(junk_records)} junk, needs_review={needs_review}')
        return

    # ── Local mode: human-readable report ────────────────────────────────────
    print()
    print('=' * 55)
    print(f'QUARTERLY REBASE REPORT — {ql}')
    print(f'Run date: {run_date}')
    print('=' * 55)
    print(f'Input records:           {len(master):>8,}')
    print(f'Clean records:           {len(clean):>8,}')
    print(f'Invalid UPCs removed:    {len(invalid_upcs):>8,}  → REVIEW_invalid_upcs.json')
    print(f'Junk records removed:    {len(junk_records):>8,}  → REVIEW_junk.json')
    print(f'Unknown handles:         {len(unknown_handles):>8,}  → REVIEW_unknown_handle.json (not removed)')
    print()
    print('Source breakdown (clean records):')
    for src, count in sorted(breakdown.items(), key=lambda x: -x[1]):
        print(f'  {src:<28} {count:>6,}')
    print()
    if needs_review:
        print('⚠  REVIEW REQUIRED — see REVIEW_*.json files.')
    else:
        print('✓  No issues found. Safe to proceed.')
    print()
    print('Next steps:')
    print('  1. Review REVIEW_*.json files')
    print('  2. cp funko_upc_community_CLEANED.json funko_upc_community.json')
    print('  3. git rm deltas/*.json')
    print('  4. echo "{}" > merge-state.json')
    print('  5. git add -A && git commit -m "Quarterly rebase Q? YYYY"')
    print('  6. git tag vYYYY-Q?  &&  git push --tags')


if __name__ == '__main__':
    main()
