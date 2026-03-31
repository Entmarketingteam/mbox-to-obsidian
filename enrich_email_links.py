"""
Enrich Email Links -- Add [[wikilinks]] to brand profiles in email archive notes.

Scans 09-Email-Archive/ for email notes, matches sender domains to known brands
(from 01-Brands-Contacts/ profiles + hardcoded mappings), and adds:
  - related_brand: field in frontmatter
  - [[BrandName]] wikilink in a ## Related section at the bottom

Usage:
    python enrich_email_links.py                  # full run
    python enrich_email_links.py --dry-run        # preview only
    python enrich_email_links.py --dry-run --limit 100
"""

# ── Windows UTF-8 fix ────────────────────────────────────────────────────────
import sys
import io
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import os
import re
import argparse
from pathlib import Path

# ── Config ───────────────────────────────────────────────────────────────────
_HOME = os.path.expanduser("~")
VAULT = os.path.join(_HOME, "Documents", "ENT-Agency-Vault")
BRANDS_DIR = os.path.join(VAULT, "01-Brands-Contacts")
EMAIL_DIR = os.path.join(VAULT, "09-Email-Archive")

# Hardcoded domain -> brand name mappings for known brands
# Generic domains that should never be mapped to a single brand
GENERIC_DOMAINS = {
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "icloud.com",
    "aol.com", "live.com", "me.com", "msn.com", "comcast.net",
    "protonmail.com", "proton.me", "mail.com",
    "google.com", "amazon.com", "facebook.com", "apple.com", "microsoft.com",
    "mailchimpapp.com",
}

