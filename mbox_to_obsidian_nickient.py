"""
MBOX -> Obsidian Vault Importer (nickient.com)
Parses Google Takeout MBOX export and creates markdown notes in the vault.
Streams from zip -- no full extraction needed.
Extracts PDF + CSV attachments.

Usage:
  python mbox_to_obsidian_nickient.py [path_to_takeout.zip]

If no argument given, uses MBOX_ZIP default below.
"""

import zipfile
import email
import email.utils
import email.header
import email.policy
import os
import re
import sys
from datetime import datetime
from html import unescape

# ── Config ──────────────────────────────────────────────────────────────────
# Cross-platform: use home directory detection
_HOME = os.path.expanduser("~")
MBOX_ZIP = os.path.join(_HOME, "Downloads", "NICKIENT_TAKEOUT.zip")  # ← UPDATE THIS
VAULT_BASE = os.path.join(_HOME, "Documents", "ENT-Agency-Vault")

# Override with CLI argument if provided
if len(sys.argv) > 1:
    MBOX_ZIP = sys.argv[1]

VAULT_INBOX = os.path.join(VAULT_BASE, "09-Email-Archive")
VAULT_ATTACHMENTS = os.path.join(VAULT_BASE, "09-Email-Archive", "attachments")
MBOX_ENTRY = "Takeout/Mail/All mail Including Spam and Trash.mbox"
ACCOUNT = "marketingteam@nickient.com"

SKIP_LABELS = {"Trash", "Spam", "Category Promotions", "Category Social", "Category Forums"}
DATE_CUTOFF = None  # No cutoff — import everything back to 2021
MAX_BODY_LEN = 15000
MAX_MSG_BYTES = 5 * 1024 * 1024

# Extensions to extract as attachments
EXTRACT_EXTENSIONS = {".pdf", ".csv", ".xlsx", ".xls", ".docx", ".doc", ".txt"}

# ── Helpers ─────────────────────────────────────────────────────────────────

def decode_header(raw):
    if not raw:
        return ""
    try:
        parts = email.header.decode_header(raw)
    except Exception:
        return str(raw)
    decoded = []
    for part, charset in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(part)
    return " ".join(decoded).strip()


def sanitize_filename(name, max_len=80):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    if len(name) > max_len:
        name = name[:max_len].rstrip()
    return name or "untitled"


def html_to_text(html):
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


def get_body(msg):
    text_parts = []
    html_parts = []

    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            cd = str(part.get("Content-Disposition", ""))
            if "attachment" in cd:
                continue
            try:
                payload = part.get_payload(decode=True)
                if not payload:
                    continue
                charset = part.get_content_charset() or "utf-8"
                text = payload.decode(charset, errors="replace")
            except Exception:
                continue
            if ct == "text/plain":
                text_parts.append(text)
            elif ct == "text/html":
                html_parts.append(text)
    else:
        try:
            payload = msg.get_payload(decode=True)
            if payload:
                charset = msg.get_content_charset() or "utf-8"
                text = payload.decode(charset, errors="replace")
                if msg.get_content_type() == "text/html":
                    html_parts.append(text)
                else:
                    text_parts.append(text)
        except Exception:
            pass

    if text_parts:
        body = "\n".join(text_parts)
    elif html_parts:
        body = html_to_text("\n".join(html_parts))
    else:
        body = "(no readable body)"

    if len(body) > MAX_BODY_LEN:
        body = body[:MAX_BODY_LEN] + "\n\n...(truncated)..."
    return body


def parse_date(msg):
    raw = msg.get("Date", "")
    if not raw:
        return None
    try:
        parsed = email.utils.parsedate_to_datetime(raw)
        return parsed.replace(tzinfo=None)
    except Exception:
        return None


def get_labels(msg):
    raw = msg.get("X-Gmail-Labels", "")
    if not raw:
        return set()
    return {l.strip() for l in raw.split(",")}


