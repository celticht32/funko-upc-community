# FunkoDex Community Catalog

The published catalog for the **FunkoDex** Android app, plus the UPC contributions
that improve it. Maintained by Celtic Heart Steamworks.

## What this is

This repository is the **golden master**: the complete, corrected Funko catalog that
every FunkoDex install converges on. The app ships with a snapshot bundled in the APK
so it works offline from first launch, then refreshes from here monthly.

All judgement about what belongs in the catalog happens *here*, once, before publish —
visible in a git diff. Devices do not adjudicate; they replace. See
`FunkoDex_Catalog_Distribution_Architecture_v1.3.docx` in the app repository.

## Repository contents

| File / folder | Purpose |
|---|---|
| `funko_catalog_master.json` | **The golden master.** Full catalog, human-readable, the reviewable artifact |
| `funko_catalog_master.json.gz` | What devices download. Pinned by SHA-256 in the manifest |
| `manifest.json` | Version, record count, size and checksum — the gate a device checks first |
| `publish-master.py` | Validates the master and produces the two files above |
| `funko_upc_community.json` | **Legacy (schema v1).** The UPC overlay older app builds fetch — see *Transition* |
| `deltas/` | Contribution batches written by the Cloudflare Worker |
| `merge-state.json` | Which delta files the merge has already consumed |
| `merge-deltas.js` | Folds deltas into the v1 master (GitHub Actions, weekly) |
| `validate-schema.js` | Schema gate — run after every merge |
| `rebuild-community-master.py` | Rebuilds the v1 master from the corrected catalog |
| `quarterly-rebase.py` | Quality pass — GS1 check digits, junk detection |
| `SCHEMA.md` | Field reference for both schema versions |

## How data flows

**Outbound — a contribution leaves a device**

```
User scans a UPC the catalog does not know and matches it by hand
    │
    ▼  saved locally as a contrib:: document (Couchbase Lite)
    ▼  daily, only if the user opted in under Settings
GitHubUploadWorker POSTs the pending batch to the Cloudflare Worker
    │
    ▼  the Worker holds the GitHub token, so the APK never does
Worker validates each record, rate-limits by device, writes deltas/
```

**Inbound — the catalog reaches a device**

```
Maintainer merges deltas, re-validates, runs publish-master.py
    │
    ▼  funko_catalog_master.json.gz + manifest.json committed and pushed
Device fetches manifest.json (~250 bytes, monthly)
    │
    ▼  version unchanged? stop. This is the common case.
Device downloads the gzip, verifies SHA-256 BEFORE inflating,
applies it wholesale, then sweeps records the master no longer carries
```

A failed refresh changes nothing on the device: the partial download is deleted, the
version marker is not written, and the next attempt backs off 6h → 24h → 72h.

## Transition: two masters, for now

`funko_upc_community.json` (schema v1, a UPC-only overlay) is what shipped app builds
fetch. `funko_catalog_master.json` (schema v2, the full catalog) is what the current
code fetches. **Keep both until no install is running a pre-v1.3 build**, or older
installs lose their update feed entirely. Once the new build is the floor on Google
Play, v1 and its merge tooling can be retired.

## Privacy

Every record here describes a product, not a person. Ownership, price paid, condition,
notes and photos never leave the device and are not in this repository in any form.

The only device identifier the Worker sees is a random install UUID, used for
rate-limiting and never written to this repo.

## Merge priority

When contributions disagree about the same UPC:

| Priority | Source | Meaning |
|---|---|---|
| 3 (highest) | `CHANNEL3` | Retrieved from the Channel3 structured API |
| 2 | `USER_SCAN_CHANNEL3` | User scan, confirmed against Channel3 |
| 1 | `USER_SCAN`, `USER_MANUAL`, `USER_EDIT` | User-asserted — never outranks confirmed data |

Within the same rank: more populated fields win, then the earlier `contributedAt`.

This ordering applies **at merge time only**. The device does not evaluate source
precedence — it trusts the published master as-is.

## Publishing

```
python publish-master.py --version 2026-10 --dry-run   # validate, write nothing
python publish-master.py --version 2026-10
git add -A
git commit -m "Publish catalog 2026-10"
git tag catalog-2026-10
git push --follow-tags
```

`publish-master.py` refuses to emit a master that fails validation or falls below the
20,000-record floor. That floor matters: the client sweep deletes records the master
omits, so a short master would gut every install.

**Do not let git normalize the publish artifacts.** `.gitattributes` marks `*.gz` binary
and sets `-text` on the master and manifest. A byte-level rewrite would break the
checksum on every device, and it would look like a client bug.

## Quarterly rebase

```
python quarterly-rebase.py            # local, writes files for review
python quarterly-rebase.py --ci       # GitHub Actions mode
```

Runs automatically on 1 January, April, July and October, and opens a PR when records
are flagged.

---

*Maintained by Celtic Heart Steamworks. Contributions come through the FunkoDex Android app.*
