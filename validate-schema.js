#!/usr/bin/env node
/**
 * validate-schema.js <filename>
 * Exits 1 if the file fails schema validation (used in GitHub Actions).
 */
const fs = require('fs');
const file = process.argv[2];
if (!file) { console.error('Usage: validate-schema.js <file>'); process.exit(1); }

// Must stay in sync with SOURCE_RANK in merge-deltas.js, VALID_SOURCES in
// cloudflare-worker/worker.js, and sourceRank() in CatalogRefreshWorker.kt.
// USER_MANUAL and USER_EDIT are emitted by the Android app (ScannerViewModel,
// DetailViewModel); omitting them here fails the weekly merge workflow the
// first time a hand-corrected record reaches master.
const VALID_SOURCES = ['CHANNEL3','USER_SCAN_CHANNEL3','USER_SCAN','USER_MANUAL','USER_EDIT'];

const data = JSON.parse(fs.readFileSync(file, 'utf8'));
if (!Array.isArray(data)) { console.error('Not an array'); process.exit(1); }

let errors = 0;
for (const [i, r] of data.entries()) {
  if (!/^\d{12,13}$/.test(r.upc || ''))  { console.error(`[${i}] Invalid UPC: ${r.upc}`); errors++; }
  if (!r.handle)                           { console.error(`[${i}] Missing handle`); errors++; }
  if (!r.name || r.name.length < 2)       { console.error(`[${i}] Missing/short name`); errors++; }
  if (!r.franchise)                        { console.error(`[${i}] Missing franchise`); errors++; }
  if (r.schemaVersion !== 1)              { console.error(`[${i}] Bad schemaVersion`); errors++; }
  if (!r.contributedAt)                   { console.error(`[${i}] Missing contributedAt`); errors++; }
  if (!VALID_SOURCES.includes(r.source)) {
    console.error(`[${i}] Invalid source: ${r.source}`); errors++;
  }
}
if (errors > 0) { console.error(`\n${errors} validation error(s). Failing build.`); process.exit(1); }
console.log(`OK: ${data.length} records validated.`);
