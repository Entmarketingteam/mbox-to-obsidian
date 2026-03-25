#!/usr/bin/env bash
# Sync both Gmail accounts into the vault
# Run daily via cron or manually
#
# NOTE: gws auth only supports one account at a time.
# To sync both accounts:
#   1. Run this script — it syncs whichever account is currently authed
#   2. Run `gws auth login` and sign in with the other account
#   3. Run this script again
#
# Or set up two cron jobs with separate credential files.

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DAYS="${1:-1}"  # Default: last 1 day. Pass number as argument for more.

echo "=== Syncing Gmail → Obsidian Vault ==="
echo "Days: $DAYS"
echo ""

# Detect which account is authed
PROFILE=$(gws gmail users getProfile --params '{"userId": "me"}' 2>/dev/null || echo "{}")
EMAIL=$(echo "$PROFILE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('emailAddress','UNKNOWN'))" 2>/dev/null || echo "UNKNOWN")

if [ "$EMAIL" = "UNKNOWN" ]; then
    echo "ERROR: gws not authenticated. Run: gws auth login"
    exit 1
fi

echo "Authenticated as: $EMAIL"
echo ""

python3 "$SCRIPT_DIR/gws_email_sync.py" --account "$EMAIL" --days "$DAYS"

echo ""
echo "Done. To sync the other account:"
echo "  1. gws auth login  (sign in with the other account)"
echo "  2. ./sync_both_accounts.sh $DAYS"
