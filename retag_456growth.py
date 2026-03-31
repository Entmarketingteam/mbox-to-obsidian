"""Re-tag 456Growth emails to their actual sub-brands based on subject line and body content."""
import os, sys, io, re

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

vault = os.path.join(os.path.expanduser("~"), "Documents", "ENT-Agency-Vault")
email_dir = os.path.join(vault, "09-Email-Archive")

# Sub-brand keywords (check longest first to avoid partial matches)
SUB_BRANDS = [
    ("beekeeper's naturals", "Beekeepers Naturals"),
    ("beekeepers naturals", "Beekeepers Naturals"),
    ("beekeeper", "Beekeepers Naturals"),
    ("cocofloss", "Cocofloss"),
    ("coco floss", "Cocofloss"),
    ("kushi beauty", "Kushi Beauty"),
    ("kushi", "Kushi Beauty"),
    ("yves rocher", "Yves Rocher"),
    ("mary ruth", "MaryRuth"),
    ("maryruth", "MaryRuth"),
    ("vitaup", "VitaUp"),
    ("vita up", "VitaUp"),
    ("pique", "Pique"),
    ("levanta", "Levanta"),
    ("remilia", "Remilia"),
    ("lumineux", "Lumineux"),
    ("whitening toothpaste", "Lumineux"),
    ("whitening strips", "Lumineux"),
    ("kion aminos", "Kion"),
    ("kion", "Kion"),
    ("getkion", "Kion"),
    ("jiyu", "JiYu"),
    ("ji yu", "JiYu"),
    ("ji-yu", "JiYu"),
    ("toner pad", "JiYu"),
    ("zena nutrition", "Zena Nutrition"),
    ("zena", "Zena Nutrition"),
    ("body restore", "Body Restore"),
    ("ana luisa", "Ana Luisa"),
    ("analuisa", "Ana Luisa"),
    ("maree", "Maree"),
    ("jessica simpson", "Jessica Simpson"),
    ("armra colostrum", "ARMRA"),
    ("armra", "ARMRA"),
    ("caraway", "Caraway"),
    ("orgain", "Orgain"),
    ("skouts", "Skouts Organic"),
    ("first aid beauty", "First Aid Beauty"),
    ("wildgrain", "Wildgrain"),
    ("bioma", "Bioma"),
    ("dose daily", "Dose Daily"),
    ("oak & luna", "Oak and Luna"),
    ("oak and luna", "Oak and Luna"),
    ("letsjoli", "Letsjoli"),
    ("quince", "Quince"),
    ("seed ", "Seed"),
    ("seed daily", "Seed"),
    ("cocolab", "Cocolab"),
    ("walking pad", "Walking Pad"),
    ("walkingpad", "Walking Pad"),
]

dry_run = "--dry-run" in sys.argv

updated = 0
brand_counts = {}
still_generic = 0

for root, dirs, files in os.walk(email_dir):
    for fn in files:
        if not fn.endswith('.md'):
            continue
        fp = os.path.join(root, fn)
        try:
            with open(fp, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
        except:
            continue

        if '[[456Growth]]' not in content:
            continue

        cl = content.lower()
        matched_brand = None
        for kw, brand in SUB_BRANDS:
            if kw in cl:
                matched_brand = brand
                break

        if not matched_brand:
            still_generic += 1
            continue

        brand_counts[matched_brand] = brand_counts.get(matched_brand, 0) + 1

        if dry_run:
            continue

        # Replace [[456Growth]] with [[MatchedBrand]] (keep 456Growth as secondary)
        new_content = content.replace(
            '[[456Growth]]',
            f'[[{matched_brand}]] (via [[456Growth]])'
        )
        # Update related_brand frontmatter
        new_content = re.sub(
            r'related_brand:\s*"456Growth"',
            f'related_brand: "{matched_brand}"',
            new_content
        )

        with open(fp, 'w', encoding='utf-8') as f:
            f.write(new_content)
        updated += 1

mode = "DRY RUN" if dry_run else "UPDATED"
print(f"\n{mode}: {updated} files re-tagged")
print(f"Still generic 456Growth: {still_generic}")
print(f"\nSub-brand breakdown:")
for brand, c in sorted(brand_counts.items(), key=lambda x: -x[1]):
    print(f"  {brand}: {c}")
