#!/usr/bin/env python3
r"""
publish-master.py — produce the network publish artifacts for FunkoDex.

Reads the golden master catalog and writes the two files devices fetch:

    funko_catalog_master.json.gz   the complete catalog, gzipped
    manifest.json                  version, count, size and SHA-256 gate

See FunkoDex_Catalog_Distribution_Architecture_v1.3.docx, Section 4.

DESIGN NOTES

  The record shape here is IDENTICAL to the bundled asset produced by
  funko_enrich/build_catalog_asset.py, and the validation below mirrors its
  checks. That is deliberate: the client must parse the network master and the
  bundled asset with one code path. If you change the shape in one place, change
  it in both, or installs will diverge depending on whether they ever refreshed.

  The extension is .gz, NOT .gz_. The trailing underscore exists only for files
  bundled under app/src/main/assets, where AGP's asset merger decompresses
  anything ending .gz and strips the extension. Nothing in the build system
  touches a file fetched over the network, so the plain extension is correct
  here. Do not "fix" this to match the asset.

  The manifest's sha256 covers the GZIPPED bytes, so the client verifies before
  it inflates. Hashing the decompressed JSON would mean inflating an unverified
  archive first, which is the zip-bomb surface.

  Both outputs are written atomically via temporary files and only moved into
  place once BOTH have been produced and re-read successfully. A manifest that
  disagrees with the payload is worse than no publish at all: every client would
  download the gzip, fail the checksum, discard it, and back off.

USAGE (Windows)
    py publish-master.py --version 2026-10
    py publish-master.py --version 2026-10 --dry-run
    py publish-master.py --version 2026-10 --master funko_catalog_master.json

SPDX-License-Identifier: MIT
Copyright (c) 2026 Chris Ahrendt
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

DEF_MASTER   = "funko_catalog_master.json"
DEF_PAYLOAD  = "funko_catalog_master.json.gz"
DEF_MANIFEST = "manifest.json"

SCHEMA_VERSION   = 2
MIN_RECORD_COUNT = 20_000      # client sanity floor; also refuses publish below this
UNRESOLVED       = "__unresolved__"
BOOL_FIELDS      = ("isExclusive", "isChase", "isVaulted", "marketValueIsApproximate")
VERSION_RE       = re.compile(r"^\d{4}-\d{2}$")


# ── validation ────────────────────────────────────────────────────────────────

def validate(records: list) -> list[str]:
    """Mirror of build_catalog_asset.py's checks. Returns a list of problems."""
    problems: list[str] = []

    if not isinstance(records, list):
        return ["master is not a JSON array"]

    # Collection records must never ship.
    types = Counter(r.get("type") for r in records if isinstance(r, dict))
    owned = types.get("funko", 0)
    if owned:
        problems.append(f"{owned} collection record(s) (type=funko) present — these must NOT ship")

    # Usable document id.
    no_id = sum(1 for r in records
                if not (str(r.get("_id") or "").strip() or str(r.get("handle") or "").strip()))
    if no_id:
        problems.append(f"{no_id} record(s) with neither _id nor handle — the loader skips these")

    # Title: the loader drops records without one, so this is silent data loss.
    no_title = sum(1 for r in records if not str(r.get("title") or "").strip())
    if no_title:
        problems.append(f"{no_title} record(s) with no title — the loader skips these")

    # Booleans must be real booleans; Kotlin reads a string as false, silently.
    for field in BOOL_FIELDS:
        kinds = Counter(type(r[field]).__name__ for r in records if field in r)
        bad = sum(n for k, n in kinds.items() if k != "bool")
        if bad:
            problems.append(f"{field}: {bad} non-boolean value(s) {dict(kinds)} — a string reads as false")

    # series must be a string (base-catalog shape), not the enricher's list.
    listy = sum(1 for r in records if isinstance(r.get("series"), list))
    if listy:
        problems.append(f"{listy} record(s) carry a series LIST — the app expects a string")

    # Duplicate document ids would make the upsert order-dependent.
    ids = [str(r.get("_id") or r.get("handle") or "").strip() for r in records]
    dupes = [i for i, n in Counter(i for i in ids if i).items() if n > 1]
    if dupes:
        problems.append(f"{len(dupes)} duplicate document id(s), e.g. {dupes[:3]}")

    # The floor. A master below this would empty devices via the sweep.
    if len(records) < MIN_RECORD_COUNT:
        problems.append(f"only {len(records)} records — below the {MIN_RECORD_COUNT} floor; "
                        f"refusing to publish a master that would gut every install")

    return problems