# Hardcoded domain -> brand name mappings for known brands
HARDCODED_DOMAINS = {
    # ── Tier 1: Anchor / Active Paid Brands (current roster) ──────────────
    "drinklmnt.com":              "DrinkLMNT",
    "456growth.com":              "456Growth",
    "gruns.co":                   "Gruns",
    "eatgruns.com":               "Gruns",
    "equipfoods.com":             "Equip",
    "cubert.co":                  "Hume Health",
    "myhumehealth.com":           "Hume Health",
    "tryhumehealth.com":          "Hume Health",
    "meritbeauty.com":            "Merit Beauty",
    "dimebeautyco.com":           "DIME Beauty",
    "beamtlc.com":                "BEAM TLC",
    "nutrafol.com":               "Nutrafol",
    "armra.com":                  "ARMRA",
    "tryarmra.com":               "ARMRA",
    "trend-mgmt.com":             "Trend Management",
    "lumanu.com":                  "Lumanu",
    "oseamalibu.com":             "OSEA Malibu",
    "arrae.com":                  "Arrae",
    "clearstem.com":              "CLEARSTEM",
    "vicicollection.com":         "VICI Collection",
    "tula.com":                   "TULA",
    "tulaforlife.com":            "TULA",
    "dermalea.com":               "Dermalea",
    "oeak.com":                   "OEAK",
    "rothschildbeauty.com":       "Colleen Rothschild",
    "pinkstork.com":              "Pink Stork",
    "influential.co":             "Influential",
    "wallicases.com":             "Walli Cases",
    "eckodigitalmedia.com":       "Ecko Digital Media",
    "brandmail.co":               "Walmart Fashion",
    "joinmavely.com":             "Walmart Fashion",
    "butcherbox.com":             "Butcherbox",

    # ── Tier 1: Managed Talent One-Off Paid Brands ────────────────────────
    "lumineux.com":               "Lumineux",
    "kfruns.com":                  "Kion",
    "kfruns.co":                   "Kion",
    "seedhealth.com":              "Seed",
    "seed.com":                    "Seed",
    "orgain.com":                  "Orgain",
    "ag1.com":                     "AG1",
    "athleticgreens.com":          "AG1",
    "drinkag1.com":                "AG1",
    "avaline.com":                 "Avaline",
    "jshealthvitamins.com":        "JS Health",
    "firstaidbeauty.com":          "First Aid Beauty",
    "wildgrain.com":               "Wildgrain",
    "oakandluna.com":              "Oak and Luna",
    "cocofloss.com":               "Cocofloss",
    "yvesrocherusa.com":           "Yves Rocher",
    "bioma.com":                   "Bioma",
    "dosedaily.com":               "Dose Daily",
    "skoutsorganic.com":           "Skouts Organic",
    "piquelabs.com":               "Pique",
    "pique.com":                   "Pique",
    "lapure.com":                  "La Pure",

    # ── Tier 1: Historical Paid Brands (significant relationship) ─────────
    "influencerresponse.com":      "Beekeepers Naturals",
    "accelerationpartners.com":    "Beekeepers Naturals",
    "fromourplace.com":            "Our Place",
    "thrivemarket.com":            "Thrive Market",
    "madebymary.com":              "Made by Mary",
    "nuuds.com":                   "Nuuds",
    "justingredients.us":          "Just Ingredients",
    "branchbasics.com":            "Branch Basics",
    "diviofficial.com":            "Divi",
    "koparibeauty.com":            "Kopari Beauty",
    "badbirdiegolf.com":           "Bad Birdie",
    "primalkitchen.com":           "Primal Kitchen",
    "aloha.com":                   "Aloha",
    "spanx.com":                   "Spanx",
    "bloomnu.com":                 "Bloom",
    "pinklily.com":                "Pink Lily",
    "brumate.com":                 "BruMate",
    "navyhaircare.com":            "Navy Hair Care",
    "shopreddress.com":            "Red Dress",
    "yourparade.com":              "Parade",
    "tarte.com":                   "Tarte",
    "fabletics.com":               "Fabletics",
    "wearewild.com":               "Wild",
    "rarebeauty.com":              "Rare Beauty",
    "primallypure.com":            "Primally Pure",
    "lulus.com":                   "Lulus",
    "cupshe.com":                  "Cupshe",
    "peachandlily.com":            "Peach & Lily",
    "livingproof.com":             "Living Proof",
    "ghostgolf.com":               "Ghost Golf",
    "alaninu.com":                 "Alani Nu",
    "petalandpup.com.au":          "Petal & Pup",
    "babeoriginal.com":            "Babe Original",
    "empwrnutrition.com":          "EMPWR Nutrition",
    "oijc.com":                    "Natalie's Juice",
    "superiorsupplementmfg.com":   "Superior Supplement Mfg",
    "inopro.us":                   "InoPro",
    "creatoriq.com":               "CreatorIQ",
    "abmc-us.com":                 "ABMC",

    # ── Tier 1: Product Development Partners ──────────────────────────────
    "pharmachem.com":              "Pharmachem",
    "formulife.com":               "Formulife",
    "kcmconnect.co":               "KCM",
    "healthyiish.com":             "Healthyiish",

    # ── Platforms & Agencies (map to the platform, not the end brand) ─────
    "hellofresh.com":              "HelloFresh",
    "hellofresh.de":               "HelloFresh",
    "villagemarketing.com":        "Village Marketing",
    "cegtalent.com":               "CEG Talent",
    "starpowerllc.com":            "Star Power",
    "thetrendsocial.com":          "The Trend Social",
    "viralpromotors.com":          "Viral Promotors",
    "productsociety.com":          "Product Society",
    "ltk.com":                     "LTK",
    "rewardstyle.com":             "LTK",
}

# ── Domain mapping builder ───────────────────────────────────────────────────

def extract_domain(email_addr):
    """Extract domain from an email address string."""
    if not email_addr:
        return None
    email_addr = email_addr.strip().strip('"').strip("'")
    # Handle "Name <email@domain>" format
    m = re.search(r'<([^>]+)>', email_addr)
    if m:
        email_addr = m.group(1)
    if "@" in email_addr:
        return email_addr.split("@")[-1].strip().lower()
    return None


def parse_frontmatter(text):
    """Parse YAML frontmatter from a markdown file. Returns (dict, body_text, raw_fm_text)."""
    if not text.startswith("---"):
        return {}, text, ""
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text, ""
    fm_text = text[3:end].strip()
    body = text[end + 4:]  # skip past the closing ---
    fm = {}
    for line in fm_text.split("\n"):
        # Simple key: value parsing (not full YAML, handles our use case)
        if ":" in line and not line.strip().startswith("-") and not line.strip().startswith("#"):
            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            fm[key] = val
    return fm, body, fm_text


