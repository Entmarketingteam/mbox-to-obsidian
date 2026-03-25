#!/usr/bin/env bash
# Setup gws CLI for email sync
# Run this once on each machine

set -e

echo "=== GWS Email Sync Setup ==="
echo ""

# Check if gws is installed
if ! command -v gws &>/dev/null; then
    echo "Installing @googleworkspace/cli..."
    npm install -g @googleworkspace/cli
else
    echo "✓ gws CLI already installed ($(which gws))"
fi

# Check if authenticated
echo ""
echo "Testing authentication..."
if gws gmail users messages list --params '{"userId": "me", "maxResults": 1}' 2>&1 | grep -q "authError\|401"; then
    echo ""
    echo "Not authenticated. Running gws auth login..."
    echo "This will open a browser — sign in with the Gmail account you want to sync."
    echo ""
    gws auth login
else
    echo "✓ gws is authenticated"
fi

# Verify
echo ""
echo "Verifying access..."
RESULT=$(gws gmail users getProfile --params '{"userId": "me"}' 2>/dev/null || echo "{}")
EMAIL=$(echo "$RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('emailAddress','UNKNOWN'))" 2>/dev/null || echo "UNKNOWN")
echo "✓ Connected as: $EMAIL"

echo ""
echo "=== Setup complete ==="
echo ""
echo "Sync recent emails:"
echo "  python3 gws_email_sync.py --account $EMAIL"
echo ""
echo "Sync last 7 days:"
echo "  python3 gws_email_sync.py --account $EMAIL --days 7"
echo ""
echo "Sync all history (nickient.com back to 2021):"
echo "  python3 gws_email_sync.py --account marketingteam@nickient.com --after 2021-01-01"
echo ""
echo "To switch accounts, run: gws auth login"
echo "  (sign in with the other Gmail account)"
