"""
Email Spam Filter & Recipient Harvester

Scans the email archive for mass-outreach spam (Amazon collaboration pitches,
Chinese seller blasts, etc.), extracts all recipient emails from those messages,
and generates site:instagram.com search queries to reverse-engineer the
Instagram profiles those emails were scraped from.

Use cases:
  - Identify spam/mass-blast emails hitting Nicki's inbox
  - Extract the creator email lists that spammers compiled
  - Find Instagram profiles linked to those emails
  - Surface potential micro-influencer contacts for agency outreach

Usage:
    python email_spam_filter.py                          # scan + report
    python email_spam_filter.py --output results.csv     # export CSV
    python email_spam_filter.py --dry-run                # preview only
    python email_spam_filter.py --min-recipients 10      # adjust threshold
    python email_spam_filter.py --scan-mbox takeout.mbox # scan raw mbox file
"""

# ── Windows UTF-8 fix ────────────────────────────────────────────────────────
import sys
import io
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import os
import re
import csv
import json
import email
import mailbox
import argparse
import urllib.parse
from datetime import datetime
from pathlib import Path
from collections import Counter


# ── Config ───────────────────────────────────────────────────────────────────

_HOME = os.path.expanduser("~")
VAULT = os.path.join(_HOME, "Documents", "ENT-Agency-Vault")
EMAIL_DIR = os.path.join(VAULT, "09-Email-Archive")

# Minimum number of recipients to flag as mass-blast
DEFAULT_MIN_RECIPIENTS = 5

# ── Spam Detection Patterns ─────────────────────────────────────────────────

# Keywords in subject/body that indicate Amazon seller spam
AMAZON_SPAM_KEYWORDS = [
    r"amazon\s+(collaboration|collab|partnership|influencer|gifting)",
    r"free\s+(product|item|sample|gift)",
    r"(product|item)\s+review",
    r"what\s+(size|color|shade)\s+(do\s+you|would\s+you|are\s+you)",
    r"send\s+you\s+(a\s+)?free",
    r"love\s+your\s+style",
    r"love\s+your\s+(content|feed|page|profile|posts?)",
    r"collaboration\s+opportunity",
    r"gifting\s+opportunity",
    r"summer\s+fashion\s+collaboration",
    r"would\s+you\s+like\s+to\s+(try|receive|test)",
    r"we\s+would\s+love\s+to\s+send",
    r"complimentary\s+(product|item|gift)",
    r"amazon\.com/(dp|gp|.+/dp)/[A-Z0-9]{10}",
    r"amzn\.(to|com)/",
    r"check\s+out\s+(our|the)\s+(product|listing|item)",
]

AMAZON_SPAM_RE = re.compile(
    "|".join(AMAZON_SPAM_KEYWORDS),
    re.IGNORECASE,
)

# Broader mass-outreach spam patterns (not just Amazon)
MASS_OUTREACH_KEYWORDS = [
    r"(hi|hey|hello)\s+(babe|beautiful|gorgeous|hun|lovely|dear)\b",
    r"reaching\s+out\s+(to|because)",
    r"came\s+across\s+your\s+(page|profile|account|content)",
    r"saw\s+your\s+(page|profile|account|content|instagram)",
    r"brand\s+ambassador",
    r"PR\s+(package|list|gifting)",
    r"UGC\s+(creator|content|opportunity)",
    r"we('re|\s+are)\s+(a|an)\s+(brand|company|startup)",
    r"paid\s+collaboration",
]

MASS_OUTREACH_RE = re.compile(
    "|".join(MASS_OUTREACH_KEYWORDS),
    re.IGNORECASE,
)

# Our own email addresses (never harvest these)
OWN_EMAILS = {
    "marketingteam@entagency.co",
    "marketingteam@nickient.com",
    "nicki@entagency.co",
    "nicki@nickient.com",
}

