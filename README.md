# ENT Agency Vault Tools

Scripts to consolidate, migrate, and sync the ENT Agency Obsidian vault across three machines.

## The Problem (Solved)

Three computers, three vault copies, duplicate folder structures (old + new mixed together), 90K+ parsed emails on one machine, 8K+ n8n emails on another, and no reliable sync method.

**Status as of 2026-03-26:** The vault has been consolidated on the Windows home desktop, the mbox migration is complete (13K files), the folder merge is complete (8,919 files merged, 7 old folders deleted), and Obsidian Sync is live across both machines. Talent profiles (21 creators), brand profiles (18 brands), CRM data, contracts, invoices, Zoom transcripts, and Google Sheets have all been added to the vault.

## Machine Map

| Machine | User | Vault Path | Sync Method | Vault ID / Remote |
|---------|------|-----------|-------------|-------------------|
| Windows home desktop | `C:\Users\ejatc` | `Documents\ENT-Agency-Vault` | Obsidian Sync | Vault ID: `b457de69b305459a` |
| Mac (daily driver) | `/Users/ethanatchley` | `~/Documents/obsidian-vault` | Obsidian Sync | Connected to "1st vault" remote |
| Windows work laptop | `C:\Users\ethan.atchley` | `Documents\1st vault` | Obsidian Sync (TBD) | Not yet connected |

**Sync method:** Obsidian Sync (not git). The Windows home desktop uploaded 1.12 GB to the "1st vault" remote. The Mac is connected and syncing.

## Scripts

| Script | Purpose | Status |
|--------|---------|--------|
| `merge_vault_folders.py` | Merge duplicate old->new folders, deduplicate, clean up | DONE |
| `inspect_mbox_extract.py` | Inspect parsed mbox data on ejatc machine | DONE |
| `migrate_mbox_extract.py` | Move parsed mbox categories into vault folders | DONE |
| `enrich_email_links.py` | Cross-link emails to brand/talent profiles | TODO |
| `gws_email_sync.py` | Live Gmail sync via `gws` CLI (replaces n8n) | TODO |
| `mbox_to_obsidian.py` | Bulk import from Takeout zip (entagency.co) | Available |
| `mbox_to_obsidian_nickient.py` | Bulk import from Takeout zip (nickient.com) | Available |
| `setup_gws.sh` | One-time gws CLI auth setup | TODO |
| `sync_both_accounts.sh` | Daily sync wrapper for both Gmail accounts | TODO |

---

## Step-by-Step Progress

### STEP 1: Clone repo -- DONE

```bash
git clone https://github.com/Entmarketingteam/mbox-to-obsidian.git
cd mbox-to-obsidian
```

### STEP 2: Fix encoding bugs -- DONE

Fixed UTF-8/cp1252 encoding issues in the migration scripts that caused crashes on Windows.

### STEP 3: Run inspect_mbox_extract.py -- DONE

```bash
python inspect_mbox_extract.py
```

Audited the parsed mbox data on the ejatc machine. Generated `mbox_extract_report.json`.

### STEP 4: Run migrate_mbox_extract.py -- DONE (13K files migrated)

```bash
python migrate_mbox_extract.py --source "C:\Users\ejatc\Documents\mbox_extract" --vault "C:\Users\ejatc\Documents\ENT-Agency-Vault"
```

Migrated 13,000+ parsed mbox emails into the vault's `09-Email-Archive/` folder, organized by category (Amazon-Leads, Brand-Pitches, Gmail-Captures, etc.).

### STEP 5: Run merge_vault_folders.py -- DONE (8,919 files merged, 7 old folders deleted)

```bash
python merge_vault_folders.py --vault "C:\Users\ejatc\Documents\ENT-Agency-Vault"
```

Merged content from old duplicate folders into the new structure. 8,919 files moved, 7 old folders removed.

### STEP 6: Connect Obsidian Sync on Windows -- DONE (1.12 GB uploaded)

