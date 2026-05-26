#!/usr/bin/env node
/**
 * merge-deltas.js
 *
 * Runs weekly via GitHub Actions.
 * Reads all unprocessed delta files from deltas/
 * and merges them into funko_upc_community.json (the master file),
 * deduplicating by UPC using a priority-based merge rule.
 *
 * Priority (highest wins):
 *   1. source=CHANNEL3            — structured API data, most reliable
 *   2. source=USER_SCAN_CHANNEL3  — user scan confirmed against Channel3
 *   3. source=USER_SCAN           — user-only match, no Channel3 confirmation
 *   Within same source: more fields populated > fewer
 *   Within same source + same field count: earlier contributedAt wins
 *
 * State is tracked in merge-state.json so we never reprocess old deltas.
 */

const fs   = require('fs');
const path = require('path');

const MASTER_FILE = 'funko_upc_community.json';
const STATE_FILE  = 'merge-state.json';
const DELTAS_DIR  = 'deltas';

const SOURCE_RANK = { CHANNEL3: 3, USER_SCAN_CHANNEL3: 2, USER_SCAN: 1 };

function populatedFields(r) {
  return ['upc','handle','name','franchise','category','seriesNumber',
          'retailPrice','isVaulted','isChase','isExclusive','exclusiveRetailer','imageUrl']
    .filter(k => r[k] !== undefined && r[k] !== null && r[k] !== '')
    .length;
}

function chooseBetter(a, b) {
  const ra = SOURCE_RANK[a.source] || 0;
  const rb = SOURCE_RANK[b.source] || 0;
  if (rb > ra) return b;
  if (ra > rb) return a;
  // Same source rank — prefer more populated record
  const fa = populatedFields(a);
  const fb = populatedFields(b);
  if (fb > fa) return b;
  if (fa > fb) return a;
  // All equal — keep the earlier contribution (first-correct-scan wins)
  return (a.contributedAt || '') <= (b.contributedAt || '') ? a : b;
}

function validateRecord(r) {
  if (!r || typeof r !== 'object')          return false;
  if (!/^\d{12,13}$/.test(r.upc || ''))    return false;
  if (!r.handle || r.handle.length > 100)  return false;
  if (!r.name   || r.name.length < 2)      return false;
  if (!r.franchise)                         return false;
  if (r.schemaVersion !== 1)               return false;
  return true;
}

function sanitise(r) {
  const strip = s => (s || '').replace(/<[^>]*>/g, '').trim();
  return {
    ...r,
    name:             strip(r.name),
    franchise:        strip(r.franchise),
    category:         strip(r.category     || ''),
    exclusiveRetailer:strip(r.exclusiveRetailer || ''),
    imageUrl:         strip(r.imageUrl     || ''),
  };
}

// ── Main ──────────────────────────────────────────────────────────────────────

const masterArray = JSON.parse(fs.readFileSync(MASTER_FILE, 'utf8') || '[]');
const masterMap   = new Map(masterArray.map(r => [r.upc, r]));

const state       = fs.existsSync(STATE_FILE)
  ? JSON.parse(fs.readFileSync(STATE_FILE, 'utf8'))
  : { lastMergedAt: null, processedFiles: [] };

const processed   = new Set(state.processedFiles || []);

// Get all delta files not yet processed, sorted chronologically
const deltaFiles  = fs.readdirSync(DELTAS_DIR)
  .filter(f => f.endsWith('.json') && f !== '.gitkeep' && !processed.has(f))
  .sort();

if (deltaFiles.length === 0) {
  console.log('No new delta files to process.');
  process.exit(0);
}

let added = 0, updated = 0, skipped = 0, invalid = 0;

for (const file of deltaFiles) {
  const raw = JSON.parse(fs.readFileSync(path.join(DELTAS_DIR, file), 'utf8') || '[]');
  for (const record of raw) {
    if (!validateRecord(record)) { invalid++; continue; }
    const clean    = sanitise(record);
    const existing = masterMap.get(clean.upc);
    if (!existing) {
      masterMap.set(clean.upc, clean);
      added++;
    } else {
      const winner = chooseBetter(existing, clean);
      if (winner === clean) {
        masterMap.set(clean.upc, clean);
        updated++;
      } else {
        skipped++;
      }
    }
  }
  processed.add(file);
  console.log(`  Processed: ${file} (${raw.length} records)`);
}

// Sort master by franchise then name for consistent diffs
const sorted = [...masterMap.values()].sort((a, b) => {
  const fc = (a.franchise || '').localeCompare(b.franchise || '');
  return fc !== 0 ? fc : (a.name || '').localeCompare(b.name || '');
});

fs.writeFileSync(MASTER_FILE, JSON.stringify(sorted, null, 2));

// Update state
const newState = {
  lastMergedAt:   new Date().toISOString(),
  totalRecords:   sorted.length,
  processedFiles: [...processed],
};
fs.writeFileSync(STATE_FILE, JSON.stringify(newState, null, 2));

console.log(`\nMerge complete:`);
console.log(`  Added:    ${added}`);
console.log(`  Updated:  ${updated}`);
console.log(`  Skipped:  ${skipped} (existing record was already better)`);
console.log(`  Invalid:  ${invalid} (schema errors, not imported)`);
console.log(`  Total:    ${sorted.length} records in master file`);