# Generic domains we skip when harvesting (the sender, not recipients)
GENERIC_SENDER_DOMAINS = {
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "icloud.com",
    "aol.com", "live.com", "me.com", "msn.com", "comcast.net",
    "protonmail.com", "proton.me", "mail.com", "qq.com", "163.com",
    "126.com", "foxmail.com",
}


# ── Email Address Extraction ────────────────────────────────────────────────

EMAIL_RE = re.compile(
    r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}',
)


def extract_emails_from_header(header_value):
    """Extract all email addresses from a To/CC/BCC header."""
    if not header_value:
        return []
    return EMAIL_RE.findall(header_value)


def extract_all_recipients(to_str, cc_str="", bcc_str=""):
    """Extract unique recipient emails from To + CC + BCC headers."""
    all_emails = set()
    for header in [to_str, cc_str, bcc_str]:
        for addr in extract_emails_from_header(header):
            addr_lower = addr.lower().strip()
            if addr_lower not in OWN_EMAILS:
                all_emails.add(addr_lower)
    return sorted(all_emails)


# ── Instagram Search URL Generator ──────────────────────────────────────────

def make_instagram_search_url(email_addr):
    """Generate a Google search URL: site:instagram.com "email" """
    query = f'site:instagram.com "{email_addr}"'
    return f"https://www.google.com/search?q={urllib.parse.quote(query)}"


def make_instagram_search_query(email_addr):
    """Return the raw search query string."""
    return f'site:instagram.com "{email_addr}"'


# ── Vault-based Scanning (markdown email notes) ─────────────────────────────

