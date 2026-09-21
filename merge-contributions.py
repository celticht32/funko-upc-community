#!/usr/bin/env python3
r"""
merge-contributions.py — fold community contributions into the golden master.

This is the join between the two halves of the system: the Cloudflare Worker
writes schema-v1 contribution records into deltas/, and the app fetches the
schema-v2 golden master. Without this step contributions accumulate in deltas/
and never reach a single device — the loop LOOKS closed and is not.

WHAT IT DOES
  * reads every deltas/*.json not already recorded in contrib-merge-state.json
  * maps each schema-v1 contribution onto the v2 catalog record shape
  * adds records whose handle the master does not have
  * fills BLANK fields on records it does have
  * never overwrites a populated catalog field with a contributed value

WHY FILL-ONLY, NOT OVERWRITE
  The master is curated; contributions are user-asserted and unreviewed. A
  contribution that disagrees with the catalog is far more likely to be wrong
  than right, and a wrong value applied wholesale reaches every install on the
  next refresh. Gaps are the safe thing to fill. Disagreements are reported for
  you to adjudicate, not silently resolved.

PROVENANCE AND THE SWEEP
  Merged records are written with source = "ENRICHED", the same as every other
  master record. That is deliberate and load-bearing: the client sweep only
  deletes catalog documents whose source is ENRICHED, so a contributed record
  carrying "USER_MANUAL" would be permanently immune to removal and would
  linger on devices forever after you dropped it from the master.
  The original provenance is preserved in `contributedSource` instead.

USAGE (Windows)
    py merge-contributions.py --dry-run
    py merge-contributions.py

SPDX-License-Identifier: MIT
Copyright (c) 2026 Chris Ahrendt
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from collections import Counter
from datetime import date
from pathlib import Path

MASTER      = "funko_catalog_master.json"
DELTAS      = "deltas"
STATE       = "contrib-merge-state.json"
MIN_RECORDS = 20_000
ASSET_SOURCE = "ENRICHED"

# contribution field -> master field. Anything not listed is dropped.
FIELD_MAP = {
    "name":              "title",
    "category":          "category",
    "retailPrice":       "retailPrice",
    "isVaulted":         "isVaulted",
    "isChase":           "isChase",
    "isExclusive":       "isExclusive",
    "exclusiveRetailer": "exclusiveRetailer",
    "imageUrl":          "imageUrl",
}


def blank(v) -> bool:
    return v is None or v == "" or v == [] or v == {}


def norm_handle(h: str) -> str:
    h = str(h or "").strip()
    return h[:-5] if h.endswith(".html") else h


def to_master_record(c: dict, today: str) -> dict:
    """Map a schema-v1 contribution onto the v2 catalog record shape."""
    handle = norm_handle(c.get("handle"))
    rec = {
        "_id":    f"catalog::{handle}",
        "handle": handle,
        "type":   "catalog",
        "title":  str(c.get("name") or "").strip(),
        "upc":    re.sub(r"\D", "", str(c.get("upc") or "")),
        # ENRICHED so the client sweep can manage it like any other record.
        "source": ASSET_SOURCE,
        # ...with the real provenance kept alongside.
        "contributedSource": c.get("source"),
        "contributedAt":     c.get("contributedAt") or today,
    }
    # The contribution's "franchise" is the real IP (Star Wars, Twin Peaks).
    # In the master that lives in franchiseSuggestion; `series` is the Funko
    # product line and must not be overwritten with an IP name.
    fr = str(c.get("franchise") or "").strip()
    if fr:
        rec["franchiseSuggestion"] = fr
    num = str(c.get("seriesNumber") or "").lstrip("#").strip()
    if num:
        rec["funkoNumber"] = num
    for src, dst in FIELD_MAP.items():
        v = c.get(src)
        if not blank(v) and v is not False and v != 0:
            rec[dst] = v
    return rec


def main() -> int:
    ap = argparse.ArgumentParser(description="Fold contributions into the golden master.")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--reprocess", action="store_true",
                    help="ignore the state file and re-read every delta")
    args = ap.parse_args()

    root = Path(args.repo).resolve()
    master_path = root / MASTER
    if not master_path.exists():
        print(f"ERROR: {master_path} not found", file=sys.stderr)
        return 1

    master = json.loads(master_path.read_text(encoding="utf-8"))
    if not isinstance(master, list):
        print(f"ERROR: {MASTER} must be a JSON array", file=sys.stderr)
        return 1

    state_path = root / STATE
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() \
        else {"processedFiles": []}
    processed = set() if args.reprocess else set(state.get("processedFiles", []))

    by_handle = {}
    by_upc = {}
    for r in master:
        h = norm_handle(r.get("handle") or str(r.get("_id", "")).replace("catalog::", ""))
        if h:
            by_handle[h.lower()] = r
        u = re.sub(r"\D", "", str(r.get("upc") or ""))
        if u:
            by_upc.setdefault(u, r)
    print(f"master: {len(master)} records ({len(by_upc)} with a UPC)")

    delta_files = sorted(
        p for p in (root / DELTAS).glob("*.json")
        if p.name not in processed and p.name != ".gitkeep"
    )
    if not delta_files:
        print("no new contribution files")
        return 0
    print(f"contribution files to merge: {len(delta_files)}")

    today = date.today().isoformat()
    added = 0
    filled: Counter[str] = Counter()
    unchanged = 0
    conflicts: list[dict] = []
    merged_files: list[Path] = []

    for path in delta_files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        records = payload if isinstance(payload, list) else payload.get("contributions", [])
        # The June enricher delta is schema-v1 bulk data, not a user contribution,
        # and its 9,050 records would swamp this report. It is already reflected
        # in the master via the enrichment pipeline.
        if path.name.startswith("enricher-"):
            print(f"  skipping {path.name} (enricher bulk export, not a contribution)")
            merged_files.append(path)
            continue

        for c in records:
            handle = norm_handle(c.get("handle"))
            upc = re.sub(r"\D", "", str(c.get("upc") or ""))
            if not handle or not upc:
                continue
            mapped = to_master_record(c, today)
            existing = by_handle.get(handle.lower()) or by_upc.get(upc)

            if existing is None:
                master.append(mapped)
                by_handle[handle.lower()] = mapped
                by_upc.setdefault(upc, mapped)
                added += 1
                continue

            touched = False
            for k, v in mapped.items():
                if k in ("_id", "handle", "type", "source", "contributedSource", "contributedAt"):
                    continue
                if blank(existing.get(k)):
                    existing[k] = v
                    filled[k] += 1
                    touched = True
                elif str(existing.get(k)).strip() != str(v).strip():
                    # Populated and different. The catalog wins; you decide later.
                    conflicts.append({
                        "upc": upc, "handle": handle, "field": k,
                        "master": existing.get(k), "contributed": v,
                    })
            if touched:
                existing.setdefault("contributedSource", c.get("source"))
            else:
                unchanged += 1
        merged_files.append(path)

    print(f"\n  added     {added} new record(s)")
    print(f"  filled    {sum(filled.values())} blank field(s) {dict(filled) if filled else ''}")
    print(f"  unchanged {unchanged} (master already had everything)")
    print(f"  conflicts {len(conflicts)} (master kept — see REVIEW_contribution_conflicts.json)")

    if len(master) < MIN_RECORDS:
        print(f"\nERROR: master would hold {len(master)}, below the {MIN_RECORDS} floor. "
              f"Refusing to write.", file=sys.stderr)
        return 1

    if args.dry_run:
        print("\n--dry-run: nothing written")
        return 0

    tmp = master_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(master, ensure_ascii=False), encoding="utf-8")
    check = json.loads(tmp.read_text(encoding="utf-8"))
    if len(check) != len(master):
        tmp.unlink(missing_ok=True)
        print("ERROR: round-trip lost records — master untouched", file=sys.stderr)
        return 1
    tmp.replace(master_path)
    print(f"\nwrote {master_path} ({len(master)} records)")

    (root / "REVIEW_contribution_conflicts.json").write_text(
        json.dumps(conflicts, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    state["processedFiles"] = sorted(set(state.get("processedFiles", [])) |
                                     {p.name for p in merged_files})
    state["lastMergedAt"] = today
    state["masterRecords"] = len(master)
    state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {state_path}")
    print("\nNext: py publish-master.py --version YYYY-MM")
    return 0


if __name__ == "__main__":
    sys.exit(main())
