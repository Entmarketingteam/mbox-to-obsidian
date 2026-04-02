"""
Airtable → Google Calendar Sync
Reads Campaigns with Live Date / FU Date / Content Due Date set,
creates Google Calendar events using the LIVE:/FU:/DUE: naming convention.

Run on a schedule (e.g., every 30 min via Task Scheduler) or manually.

Requires:
- Doppler: AIRTABLE_API_TOKEN, GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET,
           GMAIL_REFRESH_TOKEN_NICKIENT (reusing for calendar access)
- pip install google-api-python-client google-auth-oauthlib
"""
import json, subprocess, sys, os
from datetime import datetime, timedelta

# ============================================================
# CONFIG
# ============================================================
BASE_ID = 'app9fVT4bBMHlCf2C'
CAMPAIGNS_TABLE = 'tblZeFe5HEIu8Dcsi'
CONTENT_CAL_TABLE = 'tblJHngveI3SiCw3D'

# Calendar to create events on (Nicki's personal = primary, or use TEST-COLLABS)
TARGET_CALENDAR = 'primary'

# ============================================================
# GET SECRETS
# ============================================================
def get_secret(key, project='ent-agency-analytics', config='dev'):
    result = subprocess.run(
        ['doppler', 'secrets', 'get', key, '--project', project, '--config', config, '--plain'],
        capture_output=True, text=True
    )
    return result.stdout.strip()

airtable_token = get_secret('AIRTABLE_API_TOKEN', 'ent-agency-automation', 'prd')

# ============================================================
# AIRTABLE: Get campaigns with dates but not yet synced
# ============================================================
import urllib.request

def airtable_get(table_id, formula=None, fields=None):
    """Fetch records from Airtable with optional filterByFormula."""
    params = ['pageSize=100']
    if formula:
        params.append(f'filterByFormula={urllib.parse.quote(formula)}')
    if fields:
        for f in fields:
            params.append(f'fields%5B%5D={urllib.parse.quote(f)}')

    url = f'https://api.airtable.com/v0/{BASE_ID}/{table_id}?{"&".join(params)}'
    req = urllib.request.Request(url, headers={'Authorization': f'Bearer {airtable_token}'})

    all_records = []
    while url:
        req = urllib.request.Request(url, headers={'Authorization': f'Bearer {airtable_token}'})
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())
        all_records.extend(data.get('records', []))
        offset = data.get('offset')
        if offset:
            base_url = url.split('&offset=')[0]
            url = f'{base_url}&offset={offset}'
        else:
            break
    return all_records

def airtable_update(table_id, record_id, fields):
    """Update a single record in Airtable."""
    url = f'https://api.airtable.com/v0/{BASE_ID}/{table_id}/{record_id}'
    data = json.dumps({'fields': fields}).encode()
    req = urllib.request.Request(url, data=data, method='PATCH',
                                headers={'Authorization': f'Bearer {airtable_token}',
                                        'Content-Type': 'application/json'})
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())

# ============================================================
# GOOGLE CALENDAR: Auth + create events
# ============================================================
try:
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
except ImportError:
    print("Installing google-api-python-client...")
    subprocess.run([sys.executable, '-m', 'pip', 'install',
                    'google-api-python-client', 'google-auth-oauthlib'],
                   capture_output=True)
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

def get_calendar_service():
    """Build Google Calendar API service."""
    client_id = get_secret('GOOGLE_OAUTH_CLIENT_ID')
    client_secret = get_secret('GOOGLE_OAUTH_CLIENT_SECRET')
    refresh_token = get_secret('GMAIL_REFRESH_TOKEN_NICKIENT')

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        client_id=client_id,
        client_secret=client_secret,
        token_uri='https://oauth2.googleapis.com/token',
        scopes=['https://www.googleapis.com/auth/calendar']
    )
    return build('calendar', 'v3', credentials=creds)

