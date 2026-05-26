# FunkoDex Community UPC — Schema Reference

## Current schema version: 1

The `schemaVersion` field on every record must equal `1`.
Future schema changes will increment this number and be documented below.

---

## Field definitions

| Field | Type | Required | Description |
|---|---|---|---|
| `upc` | string (12–13 digits) | ✓ | UPC-A (12 digits) or EAN-13 (13 digits) barcode as printed on the box |
| `handle` | string ≤ 100 chars | ✓ | Kenny Chan dataset handle (e.g. `batman-1989`) — links to the catalog entry |
| `name` | string 2–200 chars | ✓ | Full product name as it appears on the box (e.g. `Batman (1989)`) |
| `franchise` | string | ✓ | IP / licence owner (e.g. `DC Comics`, `Star Wars`, `Marvel`) |
| `category` | string | | Funko product line (e.g. `Pop! Movies`, `Pop! Heroes`, `Pop! Vinyl`) |
| `seriesNumber` | string | | Series number as displayed on the box (e.g. `#01`, `#196`) |
| `retailPrice` | number (USD) | | Funko suggested retail price in US dollars |
| `isVaulted` | boolean | | `true` if Funko has permanently retired this item |
| `isChase` | boolean | | `true` if this is a chase variant |
| `isExclusive` | boolean | | `true` if this is a retailer-exclusive |
| `exclusiveRetailer` | string | | Retailer name for exclusives (e.g. `Target`, `GameStop`, `Hot Topic`) |
| `imageUrl` | string (URL) | | HobbyDB CDN image URL — ends in `_large.jpg` or `_large.JPG` |
| `source` | enum | ✓ | How this record was created — see Source values below |
| `schemaVersion` | integer | ✓ | Must be `1` |
| `contributedAt` | string (YYYY-MM-DD) | ✓ | Date the record was first contributed |

### Source values

| Value | Meaning |
|---|---|
| `CHANNEL3` | UPC and metadata retrieved directly from the Channel3 structured API |
| `USER_SCAN_CHANNEL3` | User scanned the UPC; Channel3 confirmed the product data |
| `USER_SCAN` | User scanned the UPC and manually matched it to a Kenny Chan catalog entry |

---

## Merge priority rules

When multiple records exist for the same UPC (from different contributors or delta files),
the merge script keeps the best record using this priority order:

1. **Source quality**: `CHANNEL3` (3) > `USER_SCAN_CHANNEL3` (2) > `USER_SCAN` (1)
2. **Field population**: the record with more non-empty fields wins
3. **Age**: if all else is equal, the record with the earlier `contributedAt` wins
   (first correct scan takes precedence)

---

## Validation rules (enforced by `validate-schema.js` and `quarterly-rebase.py`)

- `upc` must match `\d{12,13}` (12 or 13 numeric digits only)
- 12-digit UPCs must pass the GS1 UPC-A check digit algorithm
- `handle` must be present and ≤ 100 characters
- `name` must be present and ≥ 2 characters
- `franchise` must be present
- `schemaVersion` must equal `1`
- `contributedAt` must be present (any non-empty string is accepted)
- `source` must be one of `CHANNEL3`, `USER_SCAN_CHANNEL3`, `USER_SCAN`
- String fields (`name`, `franchise`, `category`, `exclusiveRetailer`) are
  HTML-stripped by the Cloudflare Worker before storage

---

## Schema version history

| Version | Date | Changes |
|---|---|---|
| 1 | 2025-05-25 | Initial schema — all fields above |

---

## Privacy policy

Every field in this schema describes a **product**, not a person.
No user identifiers, device IDs, collection data, purchase history,
or any personal information is stored in or uploaded to this repository.
See the [README](README.md) for the full privacy statement.
