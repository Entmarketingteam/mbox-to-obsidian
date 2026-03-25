"""
Migrate parsed mbox_extract data into the Obsidian vault.
Maps each category folder to the correct vault location.

Run inspect_mbox_extract.py FIRST to generate mbox_extract_report.json,
then run this script.

Usage:
  python migrate_mbox_extract.py
  python migrate_mbox_extract.py --source "D:\path\to\mbox_extract"
  python migrate_mbox_extract.py --dry-run
  python migrate_mbox_extract.py --category entenmann
"""

import os
import sys
import re
import shutil
import json
import argparse
import platform
from datetime import datetime
from html import unescape

# ── Config ──────────────────────────────────────────────────────────────────

# Source: the mbox_extract folder on the ejatc machine
DEFAULT_SOURCE = r"C:\Users\ejatc\Documents\mbox_extract"

# Destination: vault paths
if platform.system() == "Darwin":
    VAULT_BASE = "/Users/ethanatchley/Documents/obsidian-vault"
else:
    VAULT_BASE = r"C:\Users\ethan.atchley\Documents\1st vault"

# Where each mbox_extract category maps to in the vault
CATEGORY_MAP = {
    "entenmann": {
        "vault_folder": "09-Email-Archive",
        "account": "marketingteam@nickient.com",
        "tags": ["email", "nickient", "entenmann"],
        "description": "Nicki's full email history (90K emails)",
    },
    "amazon_leads": {
        "vault_folder": "09-Email-Archive/Amazon-Leads",
        "account": "marketingteam@nickient.com",
        "tags": ["email", "amazon", "lead"],
        "description": "Amazon brand outreach leads (50K)",
    },
    "brand_pitches": {
        "vault_folder": "09-Email-Archive/Brand-Pitches",
        "account": "marketingteam@nickient.com",
        "tags": ["email", "brand-pitch"],
        "description": "Inbound brand pitches (15K companies)",
    },
    "chinese_leads": {
        "vault_folder": "08-Archive/Chinese-Leads",
        "account": "marketingteam@nickient.com",
        "tags": ["email", "international", "archived"],
        "description": "International/Chinese brand leads (31K) — mostly spam, archive",
    },
    "healthyish": {
        "vault_folder": "03-Products/Healthyiish/Emails",
        "account": "marketingteam@nickient.com",
        "tags": ["email", "healthyiish", "product"],
        "description": "Healthyiish brand emails",
    },
    "nova": {
        "vault_folder": "03-Products/NOVA/Emails",
        "account": "marketingteam@nickient.com",
        "tags": ["email", "nova", "product"],
        "description": "NOVA project emails",
    },
    "product_launch": {
        "vault_folder": "03-Products/Launch-Emails",
        "account": "marketingteam@nickient.com",
        "tags": ["email", "product-launch"],
        "description": "Product launch communications",
    },
    "recent_attachments": {
        "vault_folder": "09-Email-Archive/attachments/2024-plus",
        "account": "marketingteam@nickient.com",
        "tags": [],
        "description": "Recent attachments (2024+) — binary files, just copy",
        "copy_only": True,  # Don't process, just copy files
    },
}

MAX_BODY_LEN = 15000


# ── Helpers ────────────────────────────────────────────────────────────────

def sanitize_filename(name, max_len=80):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    if len(name) > max_len:
        name = name[:max_len].rstrip()
    return name or "untitled"


def detect_format(filepath):
    """Detect if a file is markdown with frontmatter, raw email, or plain text."""
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            first_line = f.readline().strip()
            if first_line == "---":
                return "markdown_frontmatter"
            elif first_line.startswith("From:") or first_line.startswith("Subject:"):
                return "raw_email_headers"
            elif first_line.startswith("From "):
                return "mbox_message"
            elif first_line.startswith("{"):
                return "json"
            else:
                return "plain_text"
    except Exception:
        return "binary"


