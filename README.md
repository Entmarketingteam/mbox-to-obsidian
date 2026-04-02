# ENT Agency Vault Tools

Scripts to build, sync, and maintain the ENT Agency Obsidian vault.

## Status

The vault has been consolidated on the Windows home desktop. Mbox migration is complete (13K files), folder merge is done (8,919 files), and Obsidian Sync is live across both machines. Talent profiles (21 creators), brand profiles (18 brands), CRM data, contracts, invoices, Zoom transcripts, and Google Sheets have all been added.

## Machine Map

| Machine | User | Vault Path | Sync Method |
|---------|------|-----------|-------------|
| Windows home desktop | `C:\Users\ejatc` | `Documents\ENT-Agency-Vault` | Obsidian Sync |
| Mac (daily driver) | `/Users/ethanatchley` | `~/Documents/obsidian-vault` | Obsidian Sync |
| Windows work laptop | `C:\Users\ethan.atchley` | `Documents\1st vault` | Obsidian Sync (TBD) |

## Directory Structure

```
mbox_to_obsidian/
  analyze/                 -- Analysis scripts (sheets_repeat.py)
  data/                    -- Extracted data, calendar records, deal details (gitignored)
  integrations/            -- Airtable/GCal sync scripts
  mbox_to_obsidian.py      -- Bulk import from Takeout zip (entagency.co)
  mbox_to_obsidian_nickient.py -- Bulk import from Takeout zip (nickient.com)
  gmail_api_sync.py        -- Live Gmail sync via Gmail API
  gws_email_sync.py        -- Live Gmail sync via gws CLI
  enrich_email_links.py    -- Cross-link emails to brand/talent profiles
  merge_vault_folders.py   -- Merge duplicate old->new vault folders
  clean_attachment_stubs.py -- Clean up attachment stub notes
  retag_456growth.py       -- Retag 456 Growth emails
  google_apps_script_calendar_sync.js -- Google Calendar sync via Apps Script
  setup_gws.sh             -- One-time gws CLI auth setup
  sync_both_accounts.sh    -- Daily sync wrapper for both Gmail accounts
  scheduled_gmail_sync.bat -- Windows Task Scheduler entry point
```

## Active Scripts

| Script | Purpose | Status |
|--------|---------|--------|
| `gmail_api_sync.py` | Live Gmail sync via Gmail API | Active |
| `gws_email_sync.py` | Live Gmail sync via gws CLI (alternative) | TODO |
| `enrich_email_links.py` | Cross-link emails to brand/talent profiles | TODO |
| `mbox_to_obsidian.py` | Bulk import from Takeout zip (entagency.co) | Available |
| `mbox_to_obsidian_nickient.py` | Bulk import from Takeout zip (nickient.com) | Available |
| `merge_vault_folders.py` | Merge duplicate old->new vault folders | Done |
| `clean_attachment_stubs.py` | Clean up attachment stub notes | Available |
| `retag_456growth.py` | Retag 456 Growth emails | Done |
| `analyze/sheets_repeat.py` | Analyze repeat brands from Google Sheets | Available |
| `integrations/airtable_to_gcal_sync.py` | Sync Airtable campaigns to Google Calendar | Available |
| `integrations/backfill_campaigns.py` | Backfill campaign data into Airtable | Available |
| `setup_gws.sh` | One-time gws CLI auth setup | TODO |
| `sync_both_accounts.sh` | Daily sync wrapper for both Gmail accounts | TODO |
| `scheduled_gmail_sync.bat` | Windows Task Scheduler entry point | Available |

## Remaining TODOs

- Set up gws email sync (or continue using `gmail_api_sync.py`)
- Run `enrich_email_links.py` to cross-link emails to brand/talent profiles
- Kill n8n workflow if still running (https://entagency.app.n8n.cloud, workflow `B3bbBIvyfnuFXcze`)

## Vault Structure

```
ENT-Agency-Vault/
  .obsidian/               -- Obsidian config (synced)
  00-Dashboard/            -- Home, MOCs, dashboards
  01-Brands-Contacts/      -- 18 brand profiles + contacts CRM
  02-Campaigns/            -- Campaign tracking
  03-Products/             -- KCM, Healthyiish, NOVA, Beauty Creatine Plus
  04-Content/              -- Content ideas, calendar
  05-Financials/           -- Invoices, contracts, revenue tracking
  06-Agency-Ops/           -- SOPs, meeting notes
  06-Research/             -- Substacks, research
  07-Knowledge-Base/       -- Industry knowledge
  08-Archive/              -- Archived/spam (chinese_leads etc)
  08-Talent/               -- 21 creator profiles with subfolders
  09-Email-Archive/        -- ALL emails, both accounts
```

Synced via Obsidian Sync. No git dependency for vault data.

## Email Frontmatter Format

All email notes use this YAML frontmatter:

```yaml
---
type: email
sender: "Brand Contact"
sender_email: "contact@brand.com"
recipient: "marketingteam@nickient.com"
subject: "Partnership Opportunity"
email_date: 2023-06-15T14:30:00
account: "marketingteam@nickient.com"
labels: ["Inbox", "Important"]
related_brand:
related_campaign:
related_contact:
tags:
  - email
created: 2023-06-15
status: unprocessed
---
```
