"""
Gmail API Sync -> Obsidian Vault
Direct Gmail API using OAuth credentials from Doppler.
Supports multiple accounts with separate refresh tokens.

First run (per account):
  python gmail_api_sync.py --auth          # opens browser, saves refresh token to Doppler

Daily sync:
  python gmail_api_sync.py                 # syncs last 24h for default account
  python gmail_api_sync.py --days 7        # last 7 days
  python gmail_api_sync.py --account nickient  # sync nickient account
  python gmail_api_sync.py --all           # sync both accounts
  python gmail_api_sync.py --dry-run       # preview without writing

Scheduled (Task Scheduler):
  python gmail_api_sync.py --all --days 1
"""

import json
import os
import re
import sys
import argparse
import base64
import subprocess
import traceback
from datetime import datetime, timedelta
from html import unescape
from pathlib import Path

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

# ── Config ──────────────────────────────────────────────────────────────────

_HOME = Path.home()
VAULT_BASE = _HOME / "Documents" / "ENT-Agency-Vault"
VAULT_EMAIL_DIR = VAULT_BASE / "09-Email-Archive"
VAULT_GMAIL_DIR = VAULT_EMAIL_DIR / "Gmail-Captures"
VAULT_ATTACHMENTS = VAULT_EMAIL_DIR / "attachments"

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

SKIP_LABELS = {"TRASH", "SPAM", "CATEGORY_PROMOTIONS", "CATEGORY_SOCIAL", "CATEGORY_FORUMS"}
MAX_BODY_LEN = 15000
MAX_RESULTS_PER_PAGE = 100

EXTRACT_EXTENSIONS = {".pdf", ".csv", ".xlsx", ".xls", ".docx", ".doc", ".txt"}

ACCOUNTS = {
    "entagency": {
        "email": "marketingteam@entagency.co",
        "token_key": "GMAIL_REFRESH_TOKEN_ENTAGENCY",
    },
    "nickient": {
        "email": "marketingteam@nickient.com",
        "token_key": "GMAIL_REFRESH_TOKEN_NICKIENT",
    },
}

DOPPLER_PROJECT = "ent-agency-analytics"
DOPPLER_CONFIG = "dev"
DOPPLER_ALERT_PROJECT = "ent-agency-automation"

# ── Doppler Helpers ─────────────────────────────────────────────────────────

