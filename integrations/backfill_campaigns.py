"""
Backfill all brand deals from Entenmann Enterprise master sheet into Airtable Campaigns table.
Handles both recurring brand tabs (LMNT, Gruns, Equip, Hume, SkinHaven) and one-off tabs.
"""
import csv, json, subprocess, time, os, re
from collections import defaultdict

SHEETS_DIR = r'C:\Users\ejatc\Documents\ENT-Agency-Vault\08-Archive\Spreadsheet-Exports'
BASE_ID = 'app9fVT4bBMHlCf2C'
CAMPAIGNS_TABLE = 'tblZeFe5HEIu8Dcsi'

# Get Airtable token
token = subprocess.run(
    ['doppler', 'secrets', 'get', 'AIRTABLE_API_TOKEN', '--project', 'ent-agency-automation', '--config', 'prd', '--plain'],
    capture_output=True, text=True
).stdout.strip()

# Get creator and brand record ID lookups
import urllib.request

def fetch_all(table_id, field):
    url = f'https://api.airtable.com/v0/{BASE_ID}/{table_id}?fields%5B%5D={field.replace(" ", "+")}&pageSize=100'
    req = urllib.request.Request(url, headers={'Authorization': f'Bearer {token}'})
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())

brands_data = fetch_all('tblIkggimIE4IzJhg', 'Brand Name')
creators_data = fetch_all('tbljzrogjgoC3SFei', 'Creator Name')

brand_map = {r['fields'].get('Brand Name', '').strip().lower(): r['id'] for r in brands_data['records']}
creator_map = {r['fields'].get('Creator Name', '').strip().lower(): r['id'] for r in creators_data['records']}

# Normalize creator names
creator_aliases = {
    'sara preson': 'sara preston',
    'rosé elder': 'rosé elder',
    'rose elder': 'rosé elder',
    'ros\u00e9 elder': 'rosé elder',
    'amy & neil thompson': 'amy thompson',
}

def get_creator_id(name):
    name = name.strip().lower()
    name = creator_aliases.get(name, name)
    return creator_map.get(name)

# Brand name normalization
brand_aliases = {
    'lmnt': 'lmnt',
    'drinklmnt': 'lmnt',
    'gruns': 'gruns',
    'grüns': 'gruns',
    'equip': 'equip foods (purewod)',
    'hume': 'hume health',
    'hume health': 'hume health',
    'skinhaven': 'skinhaven',  # May not be exact match
    'js health': 'js health',
    'jshealth': 'js health',
    'kion aminos': 'kion',
    'kion': 'kion',
    'lumineux': 'lumineux',
    'armra': 'armra',
    'ag1': 'ag1',
    'beekeepers': 'beekeepers naturals',
    'dime': 'dime beauty',
    'dime beauty': 'dime beauty',
    'merit': 'merit beauty',
    'merit beauty': 'merit beauty',
    'cocolab': 'cocolab',
    'avaline': 'avaline',
    'seed': None,  # Not in brands table yet
    'yves rocher': 'yves rocher',
    'oak & luna': None,
    'la pure': None,
    'first aid beauty': None,
    'wildgrain': 'wildgrain',
    'bioma': None,
}

def get_brand_id(name):
    name_lower = name.strip().lower()
    canonical = brand_aliases.get(name_lower, name_lower)
    if canonical is None:
        return None
    return brand_map.get(canonical)

def parse_payment_status(status_str):
    s = (status_str or '').strip().lower()
    if 'paid' in s:
        return 'Paid'
    elif 'sent' in s or 'invoiced' in s:
        return 'Invoiced'
    elif 'pending' in s:
        return 'Pending'
    return None

# ============================================================
# PARSE RECURRING BRAND TABS
# ============================================================
all_records = []

