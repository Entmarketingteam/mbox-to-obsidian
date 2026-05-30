"""
Gmail -> Slack Notifier (label-driven)

Queries Gmail for messages tagged with TRIAGE_NICKI_OFFERS, posts each to
#inbound-pitches in Slack. Skips messages sent by us (Emily's replies).

This is the trusted feed: only labeled emails post. Apply the Gmail label
on your phone or desktop and the worker takes care of the rest.

Usage:
  python gmail_to_slack.py                   # post labeled emails from last 14 days
  python gmail_to_slack.py --days 30         # widen the window
  python gmail_to_slack.py --dry-run         # classify and print, do not post
  python gmail_to_slack.py --limit 5         # cap output
  python gmail_to_slack.py --reset-state     # forget what's been posted (re-posts everything)
"""

# Windows UTF-8 fix -- must come before any other prints
import sys
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import argparse
import json
import re
import subprocess
from datetime import datetime
from pathlib import Path
from urllib import request as urlreq, error as urlerr
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).parent))
from gmail_api_sync import get_gmail_service, ACCOUNTS  # noqa: E402

# Config
_HOME = Path.home()
STATE_FILE = _HOME / ".claude" / "gmail_to_slack_state.json"
LOG_FILE = _HOME / ".claude" / "gmail_to_slack.log"

GMAIL_TRIAGE_LABEL = "TRIAGE_NICKI_OFFERS"
SLACK_CHANNEL_NAME = "inbound-pitches"
DOPPLER_SLACK_PROJECT = "ent-agency-automation"
DOPPLER_SLACK_CONFIG = "dev"
SLACK_BOT_TOKEN_KEY = "ENT_BOT_SLACK_BOT_TOKEN"

# Skip messages sent by these addresses (our own outbound replies)
OWN_ADDRESSES = {
    "marketingteam@nickient.com",
    "marketingteam@entagency.co",
}


# Doppler
def doppler_get(key, project, config):
    result = subprocess.run(
        ["doppler", "secrets", "get", key,
         "--project", project, "--config", config,
         "--plain", "--no-check-version"],
        capture_output=True, text=True, timeout=15,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Doppler get {key} failed: {result.stderr.strip()}")
    return result.stdout.strip()


# State (dedupe across runs by Gmail message_id)
def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"posted_message_ids": [], "last_run": None}


def save_state(state, max_history=10000):
    state["posted_message_ids"] = state["posted_message_ids"][-max_history:]
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def log(msg):
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(f"{datetime.now().isoformat(timespec='seconds')} {msg}\n")


# Gmail fetch
def parse_from_header(from_str):
    """Parse 'Name <email>' or just 'email'."""
    m = re.match(r'(.*?)\s*<(.+?)>', from_str or "")
    if m:
        return m.group(1).strip().strip('"'), m.group(2).strip()
    return (from_str or "").strip(), (from_str or "").strip()


def fetch_labeled_messages(label_name, days, account_key):
    """Yield dicts of metadata for each labeled message in the account."""
    service = get_gmail_service(account_key)
    if not service:
        return  # auth failure already printed by get_gmail_service
    account_email = ACCOUNTS[account_key]["email"]

    query = f"label:{label_name} newer_than:{days}d"
    page_token = None
    while True:
        kwargs = {"userId": "me", "q": query, "maxResults": 100}
        if page_token:
            kwargs["pageToken"] = page_token
        resp = service.users().messages().list(**kwargs).execute()
        for ref in resp.get("messages", []):
            m = service.users().messages().get(
                userId="me", id=ref["id"], format="metadata",
                metadataHeaders=["From", "Subject", "Date", "To"],
            ).execute()
            headers = {h["name"]: h["value"] for h in m.get("payload", {}).get("headers", [])}
            sender_name, sender_email = parse_from_header(headers.get("From", ""))
            yield {
                "message_id": ref["id"],
                "thread_id": m.get("threadId", ""),
                "snippet": (m.get("snippet") or "").strip(),
                "sender": sender_name,
                "sender_email": sender_email,
                "subject": headers.get("Subject", ""),
                "date": headers.get("Date", ""),
                "labels": m.get("labelIds", []),
                "account": account_email,
                "gmail_url": f"https://mail.google.com/mail/u/0/#inbox/{ref['id']}",
            }
        page_token = resp.get("nextPageToken")
        if not page_token:
            break


# Slack
SLACK_API = "https://slack.com/api"

def slack_post(method, token, payload):
    req = urlreq.Request(
        f"{SLACK_API}/{method}",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        },
    )
    try:
        with urlreq.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urlerr.HTTPError as e:
        return {"ok": False, "error": f"http_{e.code}", "raw": e.read().decode(errors="replace")}


