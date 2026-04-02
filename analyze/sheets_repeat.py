import csv, os
from collections import defaultdict

sheets_dir = r'C:\Users\ejatc\Documents\ENT-Agency-Vault\08-Archive\Spreadsheet-Exports'

# ============================================================
# RECURRING BRAND TABS (dedicated sheets = guaranteed recurring)
# ============================================================
recurring_brands = {}

# LMNT - both years
for fname, label in [('sheet_07_LMNT.csv', 'LMNT 2025'), ('sheet_01_LMNT_2026.csv', 'LMNT 2026')]:
    path = os.path.join(sheets_dir, fname)
    with open(path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        rows = [r for r in reader if r.get('Client Name ', '').strip()]
    creators = set(r['Client Name '].strip() for r in rows if r['Client Name '].strip())
    recurring_brands[label] = {'rows': len(rows), 'creators': creators}
    print(f"{label}: {len(rows)} deal-months across {len(creators)} creators: {', '.join(sorted(creators))}")

# Gruns
for fname, label in [('sheet_08_Gruns.csv', 'Gruns 2025'), ('sheet_02_Gruns_2026.csv', 'Gruns 2026')]:
    path = os.path.join(sheets_dir, fname)
    with open(path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        rows = [r for r in reader if r.get('Client Name ', '').strip()]
    creators = set(r['Client Name '].strip() for r in rows if r['Client Name '].strip())
    recurring_brands[label] = {'rows': len(rows), 'creators': creators}
    print(f"{label}: {len(rows)} deal-months across {len(creators)} creators: {', '.join(sorted(creators))}")

# Equip
for fname, label in [('sheet_09_Equip_25.csv', 'Equip 2025'), ('sheet_03_Equip_2026.csv', 'Equip 2026')]:
    path = os.path.join(sheets_dir, fname)
    with open(path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        rows = [r for r in reader if r.get('Client Name ', '').strip()]
    creators = set(r['Client Name '].strip() for r in rows if r['Client Name '].strip())
    recurring_brands[label] = {'rows': len(rows), 'creators': creators}
    print(f"{label}: {len(rows)} deal-months across {len(creators)} creators: {', '.join(sorted(creators))}")

# Hume
for fname, label in [('sheet_10_Hume_.csv', 'Hume 2025'), ('sheet_04_Hume_2026.csv', 'Hume 2026')]:
    path = os.path.join(sheets_dir, fname)
    with open(path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        rows = [r for r in reader if r.get('Client Name ', '').strip()]
    creators = set(r['Client Name '].strip() for r in rows if r['Client Name '].strip())
    recurring_brands[label] = {'rows': len(rows), 'creators': creators}
    print(f"{label}: {len(rows)} deal-months across {len(creators)} creators: {', '.join(sorted(creators))}")

# SkinHaven etc
for fname, label in [('sheet_15_SkinHavenetc_.csv', 'SkinHaven+ 2025'), ('sheet_06_2026_SkinHavenetc_.csv', 'SkinHaven+ 2026')]:
    path = os.path.join(sheets_dir, fname)
    with open(path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        rows = [r for r in reader if r.get('Client Name ', '').strip()]
    creators = set(r['Client Name '].strip() for r in rows if r['Client Name '].strip())
    recurring_brands[label] = {'rows': len(rows), 'creators': creators}
    print(f"{label}: {len(rows)} deal-months across {len(creators)} creators: {', '.join(sorted(creators))}")

# ============================================================
# ONE-OFF COLLABS (both years)
# ============================================================
print(f"\n{'='*70}")

oneoff_deals = defaultdict(lambda: defaultdict(int))  # brand -> creator -> count

for fname, label in [('sheet_14_One_Off_Collabs.csv', 'One-Offs 2025'), ('sheet_05_One_Offs_2026.csv', 'One-Offs 2026')]:
    path = os.path.join(sheets_dir, fname)
    with open(path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    total = 0
    for r in rows:
        creator = r.get('Client Name ', '').strip()
        brand = r.get('Brand', '').strip()
        if creator and brand:
            oneoff_deals[brand][creator] += 1
            total += 1
    print(f"{label}: {total} deals across {len(set(r.get('Brand','').strip() for r in rows if r.get('Brand','').strip()))} brands")

# ============================================================
# Affiliate/Monthly Adds
# ============================================================
path = os.path.join(sheets_dir, 'sheet_11_AffiliateMonthly_Adds.csv')
with open(path, 'r', encoding='utf-8-sig') as f:
    reader = csv.reader(f)
    aff_rows = list(reader)
print(f"\nAffiliate/Monthly Adds: {len(aff_rows)} rows (recurring brand lists per creator)")

# ============================================================
# FULL ANALYSIS
# ============================================================
print(f"\n{'='*70}")
print(f"  FULL REPEAT ANALYSIS — ENTENMANN ENTERPRISE MASTER SHEET")
print(f"  (All creators, all brands, 2025-2026)")
print(f"{'='*70}")

# Count total recurring deal-months from dedicated tabs
total_recurring_deals = sum(rb['rows'] for rb in recurring_brands.values())
total_oneoff_deals = sum(sum(creators.values()) for creators in oneoff_deals.values())
total_all = total_recurring_deals + total_oneoff_deals

print(f"\n  RECURRING brand deal-months (dedicated tabs):  {total_recurring_deals}")
print(f"  ONE-OFF brand deals:                            {total_oneoff_deals}")
print(f"  TOTAL deals tracked:                            {total_all}")
print(f"")
print(f"  RECURRING as % of all deals: {total_recurring_deals/total_all*100:.1f}%")
print(f"  ONE-OFF as % of all deals:   {total_oneoff_deals/total_all*100:.1f}%")

# Now check: how many "one-off" brands actually appear multiple times?
repeat_in_oneoffs = {b: c for b, c in oneoff_deals.items() if sum(c.values()) >= 2}
truly_oneoff = {b: c for b, c in oneoff_deals.items() if sum(c.values()) == 1}

print(f"\n  Within the 'One-Off' tabs:")
print(f"    Brands that appeared 2+ times: {len(repeat_in_oneoffs)} ({len(repeat_in_oneoffs)/len(oneoff_deals)*100:.0f}% of 'one-off' brands are actually repeat!)")
print(f"    Truly single-time brands:      {len(truly_oneoff)}")

repeat_oneoff_deals = sum(sum(c.values()) for c in repeat_in_oneoffs.values())
truly_oneoff_deals = sum(sum(c.values()) for c in truly_oneoff.values())

print(f"    Deals from repeat 'one-offs':  {repeat_oneoff_deals}")
print(f"    Deals from true one-offs:      {truly_oneoff_deals}")

# Recalculate with corrected numbers
actual_recurring = total_recurring_deals + repeat_oneoff_deals
actual_oneoff = truly_oneoff_deals

print(f"\n  CORRECTED TOTALS:")
print(f"    Actual recurring deals:  {actual_recurring} ({actual_recurring/total_all*100:.1f}%)")
print(f"    Actual one-off deals:    {actual_oneoff} ({actual_oneoff/total_all*100:.1f}%)")

# Per-brand summary from dedicated tabs
print(f"\n{'='*70}")
print(f"  RECURRING BRANDS — DEAL VOLUME ACROSS ALL CREATORS")
print(f"{'='*70}")

# Aggregate by brand across years
brand_totals = defaultdict(lambda: {'deal_months': 0, 'creators': set()})
for label, data in recurring_brands.items():
    brand = label.rsplit(' ', 1)[0]  # Remove year
    brand_totals[brand]['deal_months'] += data['rows']
    brand_totals[brand]['creators'].update(data['creators'])

print(f"\n  {'Brand':<20} {'Deal-Months':>12} {'Creators':>9}")
print(f"  {'-'*20} {'-'*12} {'-'*9}")
for brand in sorted(brand_totals.keys(), key=lambda b: brand_totals[b]['deal_months'], reverse=True):
    d = brand_totals[brand]
    print(f"  {brand:<20} {d['deal_months']:>12} {len(d['creators']):>9}")

# Per-creator deal count
print(f"\n{'='*70}")
print(f"  PER-CREATOR DEAL COUNT (from master sheet)")
print(f"{'='*70}")

creator_total = defaultdict(lambda: {'recurring': 0, 'oneoff': 0})
for label, data in recurring_brands.items():
    for c in data['creators']:
        # Count how many rows this creator has in this tab
        pass  # We'd need per-creator row counts

# Count from one-off tabs per creator
creator_oneoff = defaultdict(int)
for brand, creators in oneoff_deals.items():
    for c, count in creators.items():
        creator_oneoff[c] += count

print(f"\n  {'Creator':<25} {'One-Off Deals':>13}")
print(f"  {'-'*25} {'-'*13}")
for c in sorted(creator_oneoff.keys(), key=lambda x: creator_oneoff[x], reverse=True):
    print(f"  {c:<25} {creator_oneoff[c]:>13}")

# Brands that appear in one-offs multiple times
print(f"\n{'='*70}")
print(f"  'ONE-OFF' BRANDS THAT ARE ACTUALLY REPEAT (2+ deals)")
print(f"{'='*70}")
print(f"\n  {'Brand':<30} {'Total Deals':>11} {'Creators'}")
print(f"  {'-'*30} {'-'*11} {'-'*30}")
for brand in sorted(repeat_in_oneoffs.keys(), key=lambda b: sum(repeat_in_oneoffs[b].values()), reverse=True):
    creators = repeat_in_oneoffs[brand]
    total = sum(creators.values())
    clist = ', '.join(f"{c}({n})" for c, n in creators.items())
    print(f"  {brand:<30} {total:>11} {clist}")