def extract_attachments(msg, date_prefix, attach_dir, seen_attach):
    """Extract PDF/CSV/doc attachments and return list of (original_name, saved_path)."""
    extracted = []
    all_names = []

    if not msg.is_multipart():
        return extracted, all_names

    for part in msg.walk():
        cd = str(part.get("Content-Disposition", ""))
        if "attachment" not in cd:
            continue

        fn = part.get_filename()
        if not fn:
            continue
        fn = decode_header(fn)
        all_names.append(fn)

        # Check extension
        _, ext = os.path.splitext(fn)
        if ext.lower() not in EXTRACT_EXTENSIONS:
            continue

        try:
            payload = part.get_payload(decode=True)
            if not payload:
                continue
        except Exception:
            continue

        # Save with date prefix to avoid collisions
        safe_fn = sanitize_filename(fn, max_len=100)
        save_name = f"{date_prefix}_{safe_fn}"

        # Deduplicate
        final_save = save_name
        counter = 1
        while final_save in seen_attach:
            name_part, ext_part = os.path.splitext(save_name)
            final_save = f"{name_part}_{counter}{ext_part}"
            counter += 1
        seen_attach.add(final_save)

        save_path = os.path.join(attach_dir, final_save)
        with open(save_path, "wb") as f:
            f.write(payload)

        extracted.append((fn, final_save))

    return extracted, all_names


def process_message(raw_bytes, output_dir, attach_dir, seen_filenames, seen_attach, attach_stats):
    try:
        msg = email.message_from_bytes(raw_bytes, policy=email.policy.compat32)
    except Exception:
        return "errors"

    labels = get_labels(msg)
    if labels & SKIP_LABELS:
        return "skipped_label"

    dt = parse_date(msg)
    if not dt:
        return "skipped_nodate"
    if DATE_CUTOFF and dt < DATE_CUTOFF:
        return "skipped_old"

    subject = decode_header(msg.get("Subject", "")) or "(no subject)"
    from_addr = decode_header(msg.get("From", ""))
    to_addr = decode_header(msg.get("To", ""))
    body = get_body(msg)
    display_labels = sorted(labels - {"Unread", "Opened"})

    date_str = dt.strftime("%Y-%m-%d")
    safe_subj = sanitize_filename(subject, max_len=60)
    base_name = f"{date_str}_{safe_subj}"

    final_name = base_name
    counter = 1
    while final_name in seen_filenames:
        final_name = f"{base_name}_{counter}"
        counter += 1
    seen_filenames.add(final_name)

    # Extract attachments
    extracted, all_attach_names = extract_attachments(msg, date_str, attach_dir, seen_attach)
    attach_stats["extracted"] += len(extracted)

    from_name = from_addr
    from_email_addr = ""
    m_match = re.match(r'(.*?)\s*<(.+?)>', from_addr)
    if m_match:
        from_name = m_match.group(1).strip().strip('"')
        from_email_addr = m_match.group(2)

    # Build attachment links for extracted files
    attach_links = []
    for orig_name, saved_name in extracted:
        attach_links.append(f"[[attachments/{saved_name}|{orig_name}]]")

    # Use the vault's 09-Email-Archive frontmatter schema
    note = f"""---
type: email
sender: "{from_name}"
sender_email: "{from_email_addr}"
recipient: "{to_addr[:200]}"
subject: "{subject.replace('"', "'")}"
email_date: {dt.strftime("%Y-%m-%dT%H:%M:%S")}
account: "{ACCOUNT}"
labels: [{', '.join(f'"{l}"' for l in display_labels)}]
related_brand:
related_campaign:
related_contact:
tags:
  - email
  - nickient
created: {date_str}
status: unprocessed
---

# {subject}

**From:** {from_addr}
**To:** {to_addr}
**Date:** {dt.strftime("%Y-%m-%d %H:%M")}
**Account:** {ACCOUNT}
**Labels:** {', '.join(display_labels) if display_labels else 'none'}
"""
    if all_attach_names:
        note += f"**Attachments:** {', '.join(all_attach_names)}\n"
    if attach_links:
        note += "\n**Saved attachments:**\n"
        for link in attach_links:
            note += f"- {link}\n"

    note += f"\n---\n\n{body}\n"

    filepath = os.path.join(output_dir, f"{final_name}.md")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(note)

    return "created"


FROM_LINE_RE = re.compile(rb'^From \S+.*\d{4}\s*$')