# ============================================================
# SYNC LOGIC
# ============================================================
def build_event_name(prefix, brand_name, deliverables=''):
    """Build calendar event name using the naming convention."""
    name = f'{prefix}: {brand_name}'
    if deliverables:
        # Map deliverables to suffix
        dl = deliverables.lower()
        if 'reel' in dl and 'story' in dl and 'ltk' in dl:
            name += ' IG Reel + Story + LTK'
        elif 'reel' in dl and 'story' in dl:
            name += ' IG Reel + Story Set'
        elif 'story' in dl:
            name += ' IG Story Set'
        elif 'reel' in dl:
            name += ' Reel'
        elif 'tiktok' in dl:
            name += ' TikTok'
    return name

def create_calendar_event(service, summary, date_str, description=''):
    """Create an all-day calendar event."""
    event = {
        'summary': summary,
        'start': {'date': date_str},
        'end': {'date': date_str},
        'description': description,
        'reminders': {'useDefault': False, 'overrides': [
            {'method': 'popup', 'minutes': 60 * 9},  # 9am day-of
        ]},
    }

    try:
        created = service.events().insert(
            calendarId=TARGET_CALENDAR,
            body=event,
            sendUpdates='none'
        ).execute()
        return created.get('id')
    except Exception as e:
        print(f"  ERROR creating event '{summary}': {e}")
        return None

def sync_campaigns():
    """Main sync: Airtable Campaigns → Google Calendar events."""
    print(f"Fetching campaigns with Live Date, FU Date, or Content Due Date...")

    # Get campaigns that have dates set
    # We can't use complex OR formulas easily, so get all with Live Date
    fields = ['Name', 'Brand', 'Creator', 'Live Date', 'FU Date',
              'Content Due Date', 'Deliverables', 'Pipeline Stage']

    campaigns = airtable_get(CAMPAIGNS_TABLE, fields=fields)
    print(f"Total campaigns: {len(campaigns)}")

    # Also get brand name lookup
    brands = airtable_get('tblIkggimIE4IzJhg', fields=['Brand Name'])
    brand_map = {r['id']: r['fields'].get('Brand Name', '?') for r in brands}

    creators = airtable_get('tbljzrogjgoC3SFei', fields=['Creator Name'])
    creator_map = {r['id']: r['fields'].get('Creator Name', '?') for r in creators}

    # Build calendar service
    service = get_calendar_service()

    events_created = 0

    for camp in campaigns:
        f = camp['fields']
        name = f.get('Name', '')
        live_date = f.get('Live Date')
        fu_date = f.get('FU Date')
        due_date = f.get('Content Due Date')
        deliverables = f.get('Deliverables', '')

        # Get brand name
        brand_ids = f.get('Brand', [])
        brand_name = brand_map.get(brand_ids[0], '?') if brand_ids else name.split(' x ')[0] if ' x ' in name else name

        # Get creator name
        creator_ids = f.get('Creator', [])
        creator_name = creator_map.get(creator_ids[0], '') if creator_ids else ''

        description = f'Campaign: {name}\nCreator: {creator_name}\nDeliverables: {deliverables}'

        # Create LIVE event
        if live_date and live_date >= datetime.now().strftime('%Y-%m-%d'):
            event_name = build_event_name('LIVE', brand_name, deliverables)
            event_id = create_calendar_event(service, event_name, live_date, description)
            if event_id:
                events_created += 1
                print(f"  Created: {event_name} on {live_date}")

        # Create FU event
        if fu_date and fu_date >= datetime.now().strftime('%Y-%m-%d'):
            event_name = f'FU: {brand_name}'
            event_id = create_calendar_event(service, event_name, fu_date, description)
            if event_id:
                events_created += 1
                print(f"  Created: {event_name} on {fu_date}")

        # Create DUE event
        if due_date and due_date >= datetime.now().strftime('%Y-%m-%d'):
            event_name = build_event_name('DUE', brand_name, deliverables)
            event_id = create_calendar_event(service, event_name, due_date, description)
            if event_id:
                events_created += 1
                print(f"  Created: {event_name} on {due_date}")

    print(f"\nSync complete! Created {events_created} calendar events.")

if __name__ == '__main__':
    sync_campaigns()
