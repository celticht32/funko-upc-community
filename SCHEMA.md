# FunkoDex Community Catalog — Schema Reference

Two schemas are live at once during the transition. Know which one you are looking at.

| Version | File | Status |
|---|---|---|
| **2** | `funko_catalog_master.json` (+ `.gz`, `manifest.json`) | **Current.** The full golden master |
| 1 | `funko_upc_community.json` | Legacy. UPC overlay for pre-v1.3 app builds |

---

## Schema 2 — the golden master

A bare JSON array of catalog records, **identical in shape to the bundled APK asset**.
That is deliberate: the client parses the network master and the bundled asset with one
code path. Change the shape in one place and you must change it in both, or installs
diverge depending on whether they ever refreshed.

### Required for a record to load

| Field | Type | Notes |
|---|---|---|
| `_id` or `handle` | string | Document id. `_id` is already prefixed (`catalog::{handle}`) |
| `title` | string | The loader **skips** records without one — silent data loss |
| `type` | string | Must be `catalog`. A `funko` record here is a collection record and must never ship |

### Core fields

| Field | Type | Notes |
|---|---|---|
| `upc` | string | 12-digit UPC-A or 13-digit EAN-13 |
| `series` | string | Funko product line. **A list here fails validation** — the app expects a string |
| `category` | string | e.g. `Pop! Movies` |
| `funkoNumber` | string | Pop number as printed on the box |
| `imageUrl` | string | Product image |
| `retailPrice` | number | USD |
| `exclusiveRetailer` | string | e.g. `Funko Hot Topic` |
| `franchiseSuggestion`, `pcSeries` | string | The real franchise (`Star Wars`, `Twin Peaks`) — *not* the product line |
| `marketValueLoose`, `marketValueComplete`, `marketValueNew` | string | PriceCharting values |
| `releaseDate`, `ebayEpid`, `publisher`, `pricechartingId`, `pricechartingUrl` | | Provenance and lookup keys |
| `source` | string | `ENRICHED` for every master record — **load-bearing**, see below |

### Booleans must be real booleans

`isExclusive`, `isChase`, `isVaulted`, `marketValueIsApproximate`.

Kotlin reads a JSON string as **false**, silently. The string `"False"` has shipped
broken data in this project before. `publish-master.py` refuses to publish if any of
these is not a real boolean.

### Why `source: "ENRICHED"` matters

The client sweep deletes catalog documents the master no longer carries — but **only
those whose `source` is `ENRICHED`**. That filter is what protects a user's manual adds
and any record another writer created. Publishing master records under a different
`source` would exempt them from the sweep and leave stale records on devices forever.

### manifest.json

```json
{
  "schemaVersion": 2,
  "catalogVersion": "2026-10",
  "recordCount": 26655,
  "sha256": "4250bc...f2ea",
  "sizeBytes": 2292962,
  "publishedAt": "2026-09-20T13:53:50Z",
  "minRecordCount": 20000
}
```

`sha256` covers the **gzipped** bytes, so the client verifies before it inflates.
Hashing the decompressed JSON would mean inflating an unverified archive first.

`minRecordCount` is the floor below which a client refuses the master outright. A
catalog claiming 400 records is a bug or an attack, and applying it would empty every
device through the sweep.

### Publish-time validation

`publish-master.py` refuses to publish on any of: a collection record present, a record
with no usable id, a record with no title, a non-boolean in the four boolean fields,
`series` as a list, a duplicate document id, or a record count below the floor.

---

## Schema 1 — legacy UPC overlay

Retained only for app builds that predate the v1.3 architecture. Retire it once those
are no longer in the field.

| Field | Type | Required | Description |
|---|---|---|---|
| `upc` | string (12–13 digits) | ✓ | UPC-A or EAN-13 |
| `handle` | string ≤ 100 | ✓ | Catalog handle — becomes `catalog::{handle}` |
| `name` | string 2–200 | ✓ | Product name |
| `franchise` | string | ✓ | IP / licence owner |
| `category` | string | | Funko product line |
| `seriesNumber` | string | | e.g. `#196` |
| `retailPrice` | number | | USD |
| `isVaulted`, `isChase`, `isExclusive` | boolean | | Real booleans, not strings |
| `exclusiveRetailer` | string | | |
| `imageUrl` | string | | |
| `source` | enum | ✓ | See below |
| `schemaVersion` | integer | ✓ | Must be `1` |
| `contributedAt` | string | ✓ | `YYYY-MM-DD` |

### Source values

| Value | Meaning |
|---|---|
| `CHANNEL3` | From the Channel3 structured API |
| `USER_SCAN_CHANNEL3` | User scan, confirmed by Channel3 |
| `USER_SCAN` | User scan, unconfirmed |
| `USER_MANUAL` | User matched a not-found scan by hand |
| `USER_EDIT` | User corrected an existing record |

`USER_MANUAL` and `USER_EDIT` are emitted by the app (`ScannerViewModel`,
`DetailViewModel`). Omitting them from `validate-schema.js` fails the weekly merge
workflow the first time a hand-corrected record reaches the master — that happened, and
is why they are listed here.

### Merge priority

1. Source rank: `CHANNEL3` (3) > `USER_SCAN_CHANNEL3` (2) > `USER_SCAN` / `USER_MANUAL` / `USER_EDIT` (1)
2. More populated fields win
3. Earlier `contributedAt` wins

A user-asserted record never outranks Channel3-confirmed data.

### Validation (`validate-schema.js`, `quarterly-rebase.py`)

- `upc` matches `\d{12,13}`; 12-digit values must pass the GS1 check digit
- `handle` present, ≤ 100 chars
- `name` present, ≥ 2 chars
- `franchise` present
- `schemaVersion` equals `1`
- `contributedAt` present
- `source` is one of the five values above

---

## Schema version history

| Version | Date | Changes |
|---|---|---|
| 2 | 2026-09-20 | Full golden master replaces the UPC overlay. Manifest-gated, checksum-pinned, applied wholesale. Per-record trust logic removed from the client |
| 1 | 2025-05-25 | Initial UPC overlay schema |

---

## Privacy

Every field in both schemas describes a **product**. No user identifiers, device IDs,
ownership, purchase history, notes or photographs are stored here or uploaded in any
form. See the [README](README.md).
