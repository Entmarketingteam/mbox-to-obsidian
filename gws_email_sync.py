"""
GWS CLI Email Sync → Obsidian Vault
Pulls emails from Gmail via `gws` CLI and writes them as markdown notes.
No n8n, no MCP server — just gws + Python + vault.

Usage:
  # First time: authenticate gws
  gws auth login

  # Sync recent emails (default: last 24 hours)
  python gws_email_sync.py

  # Sync last 7 days
  python gws_email_sync.py --days 7

  # Sync specific account
  python gws_email_sync.py --account marketingteam@nickient.com

  # Sync all history (careful — could be huge)
  python gws_email_sync.py --after 2021-01-01

  # Dry run — see what would be created without writing files
  python gws_email_sync.py --dry-run

  # Sync both accounts
  python gws_email_sync.py --account marketingteam@entagency.co
  python gws_email_sync.py --account marketingteam@nickient.com
"""

import json
import os
import re
import subprocess
import sys
import argparse
import base64
from datetime import datetime, timedelta
from html import unescape


# ── Config ──────────────────────────────────────────────────────────────────

_HOME = os.path.expanduser("~")
VAULT_BASE = os.path.join(_HOME, "Documents", "ENT-Agency-Vault")

VAULT_EMAIL_DIR = os.path.join(VAULT_BASE, "09-Email-Archive")
VAULT_ATTACHMENTS = os.path.join(VAULT_EMAIL_DIR, "attachments")

SKIP_LABELS = {"TRASH", "SPAM", "CATEGORY_PROMOTIONS", "CATEGORY_SOCIAL", "CATEGORY_FORUMS"}
MAX_BODY_LEN = 15000
MAX_RESULTS_PER_PAGE = 100

# Extensions to save as attachments
EXTRACT_EXTENSIONS = {".pdf", ".csv", ".xlsx", ".xls", ".docx", ".doc", ".txt"}


# ── GWS CLI Wrapper ────────────────────────────────────────────────────────

def gws_cmd(service, resource, method, params=None, sub_resource=None, page_all=False):
    """Run a gws CLI command and return parsed JSON."""
    cmd = ["gws", service, resource]
    if sub_resource:
        cmd.append(sub_resource)
    cmd.append(method)

    if params:
        cmd.extend(["--params", json.dumps(params)])
    if page_all:
        cmd.append("--page-all")

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

    if result.returncode != 0:
        error_msg = result.stderr.strip() or result.stdout.strip()
        if "401" in error_msg or "authError" in error_msg:
            print("ERROR: gws not authenticated. Run: gws auth login")
            sys.exit(1)
        raise RuntimeError(f"gws command failed: {error_msg}")

    output = result.stdout.strip()
    if not output:
        return {}

    # Handle NDJSON from --page-all
    if page_all:
        results = []
        for line in output.split("\n"):
            line = line.strip()
            if line:
                try:
                    results.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return results

    return json.loads(output)


def get_message_ids(query, max_pages=50):
    """Get all message IDs matching a Gmail query."""
    all_ids = []
    page_token = None
    pages = 0

    while pages < max_pages:
        params = {"userId": "me", "maxResults": MAX_RESULTS_PER_PAGE, "q": query}
        if page_token:
            params["pageToken"] = page_token

        result = gws_cmd("gmail", "users", "list", params=params, sub_resource="messages")
        messages = result.get("messages", [])
        all_ids.extend(msg["id"] for msg in messages)

        page_token = result.get("nextPageToken")
        pages += 1

        if not page_token:
            break

        if len(all_ids) % 500 == 0:
            print(f"  Found {len(all_ids)} messages so far...")

    return all_ids


def get_message(msg_id):
    """Get a single message with full content."""
    params = {"userId": "me", "id": msg_id, "format": "full"}
    return gws_cmd("gmail", "users", "get", params=params, sub_resource="messages")


def get_message_metadata(msg_id):
    """Get message metadata only (faster, for checking if we already have it)."""
    params = {
        "userId": "me",
        "id": msg_id,
        "format": "metadata",
        "metadataHeaders": ["Subject", "From", "To", "Date"]
    }
    return gws_cmd("gmail", "users", "get", params=params, sub_resource="messages")


# ── Email Parsing ──────────────────────────────────────────────────────────

def get_header(msg, name):
    """Extract a header value from a Gmail message."""
    headers = msg.get("payload", {}).get("headers", [])
    for h in headers:
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


def get_labels(msg):
    """Get label names from a message."""
    return set(msg.get("labelIds", []))


def parse_from(from_str):
    """Parse 'Name <email>' into (name, email)."""
    match = re.match(r'(.*?)\s*<(.+?)>', from_str)
    if match:
        name = match.group(1).strip().strip('"')
        email_addr = match.group(2)
        return name, email_addr
    return from_str, from_str