def stream_mbox_from_zip(zip_path, entry_name):
    """Yield individual email messages as raw bytes by streaming from zip."""
    with zipfile.ZipFile(zip_path) as zf:
        with zf.open(entry_name) as f:
            current_msg_size = 0
            current_msg = []
            in_message = False
            too_big = False

            leftover = b""
            chunk_size = 4 * 1024 * 1024

            while True:
                chunk = f.read(chunk_size)
                if not chunk and not leftover:
                    break

                data = leftover + chunk
                lines = data.split(b"\n")

                if chunk:
                    leftover = lines.pop()
                else:
                    leftover = b""

                for line in lines:
                    stripped = line.rstrip(b"\r")

                    if FROM_LINE_RE.match(stripped):
                        if in_message and current_msg and not too_big:
                            yield b"\n".join(current_msg)
                        current_msg = []
                        current_msg_size = 0
                        too_big = False
                        in_message = True
                    elif in_message:
                        line_len = len(line) + 1
                        current_msg_size += line_len
                        if current_msg_size > MAX_MSG_BYTES:
                            if not too_big:
                                too_big = True
                                current_msg = []
                        else:
                            current_msg.append(line)

            if current_msg and in_message and not too_big:
                yield b"\n".join(current_msg)


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    print("MBOX -> Obsidian Importer (nickient.com)")
    print("========================================")
    print(f"Platform: {sys.platform}")
    print(f"Source: {MBOX_ZIP}")
    print(f"Output: {VAULT_INBOX}")
    print(f"Account: {ACCOUNT}")
    print(f"Cutoff: {DATE_CUTOFF or 'none (all history)'}")
    print(f"Skip labels: {SKIP_LABELS}")
    print(f"Extract attachments: {EXTRACT_EXTENSIONS}")
    print()

    if not os.path.exists(MBOX_ZIP):
        print(f"ERROR: Takeout zip not found at {MBOX_ZIP}")
        print()
        print("Usage: python mbox_to_obsidian_nickient.py [path_to_takeout.zip]")
        print()
        print("Or update MBOX_ZIP at the top of this script.")
        sys.exit(1)

    os.makedirs(VAULT_INBOX, exist_ok=True)
    os.makedirs(VAULT_ATTACHMENTS, exist_ok=True)

    # Pre-load existing filenames to avoid overwriting
    existing = set()
    for f in os.listdir(VAULT_INBOX):
        if f.endswith(".md"):
            existing.add(os.path.splitext(f)[0])
    print(f"Found {len(existing)} existing notes (will not overwrite)")
    print("Streaming and parsing emails from zip...")
    print()

    stats = {"created": 0, "skipped_label": 0, "skipped_old": 0, "skipped_nodate": 0, "errors": 0}
    attach_stats = {"extracted": 0}
    seen_filenames = set(existing)  # Start with existing to avoid collisions
    seen_attach = set()
    total = 0

    for raw_msg in stream_mbox_from_zip(MBOX_ZIP, MBOX_ENTRY):
        total += 1
        try:
            result = process_message(raw_msg, VAULT_INBOX, VAULT_ATTACHMENTS, seen_filenames, seen_attach, attach_stats)
            stats[result] = stats.get(result, 0) + 1
        except Exception as e:
            stats["errors"] += 1
            if stats["errors"] <= 5:
                print(f"  Error on email #{total}: {e}")

        if total % 500 == 0:
            print(f"  Processed {total}... ({stats['created']} created, {attach_stats['extracted']} attachments)")

    print()
    print(f"Done! Processed {total} emails.")
    print(f"  Created:          {stats['created']}")
    print(f"  Attachments saved:{attach_stats['extracted']}")
    print(f"  Skipped (label):  {stats['skipped_label']}")
    print(f"  Skipped (old):    {stats['skipped_old']}")
    print(f"  Skipped (no date):{stats['skipped_nodate']}")
    print(f"  Errors:           {stats['errors']}")
    print(f"\nNotes saved to: {VAULT_INBOX}")
    print(f"Attachments saved to: {VAULT_ATTACHMENTS}")


if __name__ == "__main__":
    main()
