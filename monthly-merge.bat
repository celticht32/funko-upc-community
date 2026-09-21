@echo off
setlocal enabledelayedexpansion
REM ===========================================================================
REM  monthly-merge.bat - fold community contributions into the published
REM                      catalog and publish it.
REM
REM  Run this from C:\Downloads\Development\funko-upc-community, or just
REM  double-click it - it cd's to its own folder.
REM
REM  WHAT IT DOES
REM    1. pulls the deltas the Cloudflare Worker has committed
REM    2. shows you a dry run and WAITS for you to approve it
REM    3. merges contributions into funko_catalog_master.json
REM    4. rebuilds funko_catalog_master.json.gz + manifest.json
REM    5. commits, tags and pushes
REM
REM  It stops at the first failure. Nothing is committed unless every step
REM  before it succeeded.
REM
REM  NOTE: merge-deltas.js is NOT run here. That tool maintains the schema-v1
REM  funko_upc_community.json, which no shipped build reads - the app fetches
REM  the v2 master. v1 is frozen, kept only as history.
REM
REM  SPDX-License-Identifier: MIT
REM  Copyright (c) 2026 Chris Ahrendt
REM ===========================================================================

cd /d "%~dp0"
echo.
echo ===== FunkoDex monthly catalog merge =====
echo Working in: %CD%
echo.

REM --- version stamp, YYYY-MM -------------------------------------------------
for /f "usebackq delims=" %%i in (`python -c "from datetime import date;print(date.today().strftime('%%Y-%%m'))"`) do set "VER=%%i"
if "%VER%"=="" (
    echo ERROR: could not determine the version stamp. Is python on PATH?
    goto :fail
)
echo Catalog version to publish: %VER%
echo.

REM --- 1. pull ---------------------------------------------------------------
echo [1/6] Pulling latest contributions...
git pull
if errorlevel 1 goto :fail

REM --- 2. dry run, then ask ---------------------------------------------------
echo.
echo [2/6] Dry run - nothing is written yet:
echo.
python merge-contributions.py --dry-run
if errorlevel 1 goto :fail
echo.
set /p OK="Apply this merge and publish %VER%? (y/N): "
if /i not "%OK%"=="y" (
    echo Aborted. Nothing changed.
    goto :end
)

REM --- 3. merge --------------------------------------------------------------
echo.
echo [3/6] Merging contributions into the master...
python merge-contributions.py
if errorlevel 1 goto :fail

REM --- 4. publish ------------------------------------------------------------
echo.
echo [4/6] Building the publish artifacts...
python publish-master.py --version %VER%
if errorlevel 1 goto :fail

REM --- 5. verify what a device will actually fetch ----------------------------
echo.
echo [5/6] Verifying the payload matches the manifest...
python -c "import json,gzip,hashlib,sys; m=json.load(open('manifest.json',encoding='utf-8')); raw=open('funko_catalog_master.json.gz','rb').read(); ok = hashlib.sha256(raw).hexdigest()==m['sha256'] and len(raw)==m['sizeBytes'] and len(json.loads(gzip.decompress(raw).decode('utf-8')))==m['recordCount']; print('  verified:', m['recordCount'], 'records,', m['sizeBytes'], 'bytes') if ok else sys.exit('  MISMATCH - refusing to publish'); sys.exit(0 if ok else 1)"
if errorlevel 1 goto :fail

REM --- 6. commit, tag, push --------------------------------------------------
echo.
echo [6/6] Committing and pushing...
git add -A
if errorlevel 1 goto :fail
git commit -m "Publish catalog %VER% - community contributions merged"
if errorlevel 1 (
    echo Nothing to commit - the catalog did not change this month.
    goto :end
)
git tag catalog-%VER%
git push --follow-tags
if errorlevel 1 goto :fail

echo.
echo ===== Done. Catalog %VER% is live. =====
echo Devices pick it up on their next weekly manifest check.
echo.
if exist REVIEW_contribution_conflicts.json (
    echo Review REVIEW_contribution_conflicts.json - contributions that
    echo disagreed with the master. The master value was kept in every case.
)
goto :end

:fail
echo.
echo ***** FAILED - stopped before publishing. *****
echo Nothing was pushed. Check the message above, fix it, and re-run.
echo If merge-contributions.py already ran, `git checkout -- .` resets the
echo working tree to the last commit.
exit /b 1

:end
echo.
pause
endlocal