def doppler_get(key, project=DOPPLER_PROJECT, config=DOPPLER_CONFIG):
    """Get a secret from Doppler."""
    result = subprocess.run(
        ["doppler", "secrets", "get", key, "--project", project,
         "--config", config, "--plain"],
        capture_output=True, text=True, timeout=15
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def doppler_set(key, value, project=DOPPLER_PROJECT, config=DOPPLER_CONFIG):
    """Set a secret in Doppler."""
    result = subprocess.run(
        ["doppler", "secrets", "set", key, value, "--project", project,
         "--config", config],
        capture_output=True, text=True, timeout=15
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to set Doppler secret {key}: {result.stderr}")


# ── Gmail Auth ──────────────────────────────────────────────────────────────

def get_oauth_credentials():
    """Get the OAuth client credentials JSON from Doppler."""
    creds_json = doppler_get("GOOGLE_OAUTH_CREDENTIALS_JSON")
    if not creds_json:
        print("ERROR: GOOGLE_OAUTH_CREDENTIALS_JSON not found in Doppler")
        print(f"  Project: {DOPPLER_PROJECT}, Config: {DOPPLER_CONFIG}")
        sys.exit(1)
    return json.loads(creds_json)


def get_gmail_service(account_key):
    """Build an authenticated Gmail API service for the given account."""
    account = ACCOUNTS[account_key]
    token_key = account["token_key"]

    # Try to load existing refresh token from Doppler
    refresh_token = doppler_get(token_key)

    creds = None
    if refresh_token:
        client_creds = get_oauth_credentials()
        installed = client_creds.get("installed", client_creds)
        creds = Credentials(
            token=None,
            refresh_token=refresh_token,
            client_id=installed["client_id"],
            client_secret=installed["client_secret"],
            token_uri=installed["token_uri"],
            scopes=SCOPES,
        )
        # Refresh the access token
        try:
            creds.refresh(Request())
        except Exception as e:
            print(f"WARNING: Refresh token expired for {account['email']}: {e}")
            print("  Run: python gmail_api_sync.py --auth")
            creds = None

    if not creds or not creds.valid:
        return None

    return build("gmail", "v1", credentials=creds)


def do_auth(account_key):
    """Run the interactive OAuth flow for an account."""
    account = ACCOUNTS[account_key]
    print(f"\nAuthenticating for: {account['email']}")
    print("A browser window will open. Sign in with the account above.\n")

    client_creds = get_oauth_credentials()

    # Write temp credentials file (InstalledAppFlow needs a file)
    tmp_creds = Path.home() / ".claude" / "tmp_gmail_creds.json"
    tmp_creds.parent.mkdir(parents=True, exist_ok=True)
    tmp_creds.write_text(json.dumps(client_creds))

    try:
        flow = InstalledAppFlow.from_client_secrets_file(
            str(tmp_creds), scopes=SCOPES
        )
        creds = flow.run_local_server(port=0)
    finally:
        tmp_creds.unlink(missing_ok=True)

    # Save refresh token to Doppler
    if creds.refresh_token:
        doppler_set(account["token_key"], creds.refresh_token)
        print(f"\nRefresh token saved to Doppler as {account['token_key']}")

        # Verify the email matches
        service = build("gmail", "v1", credentials=creds)
        profile = service.users().getProfile(userId="me").execute()
        actual_email = profile.get("emailAddress", "unknown")
        print(f"Authenticated as: {actual_email}")

        if actual_email.lower() != account["email"].lower():
            print(f"\nWARNING: Expected {account['email']} but got {actual_email}")
            print("The token was saved anyway — double-check which account to use.")
    else:
        print("ERROR: No refresh token received. Try again.")
        sys.exit(1)


# ── Email Parsing ──────────────────────────────────────────────────────────

def get_header(msg, name):
    """Extract a header value from a Gmail message."""
    headers = msg.get("payload", {}).get("headers", [])
    for h in headers:
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


def get_labels(msg):
    return set(msg.get("labelIds", []))


def parse_from(from_str):
    match = re.match(r'(.*?)\s*<(.+?)>', from_str)
    if match:
        name = match.group(1).strip().strip('"')
        email_addr = match.group(2)
        return name, email_addr
    return from_str, from_str


def parse_date(date_str):
    if not date_str:
        return None
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
    cleaned = re.sub(r'\s*\([^)]*\)\s*$', '', date_str)
    cleaned = re.sub(r'\s*[+-]\d{4}\s*$', '', cleaned)
    for fmt in ["%a, %d %b %Y %H:%M:%S", "%d %b %Y %H:%M:%S"]:
        try:
            return datetime.strptime(cleaned.strip(), fmt)
        except ValueError:
            continue
    return None


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


def get_body(payload):
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


def extract_attachments(service, msg, date_prefix):
    """Extract attachment metadata and optionally download them."""
    payload = msg.get("payload", {})
    all_names = []
    saved = []

    def walk_parts(part):
        fn = part.get("filename", "")
        attach_id = part.get("body", {}).get("attachmentId")
        if fn and attach_id:
            all_names.append(fn)
            _, ext = os.path.splitext(fn)
            if ext.lower() in EXTRACT_EXTENSIONS:
                try:
                    att = service.users().messages().attachments().get(
                        userId="me", messageId=msg["id"], id=attach_id
                    ).execute()
                    data = base64.urlsafe_b64decode(att["data"])
                    safe_fn = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', fn)
                    out_name = f"{date_prefix}_{safe_fn}"
                    out_path = VAULT_ATTACHMENTS / out_name
                    if not out_path.exists():
                        out_path.write_bytes(data)
                        saved.append(out_name)
                except Exception:
                    pass
        for sub in part.get("parts", []):
            walk_parts(sub)

    walk_parts(payload)
    return all_names, saved


# ── Domain → Brand Mapping (from enrich_email_links.py) ───────────────────

DOMAIN_BRAND_MAP = {
    # Anchor brands
    "drinklmnt.com": "DrinkLMNT", "lmnt.com": "DrinkLMNT",
    "456growth.com": "456Growth",
    "gruns.co": "Gruns", "eatgruns.com": "Gruns",
    "equipfoods.com": "Equip",
    "cubert.co": "Hume Health", "myhumehealth.com": "Hume Health", "tryhumehealth.com": "Hume Health",
    # Active roster
    "meritbeauty.com": "Merit Beauty", "dimebeautyco.com": "DIME Beauty",
    "beamtlc.com": "BEAM TLC", "nutrafol.com": "Nutrafol",
    "armra.com": "ARMRA", "tryarmra.com": "ARMRA",
    "oseamalibu.com": "OSEA Malibu", "arrae.com": "Arrae",
    "clearstem.com": "CLEARSTEM", "vicicollection.com": "VICI Collection",
    "tula.com": "TULA", "tulaforlife.com": "TULA",
    "dermalea.com": "Dermalea", "oeak.com": "OEAK",
    "rothschildbeauty.com": "Colleen Rothschild",
    "pinkstork.com": "Pink Stork", "wallicases.com": "Walli Cases",
    "brandmail.co": "Walmart Fashion", "joinmavely.com": "Walmart Fashion",
    "eckodigitalmedia.com": "Ecko Digital Media",
    "influential.co": "Influential", "butcherbox.com": "Butcherbox",
    # One-off paid brands
    "lumineux.com": "Lumineux", "kfruns.com": "Kion",
    "seedhealth.com": "Seed", "orgain.com": "Orgain",
    "ag1.com": "AG1", "athleticgreens.com": "AG1",
    "avaline.com": "Avaline", "jshealthvitamins.com": "JS Health",
    "firstaidbeauty.com": "First Aid Beauty", "wildgrain.com": "Wildgrain",
    "oakandluna.com": "Oak and Luna", "cocofloss.com": "Cocofloss",
    "yvesrocherusa.com": "Yves Rocher", "bioma.com": "Bioma",
    # Historical paid
    "influencerresponse.com": "Beekeepers Naturals",
    "fromourplace.com": "Our Place", "thrivemarket.com": "Thrive Market",
    "madebymary.com": "Made by Mary", "nuuds.com": "Nuuds",
    "justingredients.us": "Just Ingredients", "branchbasics.com": "Branch Basics",
    "diviofficial.com": "Divi", "koparibeauty.com": "Kopari Beauty",
    "badbirdiegolf.com": "Bad Birdie", "primalkitchen.com": "Primal Kitchen",
    "aloha.com": "Aloha", "spanx.com": "Spanx", "bloomnu.com": "Bloom",
    "brumate.com": "BruMate", "navyhaircare.com": "Navy Hair Care",
    "yourparade.com": "Parade", "tarte.com": "Tarte",
    "fabletics.com": "Fabletics", "rarebeauty.com": "Rare Beauty",
    "primallypure.com": "Primally Pure", "peachandlily.com": "Peach & Lily",
    "livingproof.com": "Living Proof", "alaninu.com": "Alani Nu",
    # Platforms
    "hellofresh.com": "HelloFresh", "hellofresh.de": "HelloFresh",
    "skinhaven.co": "SkinHaven", "skinhaven.com": "SkinHaven",
    "trend-mgmt.com": "Trend Management", "lumanu.com": "Lumanu",
    # Product dev
    "pharmachem.com": "Pharmachem", "formulife.com": "Formulife",
}


def guess_brand(from_email, subject):
    """Guess related brand from sender domain or subject line."""
    if from_email:
        domain = from_email.split("@")[-1].lower()
        if domain in DOMAIN_BRAND_MAP:
            return DOMAIN_BRAND_MAP[domain]
    # Check subject for brand mentions
    subj_lower = (subject or "").lower()
    for domain, brand in DOMAIN_BRAND_MAP.items():
        if brand.lower() in subj_lower:
            return brand
    return ""


# ── File Writing ───────────────────────────────────────────────────────────

def sanitize_filename(name, max_len=80):
    # Strip non-ASCII (emoji, special chars) that break Windows filenames
    name = name.encode("ascii", errors="ignore").decode("ascii")
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    if len(name) > max_len:
        name = name[:max_len].rstrip()
    return name or "untitled"


def write_email_note(service, msg, account_email, output_dir, seen_filenames, dry_run=False):
    """Convert a Gmail API message to a vault markdown note."""
    subject = get_header(msg, "Subject") or "(no subject)"
    from_str = get_header(msg, "From")
    to_str = get_header(msg, "To")
    date_str = get_header(msg, "Date")
    labels = get_labels(msg)

    if labels & SKIP_LABELS:
        return "skipped_label"

    dt = parse_date(date_str)
    if not dt:
        internal = msg.get("internalDate")
        if internal:
            dt = datetime.fromtimestamp(int(internal) / 1000)
        else:
            return "skipped_nodate"

    from_name, from_email = parse_from(from_str)
    brand = guess_brand(from_email, subject)

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

    body = get_body(msg.get("payload", {}))
    all_attach_names, saved_attachments = extract_attachments(service, msg, date_prefix)

    display_labels = sorted(labels - {"UNREAD"})
    brand_line = f'"{brand}"' if brand else ""

    note = f"""---
type: email
sender: "{from_name}"
sender_email: "{from_email}"
recipient: "{to_str[:200]}"
subject: "{subject.replace('"', "'")}"
email_date: {dt.strftime("%Y-%m-%dT%H:%M:%S")}
account: "{account_email}"
labels: [{', '.join(f'"{l}"' for l in display_labels)}]
related_brand: {brand_line}
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
**Account:** {account_email}
**Labels:** {', '.join(display_labels) if display_labels else 'none'}
"""
    if brand:
        note += f"**Brand:** [[{brand}]]\n"
    if all_attach_names:
        note += f"**Attachments:** {', '.join(all_attach_names)}\n"
        if saved_attachments:
            note += "**Saved:** " + ", ".join(f"[[{a}]]" for a in saved_attachments) + "\n"

    note += f"\n---\n\n{body}\n"

    filepath = output_dir / f"{final_name}.md"
    filepath.write_text(note, encoding="utf-8", errors="replace")

    return "created"


# ── Slack Alerts ───────────────────────────────────────────────────────────

def send_slack_alert(message):
    """Send an alert to Slack on sync failure."""
    try:
        token = doppler_get("ENT_BOT_SLACK_BOT_TOKEN",
                           project=DOPPLER_ALERT_PROJECT, config="dev")
        if not token:
            print("WARNING: No Slack bot token in Doppler, skipping alert")
            return

        import urllib.request
        data = json.dumps({
            "channel": "#automation-alerts",
            "text": f":warning: Gmail Sync Alert\n{message}",
        }).encode()
        req = urllib.request.Request(
            "https://slack.com/api/chat.postMessage",
            data=data,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f"WARNING: Slack alert failed: {e}")


# ── Main Sync ──────────────────────────────────────────────────────────────

def sync_account(account_key, query, dry_run=False, limit=None):
    """Sync emails for one account."""
    account = ACCOUNTS[account_key]
    email = account["email"]

    print(f"\n{'='*60}")
    print(f"Syncing: {email}")
    print(f"Query:   {query}")
    print(f"Output:  {VAULT_GMAIL_DIR}")
    print(f"Dry run: {dry_run}")

    service = get_gmail_service(account_key)
    if not service:
        msg = f"Not authenticated for {email}. Run: python gmail_api_sync.py --auth --account {account_key}"
        print(f"ERROR: {msg}")
        return {"error": msg}

    # Ensure output dirs
    if not dry_run:
        VAULT_GMAIL_DIR.mkdir(parents=True, exist_ok=True)
        VAULT_ATTACHMENTS.mkdir(parents=True, exist_ok=True)

    # Pre-load existing filenames from Gmail-Captures
    existing = set()
    if VAULT_GMAIL_DIR.exists():
        for f in VAULT_GMAIL_DIR.iterdir():
            if f.suffix == ".md":
                existing.add(f.stem)
    print(f"Found {len(existing)} existing notes in Gmail-Captures/")

    # Get message IDs
    print("Searching for messages...")
    all_ids = []
    page_token = None
    pages = 0

    while pages < 50:
        results = service.users().messages().list(
            userId="me", q=query, maxResults=MAX_RESULTS_PER_PAGE,
            pageToken=page_token
        ).execute()
        messages = results.get("messages", [])
        all_ids.extend(m["id"] for m in messages)
        page_token = results.get("nextPageToken")
        pages += 1
        if not page_token:
            break
        if len(all_ids) % 500 == 0:
            print(f"  Found {len(all_ids)} messages so far...")

    if limit:
        all_ids = all_ids[:limit]

    print(f"Found {len(all_ids)} messages to process")

    if not all_ids:
        print("Nothing to sync.")
        return {"created": 0, "total": 0}

    stats = {"created": 0, "would_create": 0, "skipped_label": 0,
             "skipped_nodate": 0, "errors": 0, "skipped_exists": 0}
    seen_filenames = set(existing)

    for i, msg_id in enumerate(all_ids, 1):
        try:
            msg = service.users().messages().get(
                userId="me", id=msg_id, format="full"
            ).execute()

            # Quick dedupe check
            subject = get_header(msg, "Subject") or "(no subject)"
            date_str = get_header(msg, "Date")
            dt = parse_date(date_str)
            if dt:
                check_name = f"{dt.strftime('%Y-%m-%d')}_{sanitize_filename(subject, max_len=60)}"
                if check_name in existing:
                    stats["skipped_exists"] += 1
                    continue

            result = write_email_note(service, msg, email, VAULT_GMAIL_DIR, seen_filenames, dry_run)
            stats[result] = stats.get(result, 0) + 1

            if dry_run and result == "would_create":
                safe_preview = sanitize_filename(subject, max_len=40)
                print(f"  Would create: {dt.strftime('%Y-%m-%d') if dt else '????'}_{safe_preview}.md")

        except Exception as e:
            stats["errors"] += 1
            if stats["errors"] <= 5:
                print(f"  Error on message {i}: {e}")

        if i % 50 == 0:
            created = stats.get("created", 0) + stats.get("would_create", 0)
            print(f"  Processed {i}/{len(all_ids)}... ({created} new)")

    print(f"\nDone with {email}:")
    if dry_run:
        print(f"  Would create:    {stats['would_create']}")
    else:
        print(f"  Created:         {stats['created']}")
    print(f"  Already existed: {stats['skipped_exists']}")
    print(f"  Skipped (label): {stats['skipped_label']}")
    print(f"  Skipped (date):  {stats['skipped_nodate']}")
    print(f"  Errors:          {stats['errors']}")

    return stats


def main():
    parser = argparse.ArgumentParser(description="Gmail API Sync -> Obsidian Vault")
    parser.add_argument("--auth", action="store_true",
                        help="Run OAuth flow (opens browser)")
    parser.add_argument("--account", default="entagency",
                        choices=list(ACCOUNTS.keys()),
                        help="Account to sync (default: entagency)")
    parser.add_argument("--all", action="store_true",
                        help="Sync all accounts")
    parser.add_argument("--days", type=int, default=1,
                        help="Sync emails from last N days (default: 1)")
    parser.add_argument("--after", type=str, default=None,
                        help="Sync emails after date (YYYY-MM-DD)")
    parser.add_argument("--query", type=str, default=None,
                        help="Custom Gmail search query")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview without writing files")
    parser.add_argument("--limit", type=int, default=None,
                        help="Max emails to process per account")
    args = parser.parse_args()

    print("Gmail API Sync -> Obsidian Vault")
    print("================================")

    # Auth mode
    if args.auth:
        do_auth(args.account)
        return

    # Build query
    if args.query:
        query = args.query
    elif args.after:
        query = f"after:{args.after}"
    else:
        after_date = (datetime.now() - timedelta(days=args.days)).strftime("%Y/%m/%d")
        query = f"after:{after_date}"

    # Determine accounts to sync
    accounts_to_sync = list(ACCOUNTS.keys()) if args.all else [args.account]

    all_stats = {}
    errors = []

    for acct in accounts_to_sync:
        try:
            stats = sync_account(acct, query, args.dry_run, args.limit)
            all_stats[acct] = stats
            if "error" in stats:
                errors.append(f"{ACCOUNTS[acct]['email']}: {stats['error']}")
            elif stats.get("errors", 0) > 0:
                errors.append(f"{ACCOUNTS[acct]['email']}: {stats['errors']} email processing errors")
        except Exception as e:
            error_msg = f"{ACCOUNTS[acct]['email']}: {e}"
            errors.append(error_msg)
            print(f"\nERROR syncing {acct}: {e}")
            traceback.print_exc()

    # Summary
    if len(accounts_to_sync) > 1:
        print(f"\n{'='*60}")
        print("SUMMARY")
        for acct, stats in all_stats.items():
            email = ACCOUNTS[acct]["email"]
            created = stats.get("created", 0) + stats.get("would_create", 0)
            print(f"  {email}: {created} new, {stats.get('skipped_exists', 0)} skipped, {stats.get('errors', 0)} errors")

    # Alert on errors (only for non-dry-run scheduled runs)
    if errors and not args.dry_run:
        alert_msg = "Gmail sync errors:\n" + "\n".join(f"  - {e}" for e in errors)
        send_slack_alert(alert_msg)


if __name__ == "__main__":
    main()