def build_domain_map():
    """
    Build domain -> brand_name mapping from:
    1. Hardcoded mappings
    2. Brand profile frontmatter (domain: and contact_email:)
    3. Key Contacts tables in brand profiles
    """
    domain_map = dict(HARDCODED_DOMAINS)

    if not os.path.isdir(BRANDS_DIR):
        print(f"  [WARN] Brands directory not found: {BRANDS_DIR}")
        return domain_map

    brand_files = [f for f in os.listdir(BRANDS_DIR) if f.endswith(".md") and not f.startswith("_")]

    for fname in brand_files:
        fpath = os.path.join(BRANDS_DIR, fname)
        try:
            with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
        except Exception:
            continue

        fm, body, _ = parse_frontmatter(text)

        # Brand name: use the 'company' field, or the H1, or the filename stem
        brand_name = fm.get("company", "").strip().strip('"').strip("'")
        if not brand_name:
            # Try to find the first H1 header
            h1_match = re.search(r'^# (.+)$', text, re.MULTILINE)
            if h1_match:
                brand_name = h1_match.group(1).strip()
            else:
                brand_name = Path(fname).stem

        if not brand_name:
            continue

        # Extract from domain: frontmatter field
        domain_val = fm.get("domain", "")
        if domain_val:
            domain_val = domain_val.lower().strip()
            if domain_val and domain_val not in domain_map and domain_val not in GENERIC_DOMAINS:
                domain_map[domain_val] = brand_name

        # Extract from contact_email: frontmatter field
        contact_email = fm.get("contact_email", "")
        d = extract_domain(contact_email)
        if d and d not in domain_map and d not in GENERIC_DOMAINS:
            domain_map[d] = brand_name

        # Extract emails from Key Contacts table rows
        # Pattern: | Name | email@domain.com | Role |
        table_emails = re.findall(r'\|\s*[^|]+\s*\|\s*([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)\s*\|', body)
        for te in table_emails:
            d = extract_domain(te)
            if d and d not in domain_map and d not in GENERIC_DOMAINS:
                domain_map[d] = brand_name

    return domain_map


# ── Email processing ─────────────────────────────────────────────────────────

def get_sender_domain(fm, body_text):
    """
    Extract the sender's email domain from an email note.
    Checks multiple frontmatter fields and body patterns.
    """
    # Method 1: from_email frontmatter field (Gmail-Captures format)
    from_email = fm.get("from_email", "")
    d = extract_domain(from_email)
    if d:
        return d

    # Method 2: from field may contain "Name <email>" (capture format)
    from_field = fm.get("from", "")
    d = extract_domain(from_field)
    if d:
        return d

    # Method 3: sender_email frontmatter field
    sender_email = fm.get("sender_email", "")
    d = extract_domain(sender_email)
    if d:
        return d

    # Method 4: Look for **From:** line in body
    from_line = re.search(r'\*\*From:\*\*\s*(.+)', body_text)
    if from_line:
        d = extract_domain(from_line.group(1))
        if d:
            return d

    return None


def already_has_wikilink(body, brand_name):
    """Check if the body already contains a [[BrandName]] wikilink."""
    # Check for exact [[BrandName]] or [[BrandName|...]] patterns
    pattern = re.escape(brand_name)
    return bool(re.search(r'\[\[' + pattern + r'(\|[^\]]+)?\]\]', body))


def add_related_brand_frontmatter(text, brand_name):
    """
    Add or update the related_brand: field in frontmatter.
    Returns the updated full text.
    """
    if not text.startswith("---"):
        return text

    end = text.find("\n---", 3)
    if end == -1:
        return text

    fm_block = text[3:end]
    rest = text[end:]  # includes the closing ---

    # Check if related_brand already exists
    if re.search(r'^related_brand:', fm_block, re.MULTILINE):
        # Update existing value
        fm_block = re.sub(
            r'^(related_brand:)\s*.*$',
            f'\\1 "{brand_name}"',
            fm_block,
            flags=re.MULTILINE
        )
    else:
        # Add before the closing ---
        fm_block = fm_block.rstrip() + f'\nrelated_brand: "{brand_name}"'

    return "---" + fm_block + rest


