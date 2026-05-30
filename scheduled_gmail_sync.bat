@echo off
REM Gmail Sync + Slack notifier - runs via Task Scheduler every 30 minutes
REM Step 1: Sync both accounts, last 1 day of emails -> vault notes
REM Step 2: Post any TRIAGE_NICKI_OFFERS-labeled emails to Slack #inbound-pitches

cd /d "C:\Users\ejatc\Documents\mbox_to_obsidian"
set PYTHONIOENCODING=utf-8

python gmail_api_sync.py --all --days 1 >> "%USERPROFILE%\.claude\gmail_sync.log" 2>&1

python gmail_to_slack.py --days 7 >> "%USERPROFILE%\.claude\gmail_to_slack.log" 2>&1

REM Keep logs from growing forever - trim to last 500 lines each
powershell -Command "if (Test-Path '%USERPROFILE%\.claude\gmail_sync.log') { $c = Get-Content '%USERPROFILE%\.claude\gmail_sync.log' -Tail 500; Set-Content '%USERPROFILE%\.claude\gmail_sync.log' $c }"
powershell -Command "if (Test-Path '%USERPROFILE%\.claude\gmail_to_slack.log') { $c = Get-Content '%USERPROFILE%\.claude\gmail_to_slack.log' -Tail 500; Set-Content '%USERPROFILE%\.claude\gmail_to_slack.log' $c }"
