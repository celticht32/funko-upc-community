# FunkoDex Community UPC Database

Open-source UPC → Funko product mapping database, built collaboratively
by FunkoDex app users and maintained by Celtic Heart Steamworks.

## What this is

The [Kenny Chan Funko Pop dataset](https://github.com/kennymkchan/funko-pop-data)
contains 23,940+ Funko records with names and images but **zero UPC codes**.
This repository adds the UPC layer on top, contributed anonymously by
FunkoDex users who scan their physical collections.

## Repository contents

| File / Folder | Purpose |
|---|---|
| `funko_upc_community.json` | **Master file** — what the app downloads each refresh cycle |
| `deltas/` | Daily delta files written by the Cloudflare Worker (one per device upload) |
| `merge-state.json` | Tracks which delta files have been processed by the weekly merge |
| `merge-deltas.js` | Weekly merge script (run by GitHub Actions every Sunday at 02:00 UTC) |
| `validate-schema.js` | Schema validator — run after every merge and rebase |
| `quarterly-rebase.py` | Quarterly quality-pass tool — local and CI mode |
| `SCHEMA.md` | Field definitions, merge rules, schema version history |
| `.github/workflows/merge-deltas.yml` | Weekly automated delta merge workflow |
| `.github/workflows/quarterly-rebase.yml` | Quarterly quality review + rebase workflow |

## How contributions flow

```
User scans UPC in FunkoDex app (Android)
    │
    ▼
FunkoDex saves contrib:: document locally (Couchbase Lite)
    │
    ▼ (daily, if contribution opt-in enabled in Settings)
GitHubUploadWorker POSTs HMAC-signed delta to Cloudflare Worker
    │
    ▼
Cloudflare Worker validates schema, rate-limits (50/device/day),
writes delta file to deltas/{timestamp}-{deviceId}.json
    │
    ▼ (every Sunday 02:00 UTC — GitHub Actions)
merge-deltas.js merges all unprocessed deltas into master file
Deduplication: CHANNEL3 > USER_SCAN_CHANNEL3 > USER_SCAN
    │
    ▼ (every quarter — manual trigger or scheduled)
quarterly-rebase.py validates GS1 check digits, cross-references
Kenny Chan dataset, flags junk records for human review
    │
    ▼ (every CatalogRefreshWorker run — weekly on device)
App downloads funko_upc_community.json and merges UPCs
into local catalog:: Couchbase documents
```

## Privacy

All contributions are anonymous. No user identifiers, device models, or
account information are ever uploaded. The only device identifier is a
random UUID generated at install time and stored in EncryptedSharedPreferences.
It is used only for rate-limiting (50 contributions per device per day) and
is never stored in this repository.

## Setting up this repository

**This repository must be public** so the FunkoDex app can download
`funko_upc_community.json` without authentication.

1. Create a new public GitHub repository: `celtic-heart-steamworks/funko-upc-community`
2. Push the contents of this folder as the initial commit
3. Deploy the Cloudflare Worker (see `../cloudflare-worker/README.md` in the app repo)
4. Set `GITHUB_TOKEN` as a Cloudflare Worker Secret (PAT with `contents:write` on this repo)
5. Configure `workerUrl` in the Android app's `local.properties`

See `GITHUB_SETUP.md` in the app repository for full step-by-step instructions.

## Merge priority rules

When two contributions map the same UPC to different products:

| Priority | Source | Description |
|---|---|---|
| 1 (highest) | `CHANNEL3` | Verified by Channel3 API |
| 2 | `USER_SCAN_CHANNEL3` | User scan confirmed by Channel3 |
| 3 (lowest) | `USER_SCAN` | User scan only, unverified |

Within the same source: more populated fields win; earlier contribution date wins on a tie.

## Schema

See `SCHEMA.md` for the complete field reference. Current schema version: **1**.

Key fields:
- `upc` — 12-digit UPC-A or 13-digit EAN-13
- `handle` — Kenny Chan dataset handle (links to catalog entry)
- `name` — full product name as printed on the box
- `franchise` — IP/licence owner (e.g. "DC Comics", "Star Wars")
- `category` — Funko product line (e.g. "Pop! Movies", "Pop! Heroes")
- `source` — `CHANNEL3`, `USER_SCAN_CHANNEL3`, or `USER_SCAN`

## Quarterly rebase

Run `quarterly-rebase.py` locally every three months to validate GS1 check
digits, remove junk records, and cross-reference the Kenny Chan dataset.

```bash
# Local mode — interactive review
python3 quarterly-rebase.py

# CI mode — for the automated GitHub Actions workflow
python3 quarterly-rebase.py --ci
```

The GitHub Actions quarterly workflow runs automatically on the 1st of
January, April, July, and October at 09:00 UTC. It creates a PR for human
review when any records are flagged.

---

*Maintained by Celtic Heart Steamworks. Contributions welcome via the FunkoDex Android app.*