def truncate(s, n):
    s = s or ""
    return s if len(s) <= n else s[: n - 1] + "…"


def build_blocks(msg):
    subject = truncate(msg["subject"] or "(no subject)", 140)
    sender = msg["sender"] or "unknown"
    sender_email = msg["sender_email"] or ""

    fields = [
        {"type": "mrkdwn", "text": f"*From*\n{truncate(sender, 80)}\n`{sender_email}`"},
        {"type": "mrkdwn", "text": f"*Inbox*\n{msg['account']}"},
    ]

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": f":bell: {subject}", "emoji": True}},
        {"type": "section", "fields": fields},
    ]

    if msg.get("snippet"):
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"_{truncate(msg['snippet'], 300)}_"},
        })

    blocks.append({
        "type": "context",
        "elements": [
            {"type": "mrkdwn",
             "text": f":calendar: {msg['date']}  •  <{msg['gmail_url']}|Open in Gmail>"},
        ],
    })
    return blocks


def post_to_slack(token, channel, msg):
    return slack_post("chat.postMessage", token, {
        "channel": channel,
        "text": f"Labeled offer: {msg['subject']} -- {msg['sender']}",
        "blocks": build_blocks(msg),
        "unfurl_links": False,
        "unfurl_media": False,
    })


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=14,
                        help="Look at labeled messages from the last N days (default 14)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would be posted; don't post; don't save state")
    parser.add_argument("--limit", type=int, default=0,
                        help="Stop after posting this many messages (0 = unlimited)")
    parser.add_argument("--reset-state", action="store_true",
                        help="Wipe the posted-messages list so the next run reposts everything")
    parser.add_argument("--label", default=GMAIL_TRIAGE_LABEL,
                        help=f"Gmail label to filter on (default {GMAIL_TRIAGE_LABEL})")
    parser.add_argument("--channel", default=SLACK_CHANNEL_NAME,
                        help=f"Slack channel name (default {SLACK_CHANNEL_NAME})")
    args = parser.parse_args()

    if args.reset_state:
        if STATE_FILE.exists():
            STATE_FILE.unlink()
        print(f"State reset: {STATE_FILE} removed")

    print(f"Gmail -> Slack (label-driven)")
    print(f"  Label:    {args.label}")
    print(f"  Channel:  #{args.channel}")
    print(f"  Window:   last {args.days} days")

    state = load_state()
    already_posted = set(state.get("posted_message_ids", []))

    # Collect candidates from both accounts
    candidates = []
    for account_key in ACCOUNTS:
        try:
            for msg in fetch_labeled_messages(args.label, args.days, account_key):
                candidates.append(msg)
        except Exception as e:
            print(f"  ERR fetching {account_key}: {e}")
            log(f"ERR fetch {account_key}: {e}")

    print(f"  Candidates: {len(candidates)} labeled messages")

    # Sort by date (Gmail returns newest first; we want oldest first so threads land chronologically)
    candidates.sort(key=lambda m: m["message_id"])

    token = None
    if not args.dry_run:
        token = doppler_get(SLACK_BOT_TOKEN_KEY, DOPPLER_SLACK_PROJECT, DOPPLER_SLACK_CONFIG)
    channel_ref = f"#{args.channel}"

    posted = skipped_dup = skipped_self = errors = 0

    for msg in candidates:
        if msg["message_id"] in already_posted:
            skipped_dup += 1
            continue
        if msg["sender_email"].lower() in OWN_ADDRESSES:
            skipped_self += 1
            continue

        subj_short = truncate(msg["subject"] or "", 70)
        sender_short = truncate(msg["sender"] or "", 30)

        if args.dry_run:
            print(f"  WOULD POST  {subj_short}  <-- {sender_short}")
            posted += 1
        else:
            res = post_to_slack(token, channel_ref, msg)
            if res.get("ok"):
                already_posted.add(msg["message_id"])
                posted += 1
                print(f"  POSTED      {subj_short}  <-- {sender_short}")
            else:
                err = res.get("error", "unknown")
                print(f"  FAIL        {subj_short}  -> {err}")
                log(f"FAIL post {msg['message_id']} {err} {res.get('raw','')[:200]}")
                errors += 1

        if args.limit and posted >= args.limit:
            break

    if not args.dry_run:
        state["posted_message_ids"] = sorted(already_posted)
        state["last_run"] = datetime.now().isoformat()
        save_state(state)

    print(f"\nDone. Posted: {posted}  Skipped (dup): {skipped_dup}  "
          f"Skipped (self): {skipped_self}  Errors: {errors}")
    log(f"run days={args.days} posted={posted} dup={skipped_dup} self={skipped_self} errors={errors}")


if __name__ == "__main__":
    main()
