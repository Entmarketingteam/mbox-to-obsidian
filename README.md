# ENT Agency Vault Tools

Scripts to consolidate, migrate, and sync the ENT Agency Obsidian vault across three machines.

## The Problem

Three computers, three vault copies, duplicate folder structures (old + new mixed together), 90K+ parsed emails on one machine, 8K+ n8n emails on another, and almost none of it in git.

## Machine Map

| Machine | User | Vault Path | Vault Name | What's unique |
|---------|------|-----------|------------|---------------|
| Mac (daily driver) | `/Users/ethanatchley` | `~/Documents/obsidian-vault` | `obsidian-vault` | Primary machine |
| Windows work laptop | `C:\Users\ethan.atchley` | `Documents\1st vault` | `1st vault` | 8,400 n8n-captured entagency.co emails |
| Windows home desktop | `C:\Users\ejatc` | `Documents\Ent-Agency-vault` | `Ent-Agency-vault` | 90K parsed/categorized mbox emails, days of Claude Code restructuring work |

## Duplicate Folder Problem

All three machines have two sets of numbered folders — old structure and new structure living side by side:

| Old (keep content, delete folder) | New (keep folder, merge content into) |
|-----------------------------------|---------------------------------------|
| `01-Inbox` | `09-Email-Archive` |
| `02-Creators` | `08-Talent` |
| `03-Brands` | `01-Brands-Contacts` |
| `04-Campaigns` | `02-Campaigns` |
| `05-ENT-Agency` | `06-Agency-Ops` |
| `06-Beauty-Creatine-Plus` | `03-Products/Beauty-Creatine-Plus` |
| `07-Technical` | `07-Knowledge-Base` |

Only 720 files are tracked in git. Everything else is local-only and at risk.

## Scripts

| Script | Purpose |
|--------|---------|
| `merge_vault_folders.py` | Merge duplicate old→new folders, deduplicate, clean up |
| `inspect_mbox_extract.py` | Inspect parsed mbox data on ejatc machine |
| `migrate_mbox_extract.py` | Move parsed mbox categories into vault folders |
| `gws_email_sync.py` | Live Gmail sync via `gws` CLI (replaces n8n) |
| `mbox_to_obsidian.py` | Bulk import from Takeout zip (entagency.co) |
| `mbox_to_obsidian_nickient.py` | Bulk import from Takeout zip (nickient.com) |
| `setup_gws.sh` | One-time gws CLI auth setup |
| `sync_both_accounts.sh` | Daily sync wrapper for both Gmail accounts |

---

## Step-by-Step: Fix Everything

### STEP 1: On the ejatc home desktop — consolidate the vault

This machine has the most data and the restructured folders. Start here.

```bash
# Clone this repo
git clone https://github.com/Entmarketingteam/mbox-to-obsidian.git
cd mbox-to-obsidian

# 1a. Audit — see the current mess
python merge_vault_folders.py --vault "C:\Users\ejatc\Documents\Ent-Agency-vault" --audit

# 1b. Dry run — preview what the merge would do
python merge_vault_folders.py --vault "C:\Users\ejatc\Documents\Ent-Agency-vault" --dry-run

# 1c. Do the merge (moves old folder content into new folders, deletes empty old folders)
python merge_vault_folders.py --vault "C:\Users\ejatc\Documents\Ent-Agency-vault"

# 1d. Inspect the parsed mbox email data
python inspect_mbox_extract.py

# 1e. Push the inspection report so other machines can see it
git add mbox_extract_report.json
git commit -m "mbox_extract inspection report from ejatc"
git push
```

### STEP 2: On the ejatc home desktop — push the clean vault to git

```bash
cd "C:\Users\ejatc\Documents\Ent-Agency-vault"
git add -A
git status
# Review what's being added — should see the new folders and merged content
git commit -m "Consolidate vault: merge old folders into new structure, add all untracked content"
git push
```

**This is the most important step.** After this, everything is safe in git.

### STEP 3: On the ejatc home desktop — migrate parsed mbox emails into vault