def parse_date(date_str):
    """Parse email date string to datetime."""
    if not date_str:
        return None

    # Try common formats
    for fmt in [
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S",
    ]:
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            return dt.replace(tzinfo=None)
        except ValueError:
            continue

    # Fallback: strip timezone info and try again
    cleaned = re.sub(r'\s*\([^)]*\)\s*$', '', date_str)
    cleaned = re.sub(r'\s*[+-]\d{4}\s*$', '', cleaned)
    for fmt in ["%a, %d %b %Y %H:%M:%S", "%d %b %Y %H:%M:%S"]:
        try:
            return datetime.strptime(cleaned.strip(), fmt)
        except ValueError:
            continue

    # Last resort: use internal timestamp
    return None


def html_to_text(html):
    """Convert HTML to readable text."""
    text = re.sub(r'<(style|script)[^>]*>.*?</\1>', '', html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<br\s*/?\s*>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</(p|div|tr|li|h[1-6])>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<li[^>]*>', '- ', text, flags=re.IGNORECASE)
    text = re.sub(r'<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', r'\2 (\1)', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<[^>]+>', '', text)
    text = unescape(text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'[ \t]+', ' ', text)
    return text.strip()


def get_body(payload):
    """Extract email body from Gmail message payload."""
    text_parts = []
    html_parts = []

    def walk_parts(part):
        mime = part.get("mimeType", "")
        body_data = part.get("body", {}).get("data", "")

        if "parts" in part:
            for sub in part["parts"]:
                walk_parts(sub)
        elif body_data:
            try:
                decoded = base64.urlsafe_b64decode(body_data).decode("utf-8", errors="replace")
            except Exception:
                return

            if mime == "text/plain":
                text_parts.append(decoded)
            elif mime == "text/html":
                html_parts.append(decoded)

    walk_parts(payload)

    if text_parts:
        body = "\n".join(text_parts)
    elif html_parts:
        body = html_to_text("\n".join(html_parts))
    else:
        body = "(no readable body)"

    if len(body) > MAX_BODY_LEN:
        body = body[:MAX_BODY_LEN] + "\n\n...(truncated)..."
    return body


def get_attachments(payload, date_prefix, attach_dir, seen_attach):
    """Extract and save attachments, return lists."""
    extracted = []
    all_names = []

    def walk_parts(part):
        fn = part.get("filename", "")
        if fn and part.get("body", {}).get("attachmentId"):
            all_names.append(fn)

            _, ext = os.path.splitext(fn)
            if ext.lower() in EXTRACT_EXTENSIONS:
                # We'd need another API call to get attachment data
                # For now, just record the name
                extracted.append((fn, None))

        for sub in part.get("parts", []):
            walk_parts(sub)

    walk_parts(payload)
    return extracted, all_names


# ── File Writing ───────────────────────────────────────────────────────────

def sanitize_filename(name, max_len=80):
    """Make a string safe for use as a filename."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    if len(name) > max_len:
        name = name[:max_len].rstrip()
    return name or "untitled"


def write_email_note(msg, account, output_dir, seen_filenames, dry_run=False):
    """Convert a Gmail message to a vault markdown note."""
    subject = get_header(msg, "Subject") or "(no subject)"
    from_str = get_header(msg, "From")
    to_str = get_header(msg, "To")
    date_str = get_header(msg, "Date")
    labels = get_labels(msg)

    # Skip unwanted labels
    if labels & SKIP_LABELS:
        return "skipped_label"

    # Parse date
    dt = parse_date(date_str)
    if not dt:
        # Fallback: use Gmail internalDate (ms since epoch)
        internal = msg.get("internalDate")
        if internal:
            dt = datetime.fromtimestamp(int(internal) / 1000)
        else:
            return "skipped_nodate"

    from_name, from_email = parse_from(from_str)

    # Build filename
    date_prefix = dt.strftime("%Y-%m-%d")
    safe_subj = sanitize_filename(subject, max_len=60)
    base_name = f"{date_prefix}_{safe_subj}"

    final_name = base_name
    counter = 1
    while final_name in seen_filenames:
        final_name = f"{base_name}_{counter}"
        counter += 1
    seen_filenames.add(final_name)

    if dry_run:
        return "would_create"

    # Get body
    body = get_body(msg.get("payload", {}))

    # Get attachment names
    _, all_attach_names = get_attachments(
        msg.get("payload", {}), date_prefix, VAULT_ATTACHMENTS, set()
    )

    # Clean up label names for display
    display_labels = sorted(labels - {"UNREAD"})

    note = f"""---
type: email
sender: "{from_name}"
sender_email: "{from_email}"
recipient: "{to_str[:200]}"
subject: "{subject.replace('"', "'")}"
email_date: {dt.strftime("%Y-%m-%dT%H:%M:%S")}
account: "{account}"
labels: [{', '.join(f'"{l}"' for l in display_labels)}]
related_brand:
related_campaign:
related_contact:
tags:
  - email
created: {date_prefix}
status: unprocessed
---

# {subject}

**From:** {from_str}
**To:** {to_str}
**Date:** {dt.strftime("%Y-%m-%d %H:%M")}
**Account:** {account}
**Labels:** {', '.join(display_labels) if display_labels else 'none'}
"""
    if all_attach_names:
        note += f"**Attachments:** {', '.join(all_attach_names)}\n"

    note += f"\n---\n\n{body}\n"

    filepath = os.path.join(output_dir, f"{final_name}.md")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(note)

    return "created"


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Sync Gmail → Obsidian vault via gws CLI")
    parser.add_argument("--account", default="marketingteam@entagency.co",
                        help="Gmail account (default: marketingteam@entagency.co)")
    parser.add_argument("--days", type=int, default=1,
                        help="Sync emails from the last N days (default: 1)")
    parser.add_argument("--after", type=str, default=None,
                        help="Sync emails after this date (YYYY-MM-DD). Overrides --days")
    parser.add_argument("--query", type=str, default=None,
                        help="Custom Gmail search query (overrides --days and --after)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be created without writing files")
    parser.add_argument("--vault", type=str, default=None,
                        help="Override vault base path")
    parser.add_argument("--limit", type=int, default=None,
                        help="Max number of emails to process")
    args = parser.parse_args()

    global VAULT_EMAIL_DIR, VAULT_ATTACHMENTS
    if args.vault:
        VAULT_EMAIL_DIR = os.path.join(args.vault, "09-Email-Archive")
        VAULT_ATTACHMENTS = os.path.join(VAULT_EMAIL_DIR, "attachments")

    # Build query
    if args.query:
        query = args.query
    elif args.after:
        query = f"after:{args.after}"
    else:
        after_date = (datetime.now() - timedelta(days=args.days)).strftime("%Y/%m/%d")
        query = f"after:{after_date}"

    print(f"GWS Email Sync → Obsidian")
    print(f"=========================")
    print(f"Account:  {args.account}")
    print(f"Query:    {query}")
    print(f"Output:   {VAULT_EMAIL_DIR}")
    print(f"Dry run:  {args.dry_run}")
    print()

    # Ensure output dirs exist
    if not args.dry_run:
        os.makedirs(VAULT_EMAIL_DIR, exist_ok=True)
        os.makedirs(VAULT_ATTACHMENTS, exist_ok=True)

    # Pre-load existing filenames
    existing = set()
    if os.path.exists(VAULT_EMAIL_DIR):
        for f in os.listdir(VAULT_EMAIL_DIR):
            if f.endswith(".md"):
                existing.add(os.path.splitext(f)[0])
    print(f"Found {len(existing)} existing notes")

    # Get message IDs
    print(f"Searching for messages...")
    try:
        msg_ids = get_message_ids(query)
    except RuntimeError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    if args.limit:
        msg_ids = msg_ids[:args.limit]

    print(f"Found {len(msg_ids)} messages to process")
    print()

    if not msg_ids:
        print("Nothing to sync.")
        return

    # Process messages
    stats = {"created": 0, "would_create": 0, "skipped_label": 0,
             "skipped_nodate": 0, "errors": 0, "skipped_exists": 0}
    seen_filenames = set(existing)

    for i, msg_id in enumerate(msg_ids, 1):
        try:
            # First get metadata to check if we already have it
            meta = get_message_metadata(msg_id)
            subject = get_header(meta, "Subject") or "(no subject)"
            date_str = get_header(meta, "Date")
            dt = parse_date(date_str)

            if dt:
                date_prefix = dt.strftime("%Y-%m-%d")
                safe_subj = sanitize_filename(subject, max_len=60)
                check_name = f"{date_prefix}_{safe_subj}"
                if check_name in existing:
                    stats["skipped_exists"] += 1
                    continue

            # Get full message
            msg = get_message(msg_id)
            result = write_email_note(msg, args.account, VAULT_EMAIL_DIR, seen_filenames, args.dry_run)
            stats[result] = stats.get(result, 0) + 1

            if args.dry_run and result == "would_create":
                print(f"  Would create: {date_prefix}_{safe_subj}.md")

        except Exception as e:
            stats["errors"] += 1
            if stats["errors"] <= 5:
                print(f"  Error on message {i}: {e}")

        if i % 50 == 0:
            created = stats.get("created", 0) + stats.get("would_create", 0)
            print(f"  Processed {i}/{len(msg_ids)}... ({created} new)")

    print()
    print(f"Done! Processed {len(msg_ids)} messages.")
    if args.dry_run:
        print(f"  Would create:    {stats['would_create']}")
    else:
        print(f"  Created:         {stats['created']}")
    print(f"  Already existed: {stats['skipped_exists']}")
    print(f"  Skipped (label): {stats['skipped_label']}")
    print(f"  Skipped (date):  {stats['skipped_nodate']}")
    print(f"  Errors:          {stats['errors']}")


if __name__ == "__main__":
    main()
