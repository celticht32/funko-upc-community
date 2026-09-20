#!/usr/bin/env python3
"""
rebuild-community-master.py

Rebuilds funko_upc_community.json from the DQ-corrected enrichment catalog
(funkodex_base_catalog.final.json). This is a REBASE, not a merge: the output
replaces the master file wholesale, because merge-deltas.js cannot correct an
existing record (equal source rank falls through to "earlier contributedAt
wins", so June data beats September corrections every time).

Why a rebase was needed (measured against the 2026-06-12 master):
  * 6,168 of 8,219 records (75%) had a CATEGORY in the franchise field
    ("Pop! Vinyl", "Pop! Television") because the old exporter's heuristic
    fell through to series[0]. The catalog has real franchises.
  * 311 records carried raw HTML entities (&amp;) in the name.
  * All 8,219 imageUrl values pointed at images.hobbydb.com, which the app
    can no longer reach.
  * 1,127 catalog titles carry a trailing "#NNN" that duplicates funkoNumber;
    these are stripped, because the number belongs in seriesNumber.

Usage:
    python rebuild-community-master.py \
        --catalog  ..\\funko_enrich\\funkodex_base_catalog.final.json \
        --existing funko_upc_community.json \
        --out      funko_upc_community.NEW.json \
        --report   REBUILD_report.json

Add --drop-orphans to discard existing records absent from the catalog
(default is to carry them over rather than lose data).

SPDX-License-Identifier: MIT
Copyright (c) 2026 Chris Ahrendt
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path

VALID_SOURCES = ("CHANNEL3", "USER_SCAN_CHANNEL3", "USER_SCAN", "USER_MANUAL", "USER_EDIT")
REBUILD_SOURCE = "USER_SCAN"   # enricher-derived, same standing as before


# ── validation ────────────────────────────────────────────────────────────────

def gs1_ok(upc: str) -> bool:
    """GS1 UPC-A check digit. 13-digit EAN passes through unchecked."""
    if not re.fullmatch(r"\d{12,13}", upc):
        return False
    if len(upc) == 13:
        return True
    d = [int(c) for c in upc]
    total = sum(v * (3 if i % 2 == 0 else 1) for i, v in enumerate(d[:11]))
    return (10 - (total % 10)) % 10 == d[11]


def clean_text(value) -> str:
    """Unescape HTML entities, strip tags, collapse whitespace.

    Entities are unescaped repeatedly until stable: some catalog handles are
    double-escaped ("&amp;amp;"), which a single html.unescape() pass leaves
    as a visible "&amp;". Capped so a pathological string cannot spin.
    """
    s = str(value or "")
    for _ in range(5):
        decoded = html.unescape(s)
        if decoded == s:
            break
        s = decoded
    s = re.sub(r"<[^>]*>", "", s)
    return re.sub(r"\s+", " ", s).strip()


TRAILING_NUM = re.compile(r"\s*#\d+\s*$")


def clean_title(value) -> str:
    """Catalog titles sometimes end in '#616', duplicating funkoNumber."""
    return TRAILING_NUM.sub("", clean_text(value)).strip()


# ── catalog mapping ───────────────────────────────────────────────────────────

CATEGORY_PREFIX = re.compile(r"^(Pop!|Pocket Pop!|Vinyl|Chase|Funko|Pint Size)", re.I)


def pick_franchise(rec: dict) -> tuple[str, bool]:
    """Best franchise for a catalog row. Returns (value, is_real_franchise).

    franchiseSuggestion and pcSeries hold true franchises (Star Wars, Friends).
    category and series hold Funko's product lines (Pop! Vinyl) and are only a
    last resort, because that fallback is exactly what corrupted the old file.
    """
    for key in ("franchiseSuggestion", "pcSeries"):
        v = clean_text(rec.get(key))
        if v:
            return v, True
    for key in ("category", "series"):
        v = clean_text(rec.get(key))
        if v:
            return v, False
    return "", False


def populated_score(rec: dict) -> int:
    """Used to pick a winner when one UPC appears on several catalog rows."""
    keys = ("funkoNumber", "imageUrl", "franchiseSuggestion", "pcSeries",
            "retailPrice", "category", "series", "exclusiveRetailer",
            "releaseDate", "handle", "title")
    return sum(1 for k in keys if rec.get(k) not in (None, "", []))


def to_community(rec: dict, today: str) -> tuple[dict | None, str, bool]:
    """Map a catalog row to a schema-v1 community record.

    Returns (record_or_None, reason_if_rejected, franchise_is_real).
    """
    upc = re.sub(r"\D", "", str(rec.get("upc") or ""))
    if not upc:
        return None, "no upc", False
    if not gs1_ok(upc):
        return None, "bad upc", False

    handle = clean_text(rec.get("handle"))
    if handle.endswith(".html"):
        handle = handle[:-5]
    if not handle:
        return None, "no handle", False

    name = clean_title(rec.get("title"))
    if len(name) < 2:
        return None, "no name", False
    if len(name) > 200:
        name = name[:200].rstrip()

    franchise, real = pick_franchise(rec)
    if not franchise:
        return None, "no franchise", False

    out = {
        "upc": upc,
        "handle": handle[:100],
        "name": name,
        "franchise": franchise,
        "schemaVersion": 1,
        "source": REBUILD_SOURCE,
        "contributedAt": today,
    }

    category = clean_text(rec.get("category")) or clean_text(rec.get("series"))
    if category:
        out["category"] = category

    num = clean_text(rec.get("funkoNumber") or rec.get("seriesNumber")).lstrip("#").strip()
    if num:
        out["seriesNumber"] = f"#{int(num)}" if num.isdigit() else f"#{num}"

    try:
        price = float(re.sub(r"[^0-9.]", "", str(rec.get("retailPrice") or "")) or 0)
        if price > 0:
            out["retailPrice"] = price
    except ValueError:
        pass

    img = clean_text(rec.get("imageUrl"))
    if img.startswith("http"):
        out["imageUrl"] = img

    retailer = clean_text(rec.get("exclusiveRetailer"))
    if retailer:
        out["exclusiveRetailer"] = retailer

    for flag in ("isVaulted", "isChase", "isExclusive"):
        v = rec.get(flag)
        if isinstance(v, str):
            v = v.strip().lower() in ("true", "1", "yes")
        if v is True:
            out[flag] = True

    return out, "", real


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description="Rebuild the community master from the corrected catalog.")
    ap.add_argument("--catalog", required=True)
    ap.add_argument("--existing", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--report", default="REBUILD_report.json")
    ap.add_argument("--keep-orphan-handles", action="store_true",
                    help="do not clean carried-over handles (use once the app has shipped)")
    ap.add_argument("--drop-orphans", action="store_true",
                    help="discard existing records absent from the catalog (default: carry them over)")
    args = ap.parse_args()

    today = date.today().isoformat()

    catalog = json.loads(Path(args.catalog).read_text(encoding="utf-8"))
    existing = json.loads(Path(args.existing).read_text(encoding="utf-8"))
    if not isinstance(catalog, list) or not isinstance(existing, list):
        print("ERROR: both inputs must be JSON arrays", file=sys.stderr)
        return 1
    print(f"catalog rows: {len(catalog)}   existing master: {len(existing)}")

    # ── 1. collapse duplicate UPCs, keeping the most complete row ─────────────
    best: dict[str, dict] = {}
    for rec in catalog:
        upc = re.sub(r"\D", "", str(rec.get("upc") or ""))
        if not upc:
            continue
        cur = best.get(upc)
        if cur is None or populated_score(rec) > populated_score(cur):
            best[upc] = rec
    print(f"unique catalog UPCs: {len(best)}")

    # ── 1b. catalog rows that disagree with themselves ───────────────────────
    # 226 UPCs appear on several catalog rows carrying DIFFERENT funkoNumbers.
    # "Trust the catalog" is undefined for these, so they are reported rather
    # than silently resolved by whichever row happened to score highest.
    from collections import defaultdict
    numbers: dict[str, set] = defaultdict(set)
    for rec in catalog:
        upc = re.sub(r"\D", "", str(rec.get("upc") or ""))
        num = str(rec.get("funkoNumber") or "").strip().lstrip("0")
        if upc and num:
            numbers[upc].add(num)
    self_conflicts = [
        {"upc": u,
         "title": clean_title(best[u].get("title")) if u in best else "",
         "funkoNumbers": sorted(v),
         "chosen": str(best[u].get("funkoNumber") or "") if u in best else ""}
        for u, v in numbers.items() if len(v) > 1
    ]
    print(f"catalog UPCs whose duplicate rows disagree on funkoNumber: {len(self_conflicts)}")

    # ── 2. map ────────────────────────────────────────────────────────────────
    out: dict[str, dict] = {}
    rejects: Counter[str] = Counter()
    real_franchise = 0
    for upc, rec in best.items():
        mapped, why, real = to_community(rec, today)
        if mapped is None:
            rejects[why] += 1
            continue
        out[mapped["upc"]] = mapped
        real_franchise += bool(real)
    print(f"mapped: {len(out)}   rejected: {sum(rejects.values())} {dict(rejects)}")
    print(f"  with a real franchise (not a product line): {real_franchise}")

    # ── 2b. carry forward old values the catalog simply does not have ────────
    # The catalog wins wherever it has data, but it carries exclusiveRetailer
    # for only 2,694 rows while the old master had it for 2,257 of its 8,219.
    # Without this, 528 overlapping records silently lose "Funko Hot Topic",
    # "Funko Barnes & Noble" and the like. imageUrl is deliberately NOT carried
    # forward: every old value pointed at a host the app can no longer reach.
    PRESERVE = ("exclusiveRetailer", "retailPrice", "seriesNumber", "category")
    old_by_upc = {re.sub(r"\D", "", str(r.get("upc") or "")): r for r in existing}
    restored: Counter[str] = Counter()
    for upc, rec in out.items():
        prev = old_by_upc.get(upc)
        if not prev:
            continue
        for key in PRESERVE:
            if rec.get(key) in (None, "", []) and prev.get(key) not in (None, "", []):
                rec[key] = clean_text(prev[key]) if isinstance(prev[key], str) else prev[key]
                restored[key] += 1
    if restored:
        print(f"carried forward from the old master where the catalog was empty: {dict(restored)}")

    # ── 3. orphans — existing records the catalog does not cover ──────────────
    carried = 0
    orphan_upcs: list[str] = []
    for rec in existing:
        upc = re.sub(r"\D", "", str(rec.get("upc") or ""))
        if not upc or upc in out:
            continue
        orphan_upcs.append(upc)
        if args.drop_orphans:
            continue
        kept = dict(rec)
        kept["name"] = clean_text(kept.get("name"))
        kept["franchise"] = clean_text(kept.get("franchise"))
        for k in ("category", "exclusiveRetailer"):
            if k in kept:
                kept[k] = clean_text(kept[k])
        # The handle is an identity key: the app stores catalog::{handle}, so
        # rewriting one would make an existing install create a duplicate
        # document rather than update the record. Safe to clean only while
        # nothing has shipped (pre-Play-Store); --keep-orphan-handles preserves
        # the original spelling once real installs exist in the wild.
        if not args.keep_orphan_handles:
            h = clean_text(kept.get("handle"))
            if h.endswith(".html"):
                h = h[:-5]
            if h:
                kept["handle"] = h[:100]
        out[upc] = kept
        carried += 1
    print(f"orphans (in old master, not in catalog): {len(orphan_upcs)}   "
          f"{'dropped' if args.drop_orphans else f'carried over: {carried}'}")

    # ── 4. final validation — same rules validate-schema.js enforces ──────────
    final, invalid = [], []
    for rec in out.values():
        problems = []
        if not re.fullmatch(r"\d{12,13}", str(rec.get("upc", ""))):
            problems.append("upc")
        if not rec.get("handle"):
            problems.append("handle")
        if not rec.get("name") or len(str(rec["name"])) < 2:
            problems.append("name")
        if not rec.get("franchise"):
            problems.append("franchise")
        if rec.get("schemaVersion") != 1:
            problems.append("schemaVersion")
        if not rec.get("contributedAt"):
            problems.append("contributedAt")
        if rec.get("source") not in VALID_SOURCES:
            problems.append("source")
        (invalid if problems else final).append(
            {"upc": rec.get("upc"), "problems": problems} if problems else rec)

    final.sort(key=lambda r: (str(r.get("franchise", "")), str(r.get("name", ""))))
    if invalid:
        print(f"WARNING: {len(invalid)} record(s) failed final validation and were excluded")

    Path(args.out).write_text(json.dumps(final, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # ── 5. change report ──────────────────────────────────────────────────────
    old = {re.sub(r"\D", "", str(r.get("upc") or "")): r for r in existing}
    new = {r["upc"]: r for r in final}
    changed = [
        {"upc": u,
         "old": {k: old[u].get(k) for k in ("name", "franchise", "seriesNumber", "handle")},
         "new": {k: new[u].get(k) for k in ("name", "franchise", "seriesNumber", "handle")}}
        for u in set(old) & set(new)
        if any(str(old[u].get(k) or "") != str(new[u].get(k) or "")
               for k in ("name", "franchise", "seriesNumber", "handle"))
    ]
    report = {
        "generatedAt": today,
        "catalogRows": len(catalog),
        "uniqueCatalogUpcs": len(best),
        "oldMasterRecords": len(existing),
        "newMasterRecords": len(final),
        "addedUpcs": len(set(new) - set(old)),
        "removedUpcs": len(set(old) - set(new)),
        "changedRecords": len(changed),
        "rejectedFromCatalog": dict(rejects),
        "invalidExcluded": invalid[:200],
        "orphans": {"count": len(orphan_upcs), "action": "dropped" if args.drop_orphans else "carried"},
        "sampleChanges": changed[:100],
        "catalogSelfConflicts": len(self_conflicts),
    }
    review_path = Path(args.report).with_name("REVIEW_catalog_number_conflicts.json")
    review_path.write_text(json.dumps(self_conflicts, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    Path(args.report).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"\nwrote {args.out}  ({len(final)} records)")
    print(f"wrote {args.report}")
    print(f"wrote {review_path}  ({len(self_conflicts)} UPCs needing a human decision)")
    print(f"  added {report['addedUpcs']}   removed {report['removedUpcs']}   changed {report['changedRecords']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