def convert_to_vault_note(filepath, category_config, seen_filenames):
    """Read a parsed email file and convert to vault markdown format.
    Returns (output_filename, note_content) or None if should be skipped."""

    fmt = detect_format(filepath)

    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except Exception:
        return None

    # If it already has frontmatter, check if it matches our format
    if fmt == "markdown_frontmatter":
        # Already processed — might just need to update frontmatter fields
        # Extract existing frontmatter
        parts = content.split("---", 2)
        if len(parts) >= 3:
            frontmatter = parts[1]
            body = parts[2]

            # Check if it already has our vault fields
            if "sender:" in frontmatter or "from:" in frontmatter:
                # Might already be in vault format, check for missing fields
                if "related_brand:" not in frontmatter:
                    # Add missing vault fields to frontmatter
                    extra_fields = "\nrelated_brand:\nrelated_campaign:\nrelated_contact:"
                    tag_line = "\ntags:\n" + "\n".join(f"  - {t}" for t in category_config["tags"])
                    if "tags:" not in frontmatter:
                        frontmatter += tag_line
                    frontmatter += extra_fields
                    content = f"---{frontmatter}---{body}"

            # Use existing filename or derive from content
            basename = os.path.splitext(os.path.basename(filepath))[0]
            final_name = basename
            counter = 1
            while final_name in seen_filenames:
                final_name = f"{basename}_{counter}"
                counter += 1
            seen_filenames.add(final_name)
            return final_name, content

    elif fmt == "json":
        # JSON format — parse and convert
        try:
            data = json.loads(content)
            subject = data.get("subject", "(no subject)")
            from_name = data.get("from", data.get("sender", ""))
            from_email = data.get("from_email", data.get("sender_email", ""))
            to = data.get("to", data.get("recipient", ""))
            date_str = data.get("date", data.get("email_date", ""))
            body = data.get("body", data.get("content", ""))
            labels = data.get("labels", [])

            if isinstance(date_str, str) and "T" in date_str:
                date_prefix = date_str[:10]
            else:
                date_prefix = "unknown-date"

            tags = category_config["tags"]
            account = category_config["account"]

            safe_subj = sanitize_filename(subject, max_len=60)
            base_name = f"{date_prefix}_{safe_subj}"
            final_name = base_name
            counter = 1
            while final_name in seen_filenames:
                final_name = f"{base_name}_{counter}"
                counter += 1
            seen_filenames.add(final_name)

            if len(body) > MAX_BODY_LEN:
                body = body[:MAX_BODY_LEN] + "\n\n...(truncated)..."

            note = f"""---
type: email
sender: "{from_name}"
sender_email: "{from_email}"
recipient: "{to[:200]}"
subject: "{subject.replace('"', "'")}"
email_date: {date_str}
account: "{account}"
labels: [{', '.join(f'"{l}"' for l in labels) if isinstance(labels, list) else ''}]
related_brand:
related_campaign:
related_contact:
tags:
{chr(10).join(f'  - {t}' for t in tags)}
created: {date_prefix}
status: unprocessed
---

# {subject}

**From:** {from_name} <{from_email}>
**To:** {to}
**Date:** {date_str}
**Account:** {account}

---

{body}
"""
            return final_name, note

        except json.JSONDecodeError:
            pass

    # Fallback: treat as plain text, wrap in minimal frontmatter
    basename = os.path.splitext(os.path.basename(filepath))[0]
    safe_name = sanitize_filename(basename)
    final_name = safe_name
    counter = 1
    while final_name in seen_filenames:
        final_name = f"{safe_name}_{counter}"
        counter += 1
    seen_filenames.add(final_name)

    tags = category_config["tags"]
    account = category_config["account"]

    note = f"""---
type: email
account: "{account}"
tags:
{chr(10).join(f'  - {t}' for t in tags)}
  - needs-processing
status: unprocessed
created: {datetime.now().strftime("%Y-%m-%d")}
---

# {basename}

---

{content[:MAX_BODY_LEN]}
"""
    return final_name, note


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Migrate mbox_extract folders into Obsidian vault")
    parser.add_argument("--source", default=DEFAULT_SOURCE,
                        help=f"Path to mbox_extract folder (default: {DEFAULT_SOURCE})")
    parser.add_argument("--vault", default=VAULT_BASE,
                        help=f"Path to vault (default: {VAULT_BASE})")
    parser.add_argument("--category", default=None,
                        help="Only migrate a specific category (e.g., entenmann, brand_pitches)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be done without writing files")
    parser.add_argument("--limit", type=int, default=None,
                        help="Max files to process per category")
    args = parser.parse_args()

    source = args.source
    vault = args.vault

    print(f"Migrate mbox_extract → Obsidian Vault")
    print(f"=====================================")
    print(f"Source: {source}")
    print(f"Vault:  {vault}")
    print(f"Dry run: {args.dry_run}")
    print()

    if not os.path.exists(source):
        print(f"ERROR: Source folder not found: {source}")
        print("Pass --source with the correct path.")
        sys.exit(1)

    categories = [args.category] if args.category else list(CATEGORY_MAP.keys())

    for cat_name in categories:
        if cat_name not in CATEGORY_MAP:
            print(f"WARNING: Unknown category '{cat_name}', skipping")
            continue

        cat = CATEGORY_MAP[cat_name]
        src_path = os.path.join(source, cat_name)

        if not os.path.exists(src_path):
            print(f"--- {cat_name} --- NOT FOUND at {src_path}, skipping")
            continue

        dest_path = os.path.join(vault, cat["vault_folder"])
        print(f"--- {cat_name} ---")
        print(f"  {cat['description']}")
        print(f"  Source: {src_path}")
        print(f"  Dest:   {dest_path}")

        # Count files
        files = []
        for root, dirs, filenames in os.walk(src_path):
            for fn in filenames:
                files.append(os.path.join(root, fn))

        print(f"  Files:  {len(files)}")

        if args.limit:
            files = files[:args.limit]
            print(f"  Limited to: {args.limit}")

        if args.dry_run:
            # Just show stats
            ext_counts = {}
            for f in files:
                _, ext = os.path.splitext(f)
                ext_counts[ext.lower()] = ext_counts.get(ext.lower(), 0) + 1
            print(f"  Extensions: {ext_counts}")

            # Sample format detection
            for f in files[:3]:
                fmt = detect_format(f)
                print(f"  Sample: {os.path.basename(f)} → {fmt}")
            print()
            continue

        # Create destination
        os.makedirs(dest_path, exist_ok=True)

        # Copy-only mode (for attachments)
        if cat.get("copy_only"):
            copied = 0
            for f in files:
                dest_file = os.path.join(dest_path, os.path.basename(f))
                if not os.path.exists(dest_file):
                    shutil.copy2(f, dest_file)
                    copied += 1
            print(f"  Copied: {copied} files")
            print()
            continue

        # Process emails
        stats = {"created": 0, "skipped": 0, "errors": 0}
        seen_filenames = set()

        # Pre-load existing
        if os.path.exists(dest_path):
            for f in os.listdir(dest_path):
                if f.endswith(".md"):
                    seen_filenames.add(os.path.splitext(f)[0])

        for i, filepath in enumerate(files, 1):
            try:
                result = convert_to_vault_note(filepath, cat, seen_filenames)
                if result is None:
                    stats["skipped"] += 1
                    continue

                final_name, content = result
                out_path = os.path.join(dest_path, f"{final_name}.md")
                with open(out_path, "w", encoding="utf-8") as f:
                    f.write(content)
                stats["created"] += 1

            except Exception as e:
                stats["errors"] += 1
                if stats["errors"] <= 5:
                    print(f"  Error: {os.path.basename(filepath)}: {e}")

            if i % 1000 == 0:
                print(f"  Processed {i}/{len(files)}... ({stats['created']} created)")

        print(f"  Created: {stats['created']}")
        print(f"  Skipped: {stats['skipped']}")
        print(f"  Errors:  {stats['errors']}")
        print()

    print("Done!")


if __name__ == "__main__":
    main()
