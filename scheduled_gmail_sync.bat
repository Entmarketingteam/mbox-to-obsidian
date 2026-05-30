@echo off
REM Gmail API Sync - standalone Gmail sync utility.
REM NOTE: The active ENT-Gmail-Sync scheduled task no longer calls this file;
REM it now runs ent-agency-ops/scripts/master_sync.bat which bundles Gmail sync,
REM Email->Airtable, Email->Slack, and other steps. This file is kept as a
REM manual standalone Gmail-only sync if needed.

cd /d "C:\Users\ejatc\Documents\mbox_to_obsidian"
set PYTHONIOENCODING=utf-8

python gmail_api_sync.py --all --days 1 >> "%USERPROFILE%\.claude\gmail_sync.log" 2>&1

REM Keep log from growing forever - trim to last 500 lines
powershell -Command "if (Test-Path '%USERPROFILE%\.claude\gmail_sync.log') { $c = Get-Content '%USERPROFILE%\.claude\gmail_sync.log' -Tail 500; Set-Content '%USERPROFILE%\.claude\gmail_sync.log' $c }"