```bash
cd path\to\mbox-to-obsidian

# 3a. Dry run first — see what would be created
python migrate_mbox_extract.py --source "C:\Users\ejatc\Documents\mbox_extract" --vault "C:\Users\ejatc\Documents\Ent-Agency-vault" --dry-run

# 3b. Start with a small batch to verify format
python migrate_mbox_extract.py --source "C:\Users\ejatc\Documents\mbox_extract" --vault "C:\Users\ejatc\Documents\Ent-Agency-vault" --category entenmann --limit 100

# 3c. Check the output in Obsidian — do the notes look right?
# If yes, run the full migration (category by category):
python migrate_mbox_extract.py --source "C:\Users\ejatc\Documents\mbox_extract" --vault "C:\Users\ejatc\Documents\Ent-Agency-vault" --category entenmann
python migrate_mbox_extract.py --source "C:\Users\ejatc\Documents\mbox_extract" --vault "C:\Users\ejatc\Documents\Ent-Agency-vault" --category brand_pitches
python migrate_mbox_extract.py --source "C:\Users\ejatc\Documents\mbox_extract" --vault "C:\Users\ejatc\Documents\Ent-Agency-vault" --category amazon_leads
python migrate_mbox_extract.py --source "C:\Users\ejatc\Documents\mbox_extract" --vault "C:\Users\ejatc\Documents\Ent-Agency-vault" --category healthyish
python migrate_mbox_extract.py --source "C:\Users\ejatc\Documents\mbox_extract" --vault "C:\Users\ejatc\Documents\Ent-Agency-vault" --category nova
python migrate_mbox_extract.py --source "C:\Users\ejatc\Documents\mbox_extract" --vault "C:\Users\ejatc\Documents\Ent-Agency-vault" --category product_launch
python migrate_mbox_extract.py --source "C:\Users\ejatc\Documents\mbox_extract" --vault "C:\Users\ejatc\Documents\Ent-Agency-vault" --category recent_attachments

# 3d. Commit the migrated emails
cd "C:\Users\ejatc\Documents\Ent-Agency-vault"
git add -A
git commit -m "Import parsed mbox emails into vault"
git push
```

**Note:** 90K+ emails is a LOT for git. Consider whether you want all of them in the vault or just the important categories (entenmann, brand_pitches, healthyish, nova, product_launch). The chinese_leads (31K) are mostly spam — those go to 08-Archive.

### STEP 4: On the Mac — pull the clean vault

```bash
cd ~/Documents/obsidian-vault
git pull
```

If there are merge conflicts (because the Mac has local changes):
```bash
git stash          # save local changes
git pull           # get the clean state from ejatc
git stash pop      # re-apply local changes on top
```

Or if the Mac vault is too diverged, fresh clone:
```bash
mv ~/Documents/obsidian-vault ~/Documents/obsidian-vault-backup
cd ~/Documents
git clone git@github.com:Entmarketingteam/ent-agency-vault.git obsidian-vault
```

### STEP 5: On the Mac — set up gws for daily email sync

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

### STEP 6: On the Windows work laptop — pull the clean vault

```bash
cd "C:\Users\ethan.atchley\Documents\1st vault"
git pull
```

Or fresh clone if too messy:
```bash
cd "C:\Users\ethan.atchley\Documents"
mv "1st vault" "1st vault-backup"
git clone git@github.com:Entmarketingteam/ent-agency-vault.git "1st vault"
```

### STEP 7: Kill the n8n email workflow

Once gws sync is working on the Mac, disable the n8n email capture workflow:
- Go to https://entagency.app.n8n.cloud
- Find workflow ID `B3bbBIvyfnuFXcze` ("Gmail -> Obsidian Inbox")
- Deactivate it

---

## Final State

After all steps:

```
obsidian-vault/
  00-Dashboard/
  01-Brands-Contacts/     ← brands + contacts CRM
  02-Campaigns/           ← campaign tracking
  03-Products/            ← KCM, Healthyiish, NOVA, Beauty Creatine Plus
  04-Content/             ← content ideas, calendar
  05-Financials/          ← invoices, contracts
  06-Agency-Ops/          ← SOPs, meeting notes
  06-Research/            ← substacks, research
  07-Knowledge-Base/      ← industry knowledge
  08-Archive/             ← archived/spam (chinese_leads etc)
  08-Talent/              ← talent profiles
  09-Email-Archive/       ← ALL emails, both accounts
    Gmail-Captures/       ← n8n legacy emails
    Amazon-Leads/         ← parsed amazon leads
    Brand-Pitches/        ← parsed brand pitches
    attachments/          ← extracted attachments
```

No duplicate folders. One structure. Everything in git. Daily sync via gws CLI.

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

## Daily Sync (after setup)

```bash
cd ~/Documents/mbox-to-obsidian
./sync_both_accounts.sh 1    # sync last 1 day
./sync_both_accounts.sh 7    # sync last 7 days
```

Note: gws only supports one authed account at a time. The script syncs whichever account is logged in, then tells you to switch.