def report(records: list) -> None:
    types = Counter(r.get("type") for r in records if isinstance(r, dict))
    with_upc = sum(1 for r in records if str(r.get("upc") or "").strip())
    with_img = sum(1 for r in records if str(r.get("imageUrl") or "").strip())
    sentinel = sum(1 for r in records if str(r.get("funkoNumber") or "") == UNRESOLVED)
    print(f"  records      : {len(records)}")
    print(f"  types        : {dict(types)}")
    print(f"  with upc     : {with_upc}")
    print(f"  with image   : {with_img}")
    print(f"  funkoNumber == {UNRESOLVED!r} : {sentinel} (loader omits the field — fine)")


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description="Build the network publish artifacts.")
    ap.add_argument("--master", default=DEF_MASTER)
    ap.add_argument("--payload", default=DEF_PAYLOAD)
    ap.add_argument("--manifest", default=DEF_MANIFEST)
    ap.add_argument("--version", help="catalog version, YYYY-MM (default: current UTC month)")
    ap.add_argument("--dry-run", action="store_true", help="validate and report; write nothing")
    args = ap.parse_args()

    version = args.version or datetime.now(timezone.utc).strftime("%Y-%m")
    if not VERSION_RE.match(version):
        print(f"ERROR: --version must be YYYY-MM, got {version!r}", file=sys.stderr)
        return 1

    master_path = Path(args.master)
    if not master_path.exists():
        print(f"ERROR: {master_path} not found", file=sys.stderr)
        return 1

    print(f"loading {master_path} ...")
    try:
        records = json.loads(master_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"ERROR: {master_path} is not valid JSON - {exc}", file=sys.stderr)
        return 1
    report(records)

    print("\nvalidating ...")
    problems = validate(records)
    if problems:
        print(f"  {len(problems)} problem(s):")
        for prob in problems:
            print(f"    - {prob}")
        print("\n  NOT publishing. Fix these first.")
        return 1
    print("  all checks passed")

    # ── compress ─────────────────────────────────────────────────────────────
    raw = json.dumps(records, ensure_ascii=False).encode("utf-8")
    # mtime=0 so identical input produces identical bytes — a rebuild with no
    # data change should not churn the checksum or the git blob.
    payload = gzip.compress(raw, compresslevel=9, mtime=0)
    digest = hashlib.sha256(payload).hexdigest()

    print(f"\n  uncompressed : {len(raw)/1e6:.1f} MB")
    print(f"  gzipped      : {len(payload)/1e6:.1f} MB  ({len(payload)*100//len(raw)}%)")
    print(f"  sha256       : {digest}")

    manifest = {
        "schemaVersion":   SCHEMA_VERSION,
        "catalogVersion":  version,
        "recordCount":     len(records),
        "sha256":          digest,
        "sizeBytes":       len(payload),
        "publishedAt":     datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "minRecordCount":  MIN_RECORD_COUNT,
    }

    if args.dry_run:
        print("\n--dry-run: nothing written. Manifest would be:")
        print(json.dumps(manifest, indent=2))
        return 0

    # ── write atomically ─────────────────────────────────────────────────────
    # Both temporaries are produced and verified BEFORE either is moved into
    # place, so a failure part-way cannot leave a manifest describing a payload
    # that is not there.
    payload_path  = Path(args.payload)
    manifest_path = Path(args.manifest)
    tmp_payload   = payload_path.with_suffix(payload_path.suffix + ".tmp")
    tmp_manifest  = manifest_path.with_suffix(manifest_path.suffix + ".tmp")

    try:
        tmp_payload.write_bytes(payload)
        tmp_manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

        # Read both back and prove they agree before committing either.
        check_bytes = tmp_payload.read_bytes()
        if hashlib.sha256(check_bytes).hexdigest() != digest:
            raise RuntimeError("payload failed its own checksum after write")
        check_records = json.loads(gzip.decompress(check_bytes).decode("utf-8"))
        if len(check_records) != len(records):
            raise RuntimeError(f"round-trip lost records: {len(check_records)} != {len(records)}")
        check_manifest = json.loads(tmp_manifest.read_text(encoding="utf-8"))
        if check_manifest["sha256"] != digest or check_manifest["recordCount"] != len(records):
            raise RuntimeError("manifest does not describe the payload")

        tmp_payload.replace(payload_path)
        tmp_manifest.replace(manifest_path)
    except Exception as exc:
        for tmp in (tmp_payload, tmp_manifest):
            tmp.unlink(missing_ok=True)
        print(f"\nERROR: publish failed, nothing changed - {exc}", file=sys.stderr)
        return 1

    print(f"\n  wrote {payload_path}")
    print(f"  wrote {manifest_path}")
    print(f"\nVerified: gzip round-trips to {len(check_records)} records and matches the manifest.")
    print("\nNext:")
    print("  git add -A")
    print(f'  git commit -m "Publish catalog {version} - {len(records)} records"')
    print(f"  git tag catalog-{version}")
    print("  git push --tags")
    return 0


if __name__ == "__main__":
    sys.exit(main())
