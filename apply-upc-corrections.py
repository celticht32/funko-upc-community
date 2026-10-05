#!/usr/bin/env python3
"""
apply-upc-corrections.py

Applies verified manual UPC corrections to the v2 golden master
(funko_catalog_master.json), reading the SAME upc_corrections.json that
funko_enrich/apply_upc_corrections.js consumes, so a correction is stated
once and applied in both places.

Why this exists: merge-contributions.py is fill-only and will never overwrite
a non-blank UPC, so a wrong UPC already in the master can only be corrected
by a targeted pass like this one.

Safety / idempotency:
  * A record is only touched when its current upc still equals "wrong".
    A re-run, or a record already corrected, is skipped — never clobbered.
  * The old UPC is preserved in supersededBarcodes (never discarded).
  * The master is rewritten only if at least one correction applied, and
    only via a temp file that is cross-checked before replacing the original.

Usage (from the funko-upc-community directory):
    python apply-upc-corrections.py --dry-run
    python apply-upc-corrections.py

SPDX-License-Identifier: MIT
Copyright (c) 2026 Chris Ahrendt
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

DEF_MASTER      = "funko_catalog_master.json"
DEF_CORRECTIONS = "upc_corrections.json"


def norm(upc) -> str:
    """Digits only, leading zeros stripped — matches the JS tool's norm()."""
    return re.sub(r"\D", "", str(upc or "")).lstrip("0")


def gs1_check_digit_ok(upc: str) -> bool:
    """True when a 12-digit UPC-A carries a valid GS1 check digit."""
    d = re.sub(r"\D", "", str(upc or ""))
    if len(d) != 12:
        return False
    total = sum(int(c) * (3 if i % 2 == 0 else 1) for i, c in enumerate(d[:11]))
    return (10 - total % 10) % 10 == int(d[11])


def handle_of(record: dict) -> str:
    """The master keys records by _id ('catalog::<handle>'); the corrections
    file keys them by bare handle. Accept either shape."""
    if record.get("handle"):
        return str(record["handle"])
    doc_id = str(record.get("_id") or "")
    return doc_id.split("::", 1)[1] if "::" in doc_id else doc_id


def main() -> int:
    ap = argparse.ArgumentParser(description="Apply verified UPC corrections to the golden master.")
    ap.add_argument("--master", default=DEF_MASTER)
    ap.add_argument("--corrections", default=DEF_CORRECTIONS)
    ap.add_argument("--dry-run", action="store_true", help="report only; write nothing")
    args = ap.parse_args()

    master_path = Path(args.master)
    corr_path   = Path(args.corrections)

    for p in (master_path, corr_path):
        if not p.is_file():
            print(f"ERROR: {p} not found", file=sys.stderr)
            return 2

    records = json.loads(master_path.read_text(encoding="utf-8"))
    if not isinstance(records, list):
        print("ERROR: master is not a JSON array", file=sys.stderr)
        return 2

    corrections = json.loads(corr_path.read_text(encoding="utf-8")).get("corrections") or []
    if not corrections:
        print("ERROR: corrections file lists no corrections", file=sys.stderr)
        return 2

    # Reject a correction whose target UPC is not a structurally valid UPC-A
    # before touching anything — a typo here would poison the golden master.
    for c in corrections:
        if not gs1_check_digit_ok(c.get("correct", "")):
            print(f"ERROR: {c.get('figure')!r}: correct UPC {c.get('correct')!r} "
                  f"fails the GS1 check digit — refusing to apply any correction",
                  file=sys.stderr)
            return 2

    by_handle: dict[str, list[dict]] = {}
    for r in records:
        by_handle.setdefault(handle_of(r), []).append(r)

    applied = skipped = 0
    for c in corrections:
        handle = c.get("handle", "")
        figure = c.get("figure", handle)
        targets = by_handle.get(handle, [])

        if not targets:
            print(f"  ! not found: {figure} ({handle})", file=sys.stderr)
            skipped += 1
            continue
        if len(targets) > 1:
            print(f"  ! ambiguous: {handle} matches {len(targets)} records — skipping",
                  file=sys.stderr)
            skipped += 1
            continue

        rec = targets[0]
        if norm(rec.get("upc")) != norm(c.get("wrong")):
            print(f"  ~ skip (upc already changed): {figure} now {rec.get('upc')!r}",
                  file=sys.stderr)
            skipped += 1
            continue

        if not args.dry_run:
            superseded = rec.get("supersededBarcodes")
            if not isinstance(superseded, list):
                superseded = []
            old = rec.get("upc")
            if old and old not in superseded:
                superseded.append(old)
            rec["supersededBarcodes"] = superseded
            rec["upc"] = c["correct"]
            rec["upcCorrected"] = True

        print(f"  {figure}: {c.get('wrong')} -> {c.get('correct')}", file=sys.stderr)
        applied += 1

    print(f"applied {applied}, skipped {skipped}" + (" [DRY RUN]" if args.dry_run else ""),
          file=sys.stderr)

    if args.dry_run or applied == 0:
        if applied == 0 and not args.dry_run:
            print("Nothing to do — master left untouched.", file=sys.stderr)
        return 0

    # Write to a temp file, re-read and cross-check it, then replace.
    tmp = master_path.with_suffix(master_path.suffix + ".tmp")
    tmp.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
    verify = json.loads(tmp.read_text(encoding="utf-8"))
    if len(verify) != len(records):
        tmp.unlink(missing_ok=True)
        print("ERROR: round-trip record count mismatch — master left untouched", file=sys.stderr)
        return 2
    for c in corrections:
        hits = [r for r in verify if handle_of(r) == c.get("handle", "")]
        if hits and norm(hits[0].get("upc")) != norm(c["correct"]):
            tmp.unlink(missing_ok=True)
            print(f"ERROR: {c.get('figure')} did not land — master left untouched", file=sys.stderr)
            return 2
    os.replace(tmp, master_path)
    print(f"Wrote {master_path} ({len(verify)} records)", file=sys.stderr)
    print("\nNext: python publish-master.py --version 2026-10", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
