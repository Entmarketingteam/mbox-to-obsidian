"""
Pitch Status -- standup view of open brand offers.

Reads Gmail threads labeled TRIAGE_NICKI_OFFERS (across both accounts) and
reports, per deal thread:
  - brand / sender + subject
  - who owes the next move (NEEDS REPLY = brand spoke last; WAITING = we spoke last)
  - how many days since the last message (staleness)

Deterministic, no LLM calls. Designed to be run by the Hermes `pitch-status`
skill, but also useful standalone:

  python pitch_status.py                 # last 60 days of labeled threads
  python pitch_status.py --days 30
  python pitch_status.py --json          # machine-readable for downstream tools
"""
import sys
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from gmail_api_sync import get_gmail_service, ACCOUNTS  # noqa: E402

LABEL = "TRIAGE_NICKI_OFFERS"
OWN_ADDRESSES = {
    "marketingteam@nickient.com",
    "marketingteam@entagency.co",
}


def parse_from_header(from_str):
    m = re.match(r'(.*?)\s*<(.+?)>', from_str or "")
    if m:
        return m.group(1).strip().strip('"'), m.group(2).strip().lower()
    s = (from_str or "").strip()
    return s, s.lower()


def collect_threads(service, label, days):
    """Return {thread_id: subject_hint} for labeled messages in this account."""
    threads = {}
    query = f"label:{label} newer_than:{days}d"
    page_token = None
    while True:
        kwargs = {"userId": "me", "q": query, "maxResults": 100}
        if page_token:
            kwargs["pageToken"] = page_token
        resp = service.users().messages().list(**kwargs).execute()
        for ref in resp.get("messages", []):
            threads.setdefault(ref["threadId"], None)
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return threads


def summarize_thread(service, thread_id):
    """Return a dict describing the latest state of a labeled deal thread."""
    t = service.users().threads().get(
        userId="me", id=thread_id, format="metadata",
        metadataHeaders=["From", "Subject", "Date"],
    ).execute()
    msgs = t.get("messages", [])
    if not msgs:
        return None
    msgs.sort(key=lambda m: int(m.get("internalDate", "0")))
    first_h = {h["name"]: h["value"] for h in msgs[0].get("payload", {}).get("headers", [])}
    last = msgs[-1]
    last_h = {h["name"]: h["value"] for h in last.get("payload", {}).get("headers", [])}

    subject = first_h.get("Subject") or last_h.get("Subject") or "(no subject)"
    last_name, last_email = parse_from_header(last_h.get("From", ""))
    # First inbound (not from us) sender = the brand/agency contact
    brand_name, brand_email = last_name, last_email
    for m in msgs:
        h = {x["name"]: x["value"] for x in m.get("payload", {}).get("headers", [])}
        n, e = parse_from_header(h.get("From", ""))
        if e not in OWN_ADDRESSES:
            brand_name, brand_email = n, e
            break

    last_ms = int(last.get("internalDate", "0")) / 1000
    last_dt = datetime.fromtimestamp(last_ms, tz=timezone.utc)
    days_since = (datetime.now(timezone.utc) - last_dt).days

    we_spoke_last = last_email in OWN_ADDRESSES
    status = "WAITING ON THEM" if we_spoke_last else "NEEDS REPLY"

    return {
        "thread_id": thread_id,
        "subject": subject,
        "brand": brand_name or brand_email,
        "brand_email": brand_email,
        "status": status,
        "days_since": days_since,
        "last_date": last_dt.strftime("%Y-%m-%d"),
        "messages": len(msgs),
        "gmail_url": f"https://mail.google.com/mail/u/0/#inbox/{thread_id}",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=60, help="Look back N days (default 60)")
    ap.add_argument("--json", action="store_true", help="Emit JSON instead of text")
    args = ap.parse_args()

    deals = []
    for account_key in ACCOUNTS:
        service = get_gmail_service(account_key)
        if not service:
            continue
        account_email = ACCOUNTS[account_key]["email"]
        for thread_id in collect_threads(service, LABEL, args.days):
            try:
                d = summarize_thread(service, thread_id)
            except Exception as e:
                d = None
                sys.stderr.write(f"ERR thread {thread_id}: {e}\n")
            if d:
                d["account"] = account_email
                deals.append(d)

    # De-dup by thread_id (a thread could surface from one account only, but be safe)
    seen, unique = set(), []
    for d in deals:
        if d["thread_id"] in seen:
            continue
        seen.add(d["thread_id"])
        unique.append(d)

    # NEEDS REPLY first, then most stale first
    unique.sort(key=lambda d: (d["status"] != "NEEDS REPLY", -d["days_since"]))

    if args.json:
        print(json.dumps(unique, indent=2))
        return

    needs = [d for d in unique if d["status"] == "NEEDS REPLY"]
    waiting = [d for d in unique if d["status"] != "NEEDS REPLY"]

    print(f"PITCH STATUS  —  {len(unique)} open offer thread(s), last {args.days} days")
    print("=" * 60)
    if not unique:
        print("No threads labeled TRIAGE_NICKI_OFFERS in this window.")
        return

    def line(d):
        age = "today" if d["days_since"] == 0 else f"{d['days_since']}d ago"
        return (f"  • {d['brand']}  —  {d['subject']}\n"
                f"      {d['status']} · last activity {age} ({d['last_date']}) · "
                f"{d['messages']} msg · {d['account']}")

    if needs:
        print(f"\nNEEDS REPLY ({len(needs)}) — brand spoke last:")
        for d in needs:
            print(line(d))
    if waiting:
        print(f"\nWAITING ON THEM ({len(waiting)}) — we replied, awaiting their move:")
        for d in waiting:
            print(line(d))


if __name__ == "__main__":
    main()