def add_related_section(body, brand_name):
    """
    Add a ## Related section with [[BrandName]] wikilink at the bottom,
    if one doesn't already exist with this brand linked.
    """
    if already_has_wikilink(body, brand_name):
        return body, False

    # Check if there's already a ## Related section
    related_match = re.search(r'^## Related\s*\n', body, re.MULTILINE)
    if related_match:
        # Insert the wikilink after the ## Related header
        insert_pos = related_match.end()
        updated = body[:insert_pos] + f"- [[{brand_name}]]\n" + body[insert_pos:]
        return updated, True
    else:
        # Add a new ## Related section at the bottom
        body = body.rstrip() + f"\n\n## Related\n- [[{brand_name}]]\n"
        return body, True

    return body, False


def process_email_file(fpath, domain_map, dry_run=False):
    """
    Process a single email file. Returns (brand_name, was_updated) or (None, False).
    """
    try:
        with open(fpath, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    except Exception as e:
        return None, False

    if not text.startswith("---"):
        return None, False

    fm, body, _ = parse_frontmatter(text)

    # Only process email/capture type notes
    note_type = fm.get("type", "").lower().strip('"').strip("'")
    if note_type not in ("email", "capture", ""):
        return None, False

    # Get sender domain
    sender_domain = get_sender_domain(fm, body)
    if not sender_domain:
        return None, False

    # Look up brand
    brand_name = domain_map.get(sender_domain)
    if not brand_name:
        return None, False

    # Check if already fully linked (both frontmatter and body)
    existing_brand = fm.get("related_brand", "").strip().strip('"').strip("'")
    has_link = already_has_wikilink(body, brand_name)

    if existing_brand == brand_name and has_link:
        return brand_name, False  # already done

    if dry_run:
        return brand_name, True

    # Apply changes
    updated_text = add_related_brand_frontmatter(text, brand_name)
    # Re-parse to get the new body for wikilink insertion
    _, updated_body, _ = parse_frontmatter(updated_text)
    new_body, link_added = add_related_section(updated_body, brand_name)

    if link_added:
        # Reconstruct the full text with updated body
        end = updated_text.find("\n---", 3)
        fm_part = updated_text[:end + 4]
        updated_text = fm_part + new_body

    try:
        with open(fpath, "w", encoding="utf-8", newline="\n") as f:
            f.write(updated_text)
    except Exception as e:
        print(f"  [ERROR] Failed to write {fpath}: {e}")
        return brand_name, False

    return brand_name, True


# ── Main ─────────────────────────────────────────────────────────────────────

def collect_email_files(email_dir):
    """
    Recursively collect all .md files in the email archive directory.
    Prioritizes Gmail-Captures/ (actual email notes) over numbered attachment files.
    Skips README, database files, and common attachment patterns.
    """
    SKIP_NAMES = {"README.md", "PITCH_DATABASE.md"}
    SKIP_PATTERNS = re.compile(
        r'^(0\d{3}_(IMG_|image\d|Outlook|Screenshot|Invoice))',
        re.IGNORECASE,
    )
    SKIP_DIRS = {"attachments", "Amazon-Leads", "Brand-Pitches"}

    priority_files = []  # Gmail-Captures, Quick-Notes (actual emails)
    other_files = []     # numbered files in root

    for root, dirs, filenames in os.walk(email_dir):
        basename = os.path.basename(root)
        if basename in SKIP_DIRS:
            continue
        for fname in filenames:
            if not fname.endswith(".md") or fname.startswith("_"):
                continue
            if fname in SKIP_NAMES:
                continue
            if SKIP_PATTERNS.match(fname):
                continue

            fpath = os.path.join(root, fname)
            if basename in ("Gmail-Captures", "Quick-Notes"):
                priority_files.append(fpath)
            else:
                other_files.append(fpath)

    # Return Gmail-Captures first (most likely to have sender info), then others
    return sorted(priority_files) + sorted(other_files)


def main():
    parser = argparse.ArgumentParser(description="Enrich email notes with brand wikilinks")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing")
    parser.add_argument("--limit", type=int, default=0, help="Process only N files (0 = all)")
    args = parser.parse_args()

    print("=" * 70)
    print("  Email -> Brand Link Enricher")
    print("=" * 70)
    print(f"  Vault:     {VAULT}")
    print(f"  Brands:    {BRANDS_DIR}")
    print(f"  Emails:    {EMAIL_DIR}")
    print(f"  Dry run:   {args.dry_run}")
    print(f"  Limit:     {args.limit or 'none'}")
    print()

    # Step 1: Build domain map
    print("[1/3] Building domain -> brand mapping...")
    domain_map = build_domain_map()
    print(f"  Loaded {len(domain_map)} domain mappings")
    print()

    # Show domain map summary
    brand_names = sorted(set(domain_map.values()))
    print(f"  Unique brands: {len(brand_names)}")
    for bn in brand_names[:30]:
        domains = [d for d, b in domain_map.items() if b == bn]
        print(f"    {bn}: {', '.join(domains)}")
    if len(brand_names) > 30:
        print(f"    ... and {len(brand_names) - 30} more brands")
    print()

    # Step 2: Collect email files
    print("[2/3] Collecting email files...")
    email_files = collect_email_files(EMAIL_DIR)
    print(f"  Found {len(email_files)} .md files in email archive")
    if args.limit > 0:
        email_files = email_files[:args.limit]
        print(f"  Limited to first {args.limit} files")
    print()

    # Step 3: Process
    mode_label = "DRY RUN" if args.dry_run else "WRITING"
    print(f"[3/3] Processing email files ({mode_label})...")
    print()

    stats = {
        "scanned": 0,
        "matched": 0,
        "updated": 0,
        "already_linked": 0,
        "no_sender": 0,
        "no_match": 0,
    }
    brand_counts = {}
    updated_files = []

    for fpath in email_files:
        stats["scanned"] += 1
        brand_name, was_updated = process_email_file(fpath, domain_map, dry_run=args.dry_run)

        if brand_name is None:
            # Check if it was no-sender or no-match
            try:
                with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                    text = f.read()
                fm, body, _ = parse_frontmatter(text)
                d = get_sender_domain(fm, body)
                if d is None:
                    stats["no_sender"] += 1
                else:
                    stats["no_match"] += 1
            except Exception:
                stats["no_sender"] += 1
        elif was_updated:
            stats["updated"] += 1
            stats["matched"] += 1
            brand_counts[brand_name] = brand_counts.get(brand_name, 0) + 1
            rel = os.path.relpath(fpath, VAULT)
            updated_files.append((rel, brand_name))
        else:
            stats["already_linked"] += 1
            stats["matched"] += 1

    # Report
    print("-" * 70)
    print("  RESULTS")
    print("-" * 70)
    print(f"  Files scanned:        {stats['scanned']}")
    print(f"  Sender matched brand: {stats['matched']}")
    print(f"  Files updated:        {stats['updated']}")
    print(f"  Already linked:       {stats['already_linked']}")
    print(f"  No sender found:      {stats['no_sender']}")
    print(f"  Sender, no brand:     {stats['no_match']}")
    print()

    if brand_counts:
        print("  Brand link counts:")
        for bn, count in sorted(brand_counts.items(), key=lambda x: -x[1]):
            print(f"    {bn}: {count} files")
        print()

    if updated_files:
        print(f"  {'Would update' if args.dry_run else 'Updated'} files:")
        for rel, bn in updated_files[:50]:
            print(f"    [{bn}] {rel}")
        if len(updated_files) > 50:
            print(f"    ... and {len(updated_files) - 50} more")
        print()

    if args.dry_run:
        print("  ** DRY RUN -- no files were modified **")
    else:
        print(f"  Done. {stats['updated']} files enriched with brand links.")
    print()


if __name__ == "__main__":
    main()
