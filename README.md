# MBOX to Obsidian Vault Importer

Converts Google Takeout MBOX exports into Obsidian markdown notes with YAML frontmatter. Built for ENT Agency's Second Brain vault.

## Scripts

| Script | Account | Date Cutoff |
|--------|---------|-------------|
| `mbox_to_obsidian.py` | marketingteam@entagency.co | Jan 2025+ |
| `mbox_to_obsidian_nickient.py` | marketingteam@nickient.com | None (all history) |

## Setup

```bash
git clone git@github.com:Entmarketingteam/mbox-to-obsidian.git
cd mbox-to-obsidian
pip install google-api-python-client google-auth google-auth-httplib2 google-auth-oauthlib
```

No extra deps needed beyond Python stdlib for the mbox scripts — the pip install is only if you need Gmail API access.

## Usage (nickient.com import)

1. Go to [takeout.google.com](https://takeout.google.com) logged in as `marketingteam@nickient.com`
2. Select **Gmail only** → "All mail Including Spam and Trash" → export as `.zip`
3. Download the zip
4. Edit `mbox_to_obsidian_nickient.py` — update these lines at the top:

```python
MBOX_ZIP = r"C:\Users\ethan.atchley\Downloads\NICKIENT_TAKEOUT.zip"  # ← actual zip filename
VAULT_INBOX = r"C:\Users\ethan.atchley\Documents\1st vault\01-Inbox\Gmail-Captures"  # ← vault path on this machine
VAULT_ATTACHMENTS = r"C:\Users\ethan.atchley\Documents\1st vault\01-Inbox\Gmail-Captures\attachments"
```

5. Run it:

```bash
python mbox_to_obsidian_nickient.py
```

## What it does

- Streams emails from the Takeout zip (no full extraction needed)
- Creates one `.md` file per email in `YYYY-MM-DD_Subject.md` format
- YAML frontmatter with: type, account, from, to, subject, date, labels, status
- Extracts PDF/CSV/XLSX/DOCX attachments to `attachments/` subfolder
- Skips Trash, Spam, Promotions, Social, Forums
- Deduplicates filenames (won't overwrite existing entagency.co emails)
- Truncates bodies over 15KB, skips messages over 5MB

## Output format

```markdown
---
type: email
account: "marketingteam@nickient.com"
from: "Brand Contact"
from_email: "contact@brand.com"
to: "Nicki Entenmann <marketingteam@nickient.com>"
subject: "Partnership Opportunity"
date: 2023-06-15T14:30:00
labels: ["Inbox", "Important"]
status: unprocessed
---

# Partnership Opportunity

**From:** Brand Contact <contact@brand.com>
**To:** Nicki Entenmann <marketingteam@nickient.com>
**Date:** 2023-06-15 14:30
**Account:** marketingteam@nickient.com
**Labels:** Inbox, Important

---

Email body here...
```

## Vault structure

Both scripts output to the same folder. The `account` frontmatter field distinguishes emails:

```
01-Inbox/Gmail-Captures/
  2022-03-15_Brand Collab Inquiry.md          ← nickient.com
  2025-01-06_Re Partner with AG1.md           ← entagency.co
  attachments/
    2022-03-15_contract.pdf
    2025-01-06_FEA_Ellen_Ludwig.pdf
```

Use Dataview in Obsidian to filter by account:

```dataview
TABLE subject, date
FROM "01-Inbox/Gmail-Captures"
WHERE account = "marketingteam@nickient.com"
SORT date DESC
```
