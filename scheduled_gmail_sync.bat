@echo off
REM Gmail API Sync - runs via Task Scheduler every 30 minutes
REM Syncs both accounts, last 1 day of emails

cd /d "C:\Users\ejatc\Documents\mbox_to_obsidian"
python gmail_api_sync.py --all --days 1 >> "%USERPROFILE%\.claude\gmail_sync.log" 2>&1

REM Keep log from growing forever - trim to last 500 lines
powershell -Command "if (Test-Path '%USERPROFILE%\.claude\gmail_sync.log') { $c = Get-Content '%USERPROFILE%\.claude\gmail_sync.log' -Tail 500; Set-Content '%USERPROFILE%\.claude\gmail_sync.log' $c }"