Connected the Windows home desktop vault to "1st vault" remote via Obsidian Sync.
- Vault ID: `b457de69b305459a`
- Uploaded 1.12 GB to the remote

### STEP 7: Connect Obsidian Sync on Mac -- DONE

Connected the Mac vault to "1st vault" remote via Obsidian Sync. Both machines are now syncing.

### STEP 8: Build talent profiles -- DONE (21 creators)

Built structured profile notes for 21 creators in `08-Talent/`, each with their own subfolder containing contracts, invoices, and related documents.

### STEP 9: Build brand profiles -- DONE (18 brands)

Built structured profile notes for 18 brands in `01-Brands-Contacts/`.

### STEP 10: Add CRM data -- DONE

Added addresses, birthdays, PayPal info, and EIN numbers to talent and brand profiles.

### STEP 11: Parse contracts, invoices, Zoom transcripts, Google Sheets -- DONE

Parsed and imported contracts into `05-Financials/Contracts/`, invoices into `05-Financials/Invoices/`, Zoom transcripts, and Google Sheets data into the vault.

### STEP 12: Set up gws email sync -- TODO

```bash
cd ~/Documents/mbox-to-obsidian
bash setup_gws.sh

# Sync entagency.co emails
python3 gws_email_sync.py --account marketingteam@entagency.co --days 7 --dry-run
python3 gws_email_sync.py --account marketingteam@entagency.co --days 7

# Switch to nickient.com
gws auth login  # sign in with marketingteam@nickient.com
python3 gws_email_sync.py --account marketingteam@nickient.com --days 7
```

### STEP 13: Kill n8n workflow (if still running) -- TODO

Status of n8n is unknown -- it may still be running and capturing emails.

- Go to https://entagency.app.n8n.cloud
- Find workflow ID `B3bbBIvyfnuFXcze` ("Gmail -> Obsidian Inbox")
- Deactivate it

### STEP 14: Run enrich_email_links.py -- TODO

Cross-link emails to brand and talent profiles:

```bash
python enrich_email_links.py --vault "C:\Users\ejatc\Documents\ENT-Agency-Vault"
```

---

## Current Vault Structure

```
ENT-Agency-Vault/
  .obsidian/               -- Obsidian config (synced)
  00-Dashboard/            -- Home, MOCs, dashboards
  01-Brands-Contacts/      -- 18 brand profiles + contacts CRM
  02-Campaigns/            -- campaign tracking
  03-Products/             -- KCM, Healthyiish, NOVA, Beauty Creatine Plus
  04-Content/              -- content ideas, calendar
  05-Financials/           -- invoices, contracts, revenue tracking
    Contracts/
    Invoices/
  06-Agency-Ops/           -- SOPs, meeting notes
  06-Research/             -- substacks, research
  07-Knowledge-Base/       -- industry knowledge
  08-Archive/              -- archived/spam (chinese_leads etc)
  08-Talent/               -- 21 creator profiles with subfolders
    Ann Schulte/
    Courtney Pappy/
    Ellen Ludwig/
    Nicki Entenmann/
    Sara Preston/
    ...
  09-Email-Archive/        -- ALL emails, both accounts
    Amazon-Leads/          -- parsed amazon leads
    Brand-Pitches/         -- parsed brand pitches
    Gmail-Captures/        -- n8n legacy emails
    Quick-Notes/           -- quick capture notes
    attachments/           -- extracted attachments
```

Synced via Obsidian Sync. No git dependency for vault data.

---

## Email Frontmatter Format

All email notes use this YAML frontmatter (matches the vault's 09-Email-Archive MOC):

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

## Daily Sync (after gws setup)

```bash
cd ~/Documents/mbox-to-obsidian
./sync_both_accounts.sh 1    # sync last 1 day
./sync_both_accounts.sh 7    # sync last 7 days
```

Note: gws only supports one authed account at a time. The script syncs whichever account is logged in, then tells you to switch.
