# Setting up this repository

This file lives in the `funko-upc-community` repo and explains how to get
the full system running. The complete step-by-step guide (all four parts:
app repo, community repo, Cloudflare Worker, eBay developer registration)
is in `GITHUB_SETUP.md` inside the FunkoDex app package.

---

## Quick-start for this repo only

### 1. Create the public GitHub repo

```bash
gh repo create celtic-heart-steamworks/funko-upc-community \
    --public \
    --description "Community UPC database for FunkoDex — open source Funko Pop barcode data"
```

Or on the GitHub website: Owner `celtic-heart-steamworks`, name `funko-upc-community`,
visibility **Public**, do **not** initialise with a README.

### 2. Push

```bash
git init
git add -A
git commit -m "Initial commit — FunkoDex community UPC database v1.0"
git branch -M main          # workflows reference 'main', not 'master'
git remote add origin https://github.com/celtic-heart-steamworks/funko-upc-community.git
git push -u origin main
```

### 3. Verify workflows

Go to: `github.com/celtic-heart-steamworks/funko-upc-community/actions`

You should see two workflows:
- **Weekly delta merge** — runs every Sunday 02:00 UTC automatically
- **Quarterly rebase** — runs 1 Jan / 1 Apr / 1 Jul / 1 Oct automatically, or trigger manually

Run "Weekly delta merge" manually once to confirm it works
(it will succeed with nothing to do — no delta files yet).

### 4. No secrets needed for this repo

The workflows use `${{ secrets.GITHUB_TOKEN }}` — GitHub provides this automatically.
No manual secrets setup is required for the community repo.

### 5. Enable notifications (optional but recommended)

GitHub Mobile → your profile → Notifications → enable workflow notifications
for `funko-upc-community` so you get a push notification when the quarterly
rebase creates a PR for review.

---

## Connecting the Android app

Once the community repo is live, the Android app needs two things:

1. **Cloudflare Worker** deployed (see `cloudflare-worker/` in the app package).
   The Worker is what writes delta files to this repo on behalf of app users.

2. **`workerUrl`** set in `local.properties` in the app project:
   ```
   workerUrl=https://funkodex-contrib.YOUR_ACCOUNT.workers.dev
   ```

Users who have not set up the Worker can still use the app — community
contributions are simply queued locally and never uploaded.

---

## Files in this repo

| File | What it does |
|---|---|
| `funko_upc_community.json` | Master UPC database — downloaded weekly by every FunkoDex install |
| `deltas/` | Daily delta files written by the Cloudflare Worker |
| `merge-state.json` | Tracks which deltas have been processed |
| `merge-deltas.js` | Weekly merge script (GitHub Actions runs this automatically) |
| `validate-schema.js` | Schema validator — run after every merge and quarterly rebase |
| `quarterly-rebase.py` | Quarterly quality pass — validates GS1 check digits, flags junk |
| `SCHEMA.md` | Complete field reference and merge rules |
| `.github/workflows/` | Automated merge and rebase workflows |

For the full setup guide including the Cloudflare Worker and eBay developer
registration, see `GITHUB_SETUP.md` in the FunkoDex app repository.
