"""
Draft Reply helper — dumps the full text of a TRIAGE_NICKI_OFFERS offer thread
so the agent (Hermes) can draft a reply in Emily's voice.

This script does NOT write or send anything. It only READS a thread and prints
it. The agent reads the output, drafts a reply, and shows it to Emily for
approval/copy. (Auto-creating a Gmail draft would require a gmail.compose
scope upgrade — noted in the skill.)

Usage:
  python draft_reply.py --list                 # list open labeled offers to pick from
  python draft_reply.py --match colleen        # dump the thread matching a brand/subject substring
  python draft_reply.py --thread <thread_id>   # dump a specific thread
  python draft_reply.py                         # if exactly one open offer, dump it
"""
import sys
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import argparse
import base64
import re
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from gmail_api_sync import get_gmail_service, ACCOUNTS  # noqa: E402

LABEL = "TRIAGE_NICKI_OFFERS"
OWN_ADDRESSES = {"marketingteam@nickient.com", "marketingteam@entagency.co"}
MAX_BODY = 2500


def parse_from(s):
    m = re.match(r'(.*?)\s*<(.+?)>', s or "")
    if m:
        return m.group(1).strip().strip('"'), m.group(2).strip().lower()
    s = (s or "").strip()
    return s, s.lower()


def decode_body(payload):
    """Return first text/plain body found, decoded."""
    def walk(part):
        if "parts" in part:
            for sub in part["parts"]:
                r = walk(sub)
                if r:
                    return r
        data = part.get("body", {}).get("data")
        if data and part.get("mimeType") == "text/plain":
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
        return None
    return walk(payload) or ""


def strip_quotes(text):
    """Drop obvious quoted reply chains to keep the dump readable."""
    out = []
    for line in text.splitlines():
        if line.strip().startswith(">"):
            continue
        if re.match(r"^On .+ wrote:$", line.strip()):
            break
        out.append(line)
    return "\n".join(out).strip()


def open_offers(service, days=60):
    """Return [(thread_id, subject, brand, brand_email, days_since)] for labeled threads."""
    ids, page = [], None
    while True:
        kw = {"userId": "me", "q": f"label:{LABEL} newer_than:{days}d", "maxResults": 100}
        if page:
            kw["pageToken"] = page
        resp = service.users().messages().list(**kw).execute()
        for ref in resp.get("messages", []):
            if ref["threadId"] not in [i[0] for i in ids]:
                ids.append((ref["threadId"], None))
        page = resp.get("nextPageToken")
        if not page:
            break
    offers = []
    for tid, _ in ids:
        t = service.users().threads().get(
            userId="me", id=tid, format="metadata",
            metadataHeaders=["From", "Subject", "Date"]).execute()
        msgs = sorted(t.get("messages", []), key=lambda m: int(m.get("internalDate", "0")))
        if not msgs:
            continue
        fh = {h["name"]: h["value"] for h in msgs[0]["payload"]["headers"]}
        subject = fh.get("Subject", "(no subject)")
        brand, bemail = parse_from(fh.get("From", ""))
        for m in msgs:
            h = {x["name"]: x["value"] for x in m["payload"]["headers"]}
            n, e = parse_from(h.get("From", ""))
            if e not in OWN_ADDRESSES:
                brand, bemail = n, e
                break
        last_ms = int(msgs[-1].get("internalDate", "0")) / 1000
        days_since = (datetime.now(timezone.utc) - datetime.fromtimestamp(last_ms, tz=timezone.utc)).days
        offers.append((tid, subject, brand, bemail, days_since))
    return offers


def dump_thread(service, thread_id):
    t = service.users().threads().get(userId="me", id=thread_id, format="full").execute()
    msgs = sorted(t.get("messages", []), key=lambda m: int(m.get("internalDate", "0")))
    print(f"THREAD {thread_id}  ({len(msgs)} messages)")
    print("=" * 70)
    for m in msgs:
        h = {x["name"]: x["value"] for x in m["payload"]["headers"]}
        name, email = parse_from(h.get("From", ""))
        who = "EMILY (us)" if email in OWN_ADDRESSES else f"{name} <{email}>"
        body = strip_quotes(decode_body(m["payload"]))[:MAX_BODY]
        print(f"\n--- {h.get('Date','')}  |  {who}  |  {h.get('Subject','')}")
        print(body if body else "(no plain-text body)")
    print("\n" + "=" * 70)
    print("Above is the full thread. Draft a reply for Emily to send.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--match", default=None, help="brand/subject substring")
    ap.add_argument("--thread", default=None, help="explicit thread id")
    ap.add_argument("--days", type=int, default=60)
    args = ap.parse_args()

    # Build a service per account; offers can live in either inbox (the
    # TRIAGE_NICKI_OFFERS label is on nickient, but search all to be safe).
    services = []
    for acct in ACCOUNTS:
        s = get_gmail_service(acct)
        if s:
            services.append(s)
    if not services:
        print("ERROR: could not authenticate Gmail")
        sys.exit(1)

    if args.thread:
        for s in services:
            try:
                dump_thread(s, args.thread)
                return
            except Exception:
                continue
        print(f"Thread {args.thread} not found in any account.")
        return

    offers, svc_for = [], {}
    for s in services:
        for o in open_offers(s, args.days):
            if o[0] in svc_for:
                continue
            offers.append(o)
            svc_for[o[0]] = s

    if args.list or (not args.match and len(offers) != 1):
        if not offers:
            print(f"No open offers labeled {LABEL} in the last {args.days} days.")
            return
        print(f"Open offers ({len(offers)}) — pick one with --match or --thread:")
        for tid, subj, brand, bemail, age in offers:
            print(f"  • [{tid}] {brand} — {subj}  ({age}d ago)")
        return

    if args.match:
        ml = args.match.lower()
        hits = [o for o in offers if ml in (o[1] or "").lower() or ml in (o[2] or "").lower()
                or ml in (o[3] or "").lower()]
        if not hits:
            print(f"No open offer matches '{args.match}'. Use --list to see them.")
            return
        if len(hits) > 1:
            print(f"'{args.match}' matched {len(hits)} offers — narrow it:")
            for tid, subj, brand, bemail, age in hits:
                print(f"  • [{tid}] {brand} — {subj}")
            return
        dump_thread(svc_for[hits[0][0]], hits[0][0])
        return

    # Exactly one open offer, no match given
    dump_thread(svc_for[offers[0][0]], offers[0][0])


if __name__ == "__main__":
    main()
