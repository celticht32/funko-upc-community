#!/usr/bin/env python3
r"""
fix-titles.py — strip the duplicated pop number out of catalog titles.

THE DEFECT
  13,385 of 26,655 master records carry the pop number twice: once at the end
  of `title` and again in `funkoNumber`:

      title       "Marty McFly #61"
      funkoNumber "61"

  Every one of those titles renders in the app with a redundant "#61" hanging
  off it. It is the most visible data defect in the catalog and it affects half
  of every user's browse list.

WHY IT IS SAFE TO STRIP
  13,382 of the 13,385 already hold the identical number in funkoNumber, so
  removing it from the title discards nothing — the value survives in the field
  that is actually meant to carry it.

THE THREE EXCEPTIONS
  Three records embed a COMIC issue number as well as a pop number:

      "Iron Man Tales of Suspense #39 #238"   funkoNumber "39"

  Here #39 belongs to the title (Tales of Suspense #39 is the issue Iron Man
  debuted in) and #238 is the Funko number. The enricher captured the wrong one.
  This script strips only the TRAILING number, which leaves those titles
  correct, and reports the funkoNumber discrepancy rather than guessing — a
  wrong pop number is worse than an ugly one.

USAGE (Windows)
    py fix-titles.py --dry-run
    py fix-titles.py

SPDX-License-Identifier: MIT
Copyright (c) 2026 Chris Ahrendt
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

MASTER = "funko_catalog_master.json"
TRAILING = re.compile(r"\s*#(\d+)\s*$")


def main() -> int:
    ap = argparse.ArgumentParser(description="Strip duplicated pop numbers from catalog titles.")
    ap.add_argument("--master", default=MASTER)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    path = Path(args.master)
    if not path.exists():
        print(f"ERROR: {path} not found", file=sys.stderr)
        return 1

    records = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(records, list):
        print(f"ERROR: {path} must be a JSON array", file=sys.stderr)
        return 1
    print(f"master: {len(records)} records")

    stripped = 0
    mismatched: list[dict] = []
    emptied = 0

    for r in records:
        title = str(r.get("title") or "")
        m = TRAILING.search(title)
        if not m:
            continue
        trailing = m.group(1)

        # Some titles carry the number TWICE ("Ellie #1844 #1844"), so strip
        # repeatedly until stable. A single pass leaves one behind and the
        # defect looks half-fixed. Capped so a pathological title cannot spin.
        new_title = title
        for _ in range(5):
            stripped_once = TRAILING.sub("", new_title).strip()
            if stripped_once == new_title or len(stripped_once) < 2:
                break
            new_title = stripped_once

        # Nothing actually changed: the loop refused to strip because what
        # remains would be under two characters. These are the degenerate
        # one-letter titles ("V #284", "L #218") that need expanding upstream
        # in funko_enrich - "V (BTS)", "L (Death Note)". Keeping the number is
        # better than a bare "V", so leave them and say so.
        if new_title == title:
            emptied += 1
            continue

        fn = str(r.get("funkoNumber") or "").strip()
        if fn and fn.lstrip("0") != trailing.lstrip("0"):
            mismatched.append({
                "_id": r.get("_id"), "title": title,
                "funkoNumber": fn, "trailingNumber": trailing,
                "newTitle": new_title,
            })
        elif not fn:
            # Nothing would carry the number after the strip — put it where it belongs.
            r["funkoNumber"] = trailing

        r["title"] = new_title
        stripped += 1

    print(f"  titles stripped                 : {stripped}")
    print(f"  left alone (title is a single letter - fix upstream): {emptied}")
    print(f"  funkoNumber disagrees with the stripped number: {len(mismatched)}")
    for x in mismatched:
        print(f"      {x['title']!r} -> {x['newTitle']!r}  funkoNumber={x['funkoNumber']!r} "
              f"but title said #{x['trailingNumber']}")

    if args.dry_run:
        print("\n--dry-run: nothing written")
        return 0

    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
    check = json.loads(tmp.read_text(encoding="utf-8"))
    if len(check) != len(records):
        tmp.unlink(missing_ok=True)
        print("ERROR: round-trip lost records — master untouched", file=sys.stderr)
        return 1
    tmp.replace(path)
    print(f"\nwrote {path}")

    if mismatched:
        review = path.with_name("REVIEW_title_number_mismatch.json")
        review.write_text(json.dumps(mismatched, indent=2, ensure_ascii=False) + "\n",
                          encoding="utf-8")
        print(f"wrote {review} — funkoNumber NOT changed; decide these yourself")

    print("\nNext: py publish-master.py --version YYYY-MM")
    return 0


if __name__ == "__main__":
    sys.exit(main())