def parse_frontmatter(text):
    """Parse YAML frontmatter from markdown. Returns (dict, body)."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    fm_text = text[3:end].strip()
    body = text[end + 4:]
    fm = {}
    for line in fm_text.split("\n"):
        if ":" in line and not line.strip().startswith("-") and not line.strip().startswith("#"):
            key, _, val = line.partition(":")
            fm[key.strip()] = val.strip().strip('"').strip("'")
    return fm, body


def scan_vault_emails(email_dir, min_recipients):
    """
    Scan vault email notes for mass-outreach spam.
    Returns list of dicts with spam email details.
    """
    results = []

    if not os.path.isdir(email_dir):
        print(f"  [WARN] Email directory not found: {email_dir}")
        return results

    md_files = []
    for root, dirs, filenames in os.walk(email_dir):
        # Skip attachment dirs
        if os.path.basename(root) in ("attachments",):
            continue
        for fname in filenames:
            if fname.endswith(".md") and not fname.startswith("_"):
                md_files.append(os.path.join(root, fname))

    print(f"  Scanning {len(md_files)} email notes...")

    for fpath in sorted(md_files):
        try:
            with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
        except Exception:
            continue

        fm, body = parse_frontmatter(text)

        # Get recipient info
        to_str = fm.get("recipient", "")
        # Also check body for **To:** line which may have full recipient list
        to_body_match = re.search(r'\*\*To:\*\*\s*(.+?)(?:\n\*\*|\n---|\n#|\Z)',
                                  body, re.DOTALL)
        if to_body_match:
            to_str += " " + to_body_match.group(1)

        recipients = extract_all_recipients(to_str)

        # Get sender info
        sender = fm.get("sender", "")
        sender_email = fm.get("sender_email", "")
        subject = fm.get("subject", "")
        email_date = fm.get("email_date", fm.get("created", ""))

        # Combine subject + body for keyword matching
        full_text = f"{subject}\n{body}"

        # Scoring: determine if this is spam
        score = 0
        flags = []

        # High recipient count is a strong signal
        if len(recipients) >= min_recipients:
            score += 3
            flags.append(f"mass-blast ({len(recipients)} recipients)")

        # Amazon spam keywords
        amazon_matches = AMAZON_SPAM_RE.findall(full_text)
        if amazon_matches:
            score += 2
            flags.append(f"amazon-spam ({len(amazon_matches)} keyword hits)")

        # Amazon product links
        amazon_links = re.findall(
            r'https?://(?:www\.)?amazon\.com[^\s)"\]]*',
            full_text, re.IGNORECASE
        )
        amzn_links = re.findall(
            r'https?://amzn\.(to|com)/[^\s)"\]]*',
            full_text, re.IGNORECASE
        )
        if amazon_links or amzn_links:
            score += 2
            flags.append(f"amazon-links ({len(amazon_links) + len(amzn_links)})")

        # General mass-outreach patterns
        outreach_matches = MASS_OUTREACH_RE.findall(full_text)
        if outreach_matches:
            score += 1
            flags.append(f"outreach-patterns ({len(outreach_matches)} hits)")

        # Sender from generic/free email (common for these blasts)
        if sender_email:
            sender_domain = sender_email.split("@")[-1].lower() if "@" in sender_email else ""
            if sender_domain in GENERIC_SENDER_DOMAINS:
                score += 1
                flags.append("generic-sender-domain")

        # Only flag if score meets threshold
        # mass-blast alone (score 3) or amazon keywords alone (score 2) should qualify
        if score >= 2 and len(recipients) >= max(min_recipients, 2):
            results.append({
                "file": os.path.relpath(fpath, VAULT) if fpath.startswith(VAULT) else fpath,
                "sender": sender,
                "sender_email": sender_email,
                "subject": subject,
                "date": email_date,
                "recipient_count": len(recipients),
                "recipients": recipients,
                "score": score,
                "flags": flags,
            })

    return results


# ── MBOX File Scanning ───────────────────────────────────────────────────────

def scan_mbox_file(mbox_path, min_recipients):
    """
    Scan a raw .mbox file for mass-outreach spam.
    Returns list of dicts with spam email details.
    """
    results = []

    if not os.path.isfile(mbox_path):
        print(f"  [ERROR] MBOX file not found: {mbox_path}")
        return results

    print(f"  Opening MBOX: {mbox_path}")
    mbox = mailbox.mbox(mbox_path)
    total = len(mbox)
    print(f"  Found {total} messages")

    for i, msg in enumerate(mbox):
        if (i + 1) % 1000 == 0:
            print(f"  Processed {i + 1}/{total}...")

        try:
            to_str = msg.get("To", "") or ""
            cc_str = msg.get("Cc", "") or ""
            bcc_str = msg.get("Bcc", "") or ""
            from_str = msg.get("From", "") or ""
            subject = msg.get("Subject", "") or ""
            date_str = msg.get("Date", "") or ""

            recipients = extract_all_recipients(to_str, cc_str, bcc_str)

            # Get body text
            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    ctype = part.get_content_type()
                    if ctype == "text/plain":
                        payload = part.get_payload(decode=True)
                        if payload:
                            body += payload.decode("utf-8", errors="replace")
                    elif ctype == "text/html" and not body:
                        payload = part.get_payload(decode=True)
                        if payload:
                            html = payload.decode("utf-8", errors="replace")
                            body += re.sub(r'<[^>]+>', ' ', html)
            else:
                payload = msg.get_payload(decode=True)
                if payload:
                    body = payload.decode("utf-8", errors="replace")

            full_text = f"{subject}\n{body}"

            # Scoring
            score = 0
            flags = []

            if len(recipients) >= min_recipients:
                score += 3
                flags.append(f"mass-blast ({len(recipients)} recipients)")

            amazon_matches = AMAZON_SPAM_RE.findall(full_text)
            if amazon_matches:
                score += 2
                flags.append(f"amazon-spam ({len(amazon_matches)} keyword hits)")

            amazon_links = re.findall(
                r'https?://(?:www\.)?amazon\.com[^\s)"\]]*',
                full_text, re.IGNORECASE
            )
            amzn_links = re.findall(
                r'https?://amzn\.(to|com)/[^\s)"\]]*',
                full_text, re.IGNORECASE
            )
            if amazon_links or amzn_links:
                score += 2
                flags.append(f"amazon-links ({len(amazon_links) + len(amzn_links)})")

            outreach_matches = MASS_OUTREACH_RE.findall(full_text)
            if outreach_matches:
                score += 1
                flags.append(f"outreach-patterns ({len(outreach_matches)} hits)")

            # Parse sender
            sender_name = from_str
            sender_email_addr = ""
            m = re.search(r'<([^>]+)>', from_str)
            if m:
                sender_email_addr = m.group(1)
                sender_name = from_str[:m.start()].strip().strip('"')
            elif "@" in from_str:
                sender_email_addr = from_str.strip()

            if sender_email_addr:
                sender_domain = sender_email_addr.split("@")[-1].lower()
                if sender_domain in GENERIC_SENDER_DOMAINS:
                    score += 1
                    flags.append("generic-sender-domain")

            if score >= 2 and len(recipients) >= max(min_recipients, 2):
                results.append({
                    "file": f"mbox-message-{i + 1}",
                    "sender": sender_name,
                    "sender_email": sender_email_addr,
                    "subject": subject,
                    "date": date_str,
                    "recipient_count": len(recipients),
                    "recipients": recipients,
                    "score": score,
                    "flags": flags,
                })

        except Exception as e:
            continue

    return results


# ── Output / Reporting ───────────────────────────────────────────────────────

def print_report(results):
    """Print a summary report of detected spam and harvested emails."""
    if not results:
        print("\n  No mass-outreach spam detected.")
        return

    # Aggregate all unique recipient emails
    all_recipients = set()
    for r in results:
        all_recipients.update(r["recipients"])

    print()
    print("=" * 80)
    print("  SPAM FILTER REPORT")
    print("=" * 80)
    print(f"  Spam emails detected:       {len(results)}")
    print(f"  Unique creator emails found: {len(all_recipients)}")
    print()

    # Top spam senders
    sender_counts = Counter()
    for r in results:
        key = r["sender_email"] or r["sender"]
        sender_counts[key] += 1

    if sender_counts:
        print("  Top spam senders:")
        for sender, count in sender_counts.most_common(20):
            print(f"    {sender}: {count} emails")
        print()

    # Show each spam email
    print("-" * 80)
    print("  FLAGGED EMAILS")
    print("-" * 80)
    for i, r in enumerate(results, 1):
        print(f"\n  [{i}] {r['subject'][:80]}")
        print(f"      From: {r['sender']} <{r['sender_email']}>")
        print(f"      Date: {r['date']}")
        print(f"      Recipients: {r['recipient_count']}")
        print(f"      Flags: {', '.join(r['flags'])}")
        print(f"      Score: {r['score']}")
        if r["recipients"][:5]:
            print(f"      Sample recipients: {', '.join(r['recipients'][:5])}")
            if len(r["recipients"]) > 5:
                print(f"        ... and {len(r['recipients']) - 5} more")

    # Instagram search queries
    print()
    print("=" * 80)
    print("  INSTAGRAM PROFILE SEARCH QUERIES")
    print("=" * 80)
    print(f"  Total unique emails to search: {len(all_recipients)}")
    print()
    print("  Copy these into Google to find Instagram profiles:")
    print()

    for addr in sorted(all_recipients):
        query = make_instagram_search_query(addr)
        print(f"    {query}")

    print()
    print(f"  Total: {len(all_recipients)} search queries generated")
    print()


def export_csv(results, output_path):
    """Export results to CSV with one row per recipient email."""
    all_rows = []
    seen_emails = set()

    for r in results:
        for recipient in r["recipients"]:
            if recipient in seen_emails:
                continue
            seen_emails.add(recipient)

            all_rows.append({
                "recipient_email": recipient,
                "instagram_search_query": make_instagram_search_query(recipient),
                "instagram_search_url": make_instagram_search_url(recipient),
                "found_in_subject": r["subject"],
                "spam_sender": r["sender_email"],
                "spam_sender_name": r["sender"],
                "spam_date": r["date"],
                "spam_score": r["score"],
                "spam_flags": "; ".join(r["flags"]),
                "total_recipients_in_email": r["recipient_count"],
            })

    # Sort by email
    all_rows.sort(key=lambda x: x["recipient_email"])

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "recipient_email",
            "instagram_search_query",
            "instagram_search_url",
            "found_in_subject",
            "spam_sender",
            "spam_sender_name",
            "spam_date",
            "spam_score",
            "spam_flags",
            "total_recipients_in_email",
        ])
        writer.writeheader()
        writer.writerows(all_rows)

    print(f"  Exported {len(all_rows)} unique emails to: {output_path}")


def export_json(results, output_path):
    """Export results to JSON."""
    all_recipients = set()
    for r in results:
        all_recipients.update(r["recipients"])

    output = {
        "generated": datetime.now().isoformat(),
        "spam_emails_detected": len(results),
        "unique_creator_emails": len(all_recipients),
        "instagram_searches": [
            {
                "email": addr,
                "search_query": make_instagram_search_query(addr),
                "search_url": make_instagram_search_url(addr),
            }
            for addr in sorted(all_recipients)
        ],
        "flagged_emails": [
            {
                "file": r["file"],
                "sender": r["sender"],
                "sender_email": r["sender_email"],
                "subject": r["subject"],
                "date": r["date"],
                "recipient_count": r["recipient_count"],
                "recipients": r["recipients"],
                "score": r["score"],
                "flags": r["flags"],
            }
            for r in results
        ],
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"  Exported to: {output_path}")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Detect mass-outreach spam and harvest creator emails for Instagram lookup"
    )
    parser.add_argument("--scan-mbox", type=str, default=None,
                        help="Scan a raw .mbox file instead of vault notes")
    parser.add_argument("--email-dir", type=str, default=None,
                        help="Override email archive directory")
    parser.add_argument("--min-recipients", type=int, default=DEFAULT_MIN_RECIPIENTS,
                        help=f"Minimum recipients to flag as mass-blast (default: {DEFAULT_MIN_RECIPIENTS})")
    parser.add_argument("--output", type=str, default=None,
                        help="Export results to CSV file")
    parser.add_argument("--output-json", type=str, default=None,
                        help="Export results to JSON file")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview detection without full output")
    parser.add_argument("--limit", type=int, default=0,
                        help="Limit number of results shown")
    args = parser.parse_args()

    print()
    print("=" * 80)
    print("  Email Spam Filter & Creator Email Harvester")
    print("=" * 80)
    print(f"  Min recipients threshold: {args.min_recipients}")

    # Scan source
    if args.scan_mbox:
        print(f"  Source: MBOX file ({args.scan_mbox})")
        print()
        results = scan_mbox_file(args.scan_mbox, args.min_recipients)
    else:
        scan_dir = args.email_dir or EMAIL_DIR
        print(f"  Source: Vault email archive ({scan_dir})")
        print()
        results = scan_vault_emails(scan_dir, args.min_recipients)

    # Sort by score (highest first), then by recipient count
    results.sort(key=lambda r: (-r["score"], -r["recipient_count"]))

    if args.limit > 0:
        results = results[:args.limit]

    # Report
    print_report(results)

    # Export
    if args.output:
        export_csv(results, args.output)

    if args.output_json:
        export_json(results, args.output_json)

    # Summary
    all_recipients = set()
    for r in results:
        all_recipients.update(r["recipients"])

    print("-" * 80)
    print(f"  SUMMARY: {len(results)} spam emails → {len(all_recipients)} unique creator emails")
    if all_recipients:
        print(f"  Run Instagram searches to find {len(all_recipients)} potential creator profiles")
    print("-" * 80)
    print()


if __name__ == "__main__":
    main()