# --- LMNT ---
for fname, year in [('sheet_07_LMNT.csv', '2025'), ('sheet_01_LMNT_2026.csv', '2026')]:
    path = os.path.join(SHEETS_DIR, fname)
    with open(path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            creator = row.get('Client Name ', '').strip()
            if not creator or creator == 'Client Name':
                continue
            month = row.get('Month', '').strip()
            rate_str = row.get('Rate $', '').strip().replace(',', '').replace('$', '')
            rate = float(rate_str) if rate_str and rate_str.replace('.','').isdigit() else None
            deliverables = row.get('Deliverables', '').strip()
            campaign_type = row.get('Campiagn Type', '').strip()
            invoice_status = parse_payment_status(row.get('Invoice Status', ''))

            creator_id = get_creator_id(creator)
            brand_id = get_brand_id('LMNT')

            record = {
                'fields': {
                    'Name': f'LMNT x {creator} - {month} {year}',
                    'Month': f'{month} {year}',
                    'Deliverables': deliverables or campaign_type,
                    'Deal Type': 'Retainer',
                    'Inbound Source': 'Repeat Brand',
                    'Pipeline Stage': 'Paid' if invoice_status == 'Paid' else 'Fully Executed',
                }
            }
            if rate:
                record['fields']['Rate'] = rate
            if brand_id:
                record['fields']['Brand'] = [brand_id]
            if creator_id:
                record['fields']['Creator'] = [creator_id]
            if invoice_status:
                record['fields']['Payment Status'] = invoice_status

            all_records.append(record)

# --- Gruns ---
for fname, year in [('sheet_08_Gruns.csv', '2025'), ('sheet_02_Gruns_2026.csv', '2026')]:
    path = os.path.join(SHEETS_DIR, fname)
    with open(path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            creator = row.get('Client Name ', '').strip()
            if not creator or creator == 'Client Name':
                continue
            month = row.get('Month', '').strip()
            rate_str = row.get('Rate $', '').strip().replace(',', '').replace('$', '')
            rate = float(rate_str) if rate_str and rate_str.replace('.','').isdigit() else None
            deliverables = row.get('Deliverables', '').strip()
            campaign_type = row.get('Campiagn Type', row.get('Campaign Type', '')).strip()
            invoice_status = parse_payment_status(row.get('Invoice Status', ''))

            creator_id = get_creator_id(creator)
            brand_id = get_brand_id('Gruns')

            record = {
                'fields': {
                    'Name': f'Gruns x {creator} - {month} {year}',
                    'Month': f'{month} {year}',
                    'Deliverables': deliverables or campaign_type,
                    'Deal Type': 'Retainer',
                    'Inbound Source': 'Repeat Brand',
                    'Pipeline Stage': 'Paid' if invoice_status == 'Paid' else 'Fully Executed',
                }
            }
            if rate:
                record['fields']['Rate'] = rate
            if brand_id:
                record['fields']['Brand'] = [brand_id]
            if creator_id:
                record['fields']['Creator'] = [creator_id]
            if invoice_status:
                record['fields']['Payment Status'] = invoice_status

            all_records.append(record)

# --- Equip ---
for fname, year in [('sheet_09_Equip_25.csv', '2025'), ('sheet_03_Equip_2026.csv', '2026')]:
    path = os.path.join(SHEETS_DIR, fname)
    with open(path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            creator = row.get('Client Name ', '').strip()
            if not creator or creator == 'Client Name' or 'http' in creator or 'Analytics' in creator:
                continue
            month = row.get('Month', '').strip()
            rate_str = row.get('Rate $', '').strip().replace(',', '').replace('$', '')
            rate = float(rate_str) if rate_str and rate_str.replace('.','').isdigit() else None
            deliverables = row.get('Deliverables', '').strip()
            campaign_type = row.get('Campiagn Type', row.get('Campaign Type', '')).strip()
            invoice_status = parse_payment_status(row.get('Invoice Status', ''))

            creator_id = get_creator_id(creator)
            brand_id = get_brand_id('Equip')

            record = {
                'fields': {
                    'Name': f'Equip x {creator} - {month} {year}',
                    'Month': f'{month} {year}',
                    'Deliverables': deliverables or campaign_type,
                    'Deal Type': 'Retainer',
                    'Inbound Source': 'Repeat Brand',
                    'Pipeline Stage': 'Paid' if invoice_status == 'Paid' else 'Fully Executed',
                }
            }
            if rate:
                record['fields']['Rate'] = rate
            if brand_id:
                record['fields']['Brand'] = [brand_id]
            if creator_id:
                record['fields']['Creator'] = [creator_id]
            if invoice_status:
                record['fields']['Payment Status'] = invoice_status

            all_records.append(record)

# --- Hume ---
for fname, year in [('sheet_10_Hume_.csv', '2025'), ('sheet_04_Hume_2026.csv', '2026')]:
    path = os.path.join(SHEETS_DIR, fname)
    with open(path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            creator = row.get('Client Name ', '').strip()
            if not creator or creator == 'Client Name':
                continue
            month = row.get('Month', '').strip()
            rate_str = row.get('Rate $', '').strip().replace(',', '').replace('$', '')
            rate = float(rate_str) if rate_str and rate_str.replace('.','').isdigit() else None
            deliverables = row.get('Deliverables', '').strip()
            campaign_type = row.get('Campiagn Type', row.get('Campaign Type', '')).strip()
            invoice_status = parse_payment_status(row.get('Invoice Status', ''))

            creator_id = get_creator_id(creator)
            brand_id = get_brand_id('Hume')

            record = {
                'fields': {
                    'Name': f'Hume Health x {creator} - {month} {year}',
                    'Month': f'{month} {year}',
                    'Deliverables': deliverables or campaign_type,
                    'Deal Type': 'Retainer',
                    'Inbound Source': 'Repeat Brand',
                    'Pipeline Stage': 'Paid' if invoice_status == 'Paid' else 'Fully Executed',
                }
            }
            if rate:
                record['fields']['Rate'] = rate
            if brand_id:
                record['fields']['Brand'] = [brand_id]
            if creator_id:
                record['fields']['Creator'] = [creator_id]
            if invoice_status:
                record['fields']['Payment Status'] = invoice_status

            all_records.append(record)

# --- SkinHaven ---
for fname, year in [('sheet_15_SkinHavenetc_.csv', '2025'), ('sheet_06_2026_SkinHavenetc_.csv', '2026')]:
    path = os.path.join(SHEETS_DIR, fname)
    with open(path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            creator = row.get('Client Name ', '').strip()
            if not creator or creator == 'Client Name':
                continue
            month = row.get('Month', '').strip()
            brand_name = row.get('Brand', 'SkinHaven').strip()
            rate_str = row.get('Rate $', '').strip().replace(',', '').replace('$', '')
            rate = float(rate_str) if rate_str and rate_str.replace('.','').isdigit() else None
            campaign_type = row.get('Campiagn Type', row.get('Campaign Type', '')).strip()
            invoice_status = parse_payment_status(row.get('Invoice Status', ''))

            creator_id = get_creator_id(creator)
            brand_id = get_brand_id(brand_name)

            record = {
                'fields': {
                    'Name': f'{brand_name} x {creator} - {month} {year}',
                    'Month': f'{month} {year}',
                    'Deliverables': campaign_type,
                    'Deal Type': 'Retainer',
                    'Inbound Source': 'Repeat Brand',
                    'Pipeline Stage': 'Paid' if invoice_status == 'Paid' else 'Fully Executed',
                }
            }
            if rate:
                record['fields']['Rate'] = rate
            if brand_id:
                record['fields']['Brand'] = [brand_id]
            if creator_id:
                record['fields']['Creator'] = [creator_id]
            if invoice_status:
                record['fields']['Payment Status'] = invoice_status

            all_records.append(record)

print(f"Recurring brand records: {len(all_records)}")

# ============================================================
# PARSE ONE-OFF TABS
# ============================================================
oneoff_count = 0
for fname, year in [('sheet_14_One_Off_Collabs.csv', '2025'), ('sheet_05_One_Offs_2026.csv', '2026')]:
    path = os.path.join(SHEETS_DIR, fname)
    with open(path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            creator = row.get('Client Name ', '').strip()
            brand_name = row.get('Brand', '').strip()
            if not creator or not brand_name or creator == 'Client Name':
                continue
            month = row.get('Month', '').strip()
            rate_str = row.get('Rate $', '').strip().replace(',', '').replace('$', '')
            rate = float(rate_str) if rate_str and rate_str.replace('.','').isdigit() else None
            campaign_type = row.get('Campiagn Type', row.get('Campaign Type', '')).strip()
            invoice_status = parse_payment_status(row.get('Invoice Status', ''))
            approval = row.get('Approval Status', '').strip()

            creator_id = get_creator_id(creator)
            brand_id = get_brand_id(brand_name)

            # Determine if this is actually a repeat
            inbound = 'Repeat Brand' if brand_id else 'Email to marketingteam@'

            record = {
                'fields': {
                    'Name': f'{brand_name} x {creator} - {month} {year}',
                    'Month': f'{month} {year}',
                    'Deliverables': campaign_type,
                    'Deal Type': 'Flat Fee',
                    'Pipeline Stage': 'Paid' if invoice_status == 'Paid' else 'Fully Executed',
                }
            }
            if rate:
                record['fields']['Rate'] = rate
            if brand_id:
                record['fields']['Brand'] = [brand_id]
            if creator_id:
                record['fields']['Creator'] = [creator_id]
            if invoice_status:
                record['fields']['Payment Status'] = invoice_status
            if approval and 'approv' in approval.lower():
                record['fields']['Content Approval Status'] = 'Approved'

            all_records.append(record)
            oneoff_count += 1

print(f"One-off records: {oneoff_count}")
print(f"Total records to upload: {len(all_records)}")

# ============================================================
# UPLOAD TO AIRTABLE
# ============================================================
url = f'https://api.airtable.com/v0/{BASE_ID}/{CAMPAIGNS_TABLE}'
created = 0
errors = 0

for i in range(0, len(all_records), 10):
    batch = all_records[i:i+10]
    payload = json.dumps({'records': batch})

    result = subprocess.run(
        ['curl', '-s', '-X', 'POST', url,
         '-H', f'Authorization: Bearer {token}',
         '-H', 'Content-Type: application/json',
         '-d', payload],
        capture_output=True, text=True
    )

    try:
        resp = json.loads(result.stdout)
        if 'records' in resp:
            created += len(resp['records'])
        elif 'error' in resp:
            errors += len(batch)
            msg = resp['error'].get('message', 'unknown')
            if errors <= 5:
                print(f"  Error at batch {i//10+1}: {msg}")
                # Print the failing record for debugging
                if 'INVALID' in msg.upper():
                    print(f"    First record in batch: {json.dumps(batch[0]['fields'], indent=2)[:200]}")
    except Exception as ex:
        errors += len(batch)
        if errors <= 5:
            print(f"  Parse error at batch {i//10+1}: {ex}")

    if (i + 10) % 100 == 0 or i + 10 >= len(all_records):
        print(f"  Progress: {min(i+10, len(all_records))}/{len(all_records)} | Created: {created} | Errors: {errors}")

    time.sleep(0.25)

print(f"\nDone! Created {created}/{len(all_records)} campaign records ({errors} errors)")
