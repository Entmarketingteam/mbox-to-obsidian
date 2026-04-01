"""
Keepa Brand Scout — Find high-performing Amazon brands for proactive outreach.

Instead of waiting for Amazon sellers to spam Nicki, this tool uses the Keepa
API to discover brands that are *already selling well* on Amazon in categories
relevant to our talent (fashion, beauty, wellness, activewear, dupes) and
cross-references them against the vault's existing brand contacts to surface
net-new outreach opportunities.

Key features:
  - Pulls product/brand data from Keepa API by Amazon category
  - Filters for high BSR (Best Seller Rank), strong reviews, active sellers
  - Identifies "dupe" brands (Lululemon dupes, designer dupes, etc.)
  - Cross-references against vault contacts to skip brands we already know
  - Extracts Amazon storefront URLs + seller contact info where available
  - Generates outreach lead sheets (CSV) for the agency team

Setup:
  1. Get a Keepa API key at https://keepa.com/#!api
  2. Set it as an environment variable:
       export KEEPA_API_KEY="your-key-here"
     Or pass it via --api-key flag

Usage:
    python keepa_brand_scout.py                              # scan default categories
    python keepa_brand_scout.py --category fashion           # specific category
    python keepa_brand_scout.py --search "lululemon dupe"    # keyword search
    python keepa_brand_scout.py --output leads.csv           # export CSV
    python keepa_brand_scout.py --top 50                     # top 50 results
    python keepa_brand_scout.py --dry-run                    # preview API calls
"""

# ── Windows UTF-8 fix ────────────────────────────────────────────────────────
import sys
import io
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import os
import re
import csv
import json
import time
import argparse
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path


# ── Config ───────────────────────────────────────────────────────────────────

_HOME = os.path.expanduser("~")
VAULT = os.path.join(_HOME, "Documents", "ENT-Agency-Vault")
BRANDS_DIR = os.path.join(VAULT, "01-Brands-Contacts")
EMAIL_DIR = os.path.join(VAULT, "09-Email-Archive")

KEEPA_API_BASE = "https://api.keepa.com"

# ── Amazon Category IDs (US marketplace = domainId 1) ────────────────────────
# These are the root category node IDs on Amazon relevant to Nicki's niche.
# Full tree: https://keepa.com/#!categorytree

CATEGORY_PRESETS = {
    "fashion": {
        "name": "Women's Fashion",
        "category_ids": [
            7141123011,   # Women's Clothing
            7147440011,   # Women's Activewear
            679255011,    # Women's Athletic Clothing
            2368343011,   # Women's Fashion Hoodies & Sweatshirts
        ],
        "keywords": ["women", "fashion", "outfit", "activewear", "athleisure"],
    },
    "activewear": {
        "name": "Activewear & Athleisure (Lulu dupes)",
        "category_ids": [
            7147440011,   # Women's Activewear
            679255011,    # Women's Athletic Clothing
            2371776011,   # Women's Yoga Clothing
        ],
        "keywords": ["legging", "sports bra", "yoga", "athletic", "workout"],
    },
    "beauty": {
        "name": "Beauty & Skincare",
        "category_ids": [
            11060451,     # Skin Care
            11058281,     # Makeup
            11057241,     # Hair Care
        ],
        "keywords": ["skincare", "serum", "moisturizer", "makeup", "beauty"],
    },
    "wellness": {
        "name": "Health & Wellness Supplements",
        "category_ids": [
            3764441,      # Vitamins & Dietary Supplements
            6973663011,   # Collagen Supplements
            3774461,      # Protein Supplements
        ],
        "keywords": ["supplement", "vitamin", "collagen", "protein", "wellness"],
    },
    "accessories": {
        "name": "Women's Accessories & Jewelry",
        "category_ids": [
            7192394011,   # Women's Accessories
            7454901011,   # Women's Jewelry
        ],
        "keywords": ["jewelry", "necklace", "earring", "bag", "accessories"],
    },
    "home": {
        "name": "Home & Kitchen (lifestyle adjacent)",
        "category_ids": [
            1055398,      # Home & Kitchen
            510106,       # Kitchen & Dining
        ],
        "keywords": ["home", "kitchen", "organizer", "decor"],
    },
}

# Keywords that signal "dupe" or budget-friendly trending products
DUPE_KEYWORDS = [
    "dupe", "inspired", "lookalike", "similar to", "alternative",
    "affordable", "budget", "viral", "tiktok", "trending",
    "lululemon", "skims", "free people", "alo yoga", "gymshark",
    "designer inspired", "luxury look", "high quality",
]

DUPE_RE = re.compile("|".join(re.escape(k) for k in DUPE_KEYWORDS), re.IGNORECASE)


# ── Vault Cross-Reference ───────────────────────────────────────────────────

def load_known_brands():
    """
    Load all brand names and domains already in the vault.
    Returns (set of brand names lowercase, set of domains).
    """
    known_names = set()
    known_domains = set()

    # From brand profiles
    if os.path.isdir(BRANDS_DIR):
        for fname in os.listdir(BRANDS_DIR):
            if not fname.endswith(".md") or fname.startswith("_"):
                continue
            stem = Path(fname).stem.lower()
            known_names.add(stem)

            fpath = os.path.join(BRANDS_DIR, fname)
            try:
                with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                    text = f.read(4000)  # frontmatter is in the first few KB
            except Exception:
                continue

            # Extract domain from frontmatter
            domain_match = re.search(r'^domain:\s*(.+)$', text, re.MULTILINE)
            if domain_match:
                known_domains.add(domain_match.group(1).strip().strip('"').lower())

            # Extract company name
            company_match = re.search(r'^company:\s*(.+)$', text, re.MULTILINE)
            if company_match:
                known_names.add(company_match.group(1).strip().strip('"').lower())

    # From email enrichment hardcoded domains
    try:
        from enrich_email_links import HARDCODED_DOMAINS
        for domain, brand in HARDCODED_DOMAINS.items():
            known_domains.add(domain.lower())
            known_names.add(brand.lower())
    except ImportError:
        pass

    # Also check for Amazon-specific contacts from spam filter results
    amazon_leads_dir = os.path.join(EMAIL_DIR, "Amazon-Leads")
    if os.path.isdir(amazon_leads_dir):
        for fname in os.listdir(amazon_leads_dir):
            if fname.endswith(".md"):
                known_names.add(Path(fname).stem.lower())

    return known_names, known_domains


def load_known_sender_emails():
    """
    Scan email archive to build a set of sender emails we've already
    received mail from (i.e., brands that have already reached out).
    """
    known_senders = set()

    if not os.path.isdir(EMAIL_DIR):
        return known_senders

    for root, dirs, filenames in os.walk(EMAIL_DIR):
        if os.path.basename(root) == "attachments":
            continue
        for fname in filenames:
            if not fname.endswith(".md"):
                continue
            fpath = os.path.join(root, fname)
            try:
                with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                    head = f.read(1500)
                match = re.search(r'^sender_email:\s*"?([^"\n]+)', head, re.MULTILINE)
                if match:
                    known_senders.add(match.group(1).strip().lower())
            except Exception:
                continue

    return known_senders


# ── Keepa API Client ────────────────────────────────────────────────────────

def keepa_request(endpoint, params, api_key):
    """Make a request to the Keepa API. Returns parsed JSON."""
    params["key"] = api_key
    url = f"{KEEPA_API_BASE}/{endpoint}?" + urllib.parse.urlencode(params)

    req = urllib.request.Request(url)
    req.add_header("User-Agent", "ENT-Agency-BrandScout/1.0")

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            # Check token status
            tokens_left = data.get("tokensLeft", 0)
            if tokens_left < 10:
                print(f"  [WARN] Low API tokens remaining: {tokens_left}")
            return data
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Keepa API error {e.code}: {body}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Keepa API connection error: {e.reason}")


def keepa_best_sellers(category_id, api_key, domain_id=1):
    """
    Get best sellers for an Amazon category.
    domain_id 1 = Amazon.com (US)
    Returns list of ASINs.
    """
    data = keepa_request("bestsellers", {
        "domain": domain_id,
        "category": category_id,
    }, api_key)
    return data.get("bestSellersList", {}).get("asinList", [])


def keepa_product_search(search_term, api_key, domain_id=1, sort=None,
                         category_id=None, page=0):
    """
    Search for products via Keepa product finder.
    Returns product data list.
    """
    params = {
        "domain": domain_id,
        "page": page,
    }
    if search_term:
        params["title"] = search_term
    if category_id:
        params["rootCategory"] = category_id
    if sort:
        params["sort"] = json.dumps(sort)

    # Product finder uses POST-style params
    data = keepa_request("search", params, api_key)
    return data.get("asinList", [])


def keepa_product_details(asins, api_key, domain_id=1):
    """
    Get detailed product info for a list of ASINs (max 100 per call).
    Returns list of product objects.
    """
    if not asins:
        return []

    # Keepa accepts comma-separated ASINs
    asin_str = ",".join(asins[:100])
    data = keepa_request("product", {
        "domain": domain_id,
        "asin": asin_str,
        "stats": 180,       # 180-day stats
        "brand": 1,         # include brand info
        "buybox": 1,        # include buy box info
        "offers": 20,       # include top offers
    }, api_key)
    return data.get("products", [])


def keepa_category_tree(api_key, domain_id=1, parent=0):
    """Get the category tree from Keepa."""
    data = keepa_request("category", {
        "domain": domain_id,
        "category": parent,
        "parents": 1,
    }, api_key)
    return data.get("categories", {})


# ── Product Analysis ─────────────────────────────────────────────────────────

def analyze_product(product, known_brands, known_domains):
    """
    Analyze a Keepa product record and return a lead dict (or None to skip).
    """
    title = product.get("title", "") or ""
    brand = product.get("brand", "") or ""
    asin = product.get("asin", "") or ""
    manufacturer = product.get("manufacturer", "") or ""
    root_category = product.get("rootCategory", 0)

    if not asin or not title:
        return None

    # Stats
    stats = product.get("stats", {}) or {}
    current_sales_rank = stats.get("current", [None] * 20)

    # Sales rank (lower = better selling)
    # Index 3 = Amazon sales rank
    sales_rank = None
    if isinstance(current_sales_rank, list) and len(current_sales_rank) > 3:
        sales_rank = current_sales_rank[3]
    if sales_rank and sales_rank < 0:
        sales_rank = None

    # Review count and rating
    review_count = 0
    rating = 0
    csv_data = product.get("csv", [])
    if csv_data and len(csv_data) > 16:
        # Index 16 = review count history, 17 = rating history
        reviews_hist = csv_data[16] if csv_data[16] else []
        rating_hist = csv_data[17] if csv_data[17] else []
        if reviews_hist and len(reviews_hist) >= 2:
            review_count = reviews_hist[-1] if reviews_hist[-1] else 0
        if rating_hist and len(rating_hist) >= 2:
            rating = (rating_hist[-1] or 0) / 10  # Keepa stores as rating * 10

    # Amazon product URL
    product_url = f"https://www.amazon.com/dp/{asin}"

    # Brand/seller storefront URL (if available)
    seller_info = ""
    brand_url = ""
    if brand:
        brand_slug = urllib.parse.quote(brand)
        brand_url = f"https://www.amazon.com/s?k={brand_slug}"

    # FBA status
    is_fba = product.get("fbaFees") is not None

    # Check for dupe/trending signals in title
    is_dupe = bool(DUPE_RE.search(title))
    dupe_matches = DUPE_RE.findall(title)

    # Check if we already know this brand
    brand_lower = brand.lower() if brand else ""
    already_known = (
        brand_lower in known_brands
        or any(brand_lower in kb for kb in known_brands if len(kb) > 3)
    )

    # Seller/brand domain (if we can find it)
    seller_domain = ""
    # Sometimes manufacturer URL hints at brand domain
    if manufacturer and "." in manufacturer:
        seller_domain = manufacturer.lower()

    return {
        "asin": asin,
        "title": title[:120],
        "brand": brand,
        "manufacturer": manufacturer,
        "sales_rank": sales_rank,
        "review_count": review_count,
        "rating": rating,
        "product_url": product_url,
        "brand_search_url": brand_url,
        "is_fba": is_fba,
        "is_dupe": is_dupe,
        "dupe_keywords": dupe_matches,
        "already_known": already_known,
        "seller_domain": seller_domain,
        "root_category": root_category,
    }


def score_lead(lead):
    """
    Score a lead for outreach priority.
    Higher = more valuable as an outreach target.
    """
    score = 0

    # Strong sales rank is good (brand has money to spend)
    if lead["sales_rank"]:
        if lead["sales_rank"] < 1000:
            score += 5
        elif lead["sales_rank"] < 5000:
            score += 4
        elif lead["sales_rank"] < 20000:
            score += 3
        elif lead["sales_rank"] < 100000:
            score += 2
        else:
            score += 1

    # Good reviews = established product
    if lead["review_count"] > 5000:
        score += 4
    elif lead["review_count"] > 1000:
        score += 3
    elif lead["review_count"] > 200:
        score += 2
    elif lead["review_count"] > 50:
        score += 1

    # High rating
    if lead["rating"] >= 4.5:
        score += 2
    elif lead["rating"] >= 4.0:
        score += 1

    # Dupe/trending products are especially relevant
    if lead["is_dupe"]:
        score += 3

    # FBA sellers are more likely to have budget
    if lead["is_fba"]:
        score += 1

    # Penalize brands we already know (we want net-new leads)
    if lead["already_known"]:
        score -= 5

    return score


# ── Search Strategies ────────────────────────────────────────────────────────

def scout_category(category_key, api_key, known_brands, known_domains, top_n=50):
    """
    Scout a category for high-performing brands.
    Returns scored lead list.
    """
    preset = CATEGORY_PRESETS.get(category_key)
    if not preset:
        print(f"  [ERROR] Unknown category: {category_key}")
        print(f"  Available: {', '.join(CATEGORY_PRESETS.keys())}")
        return []

    print(f"  Scouting: {preset['name']}")
    leads = []
    seen_asins = set()
    seen_brands = set()

    for cat_id in preset["category_ids"]:
        print(f"    Category {cat_id}...")
        try:
            asins = keepa_best_sellers(cat_id, api_key)
            if not asins:
                print(f"    No best sellers found")
                continue
            print(f"    Found {len(asins)} best sellers")

            # Get details in batches of 100
            for batch_start in range(0, min(len(asins), 200), 100):
                batch = [a for a in asins[batch_start:batch_start + 100]
                         if a not in seen_asins]
                if not batch:
                    continue

                products = keepa_product_details(batch, api_key)
                time.sleep(1)  # Rate limit courtesy

                for prod in products:
                    lead = analyze_product(prod, known_brands, known_domains)
                    if not lead:
                        continue
                    seen_asins.add(lead["asin"])

                    # Dedupe by brand (keep best-ranked product per brand)
                    brand_key = lead["brand"].lower() if lead["brand"] else lead["asin"]
                    if brand_key in seen_brands:
                        continue
                    seen_brands.add(brand_key)

                    lead["score"] = score_lead(lead)
                    lead["source_category"] = preset["name"]
                    leads.append(lead)

        except RuntimeError as e:
            print(f"    [ERROR] {e}")
            continue

    # Sort by score descending
    leads.sort(key=lambda x: -x["score"])
    return leads[:top_n]


def scout_keyword(search_term, api_key, known_brands, known_domains,
                  category_key=None, top_n=50):
    """
    Search for products by keyword (e.g., "lululemon dupe").
    Returns scored lead list.
    """
    print(f"  Searching: \"{search_term}\"")

    category_id = None
    if category_key and category_key in CATEGORY_PRESETS:
        category_id = CATEGORY_PRESETS[category_key]["category_ids"][0]

    leads = []
    seen_brands = set()

    try:
        asins = keepa_product_search(search_term, api_key,
                                     category_id=category_id)
        if not asins:
            print(f"  No products found")
            return []

        print(f"  Found {len(asins)} products")

        for batch_start in range(0, min(len(asins), 200), 100):
            batch = asins[batch_start:batch_start + 100]
            products = keepa_product_details(batch, api_key)
            time.sleep(1)

            for prod in products:
                lead = analyze_product(prod, known_brands, known_domains)
                if not lead:
                    continue

                brand_key = lead["brand"].lower() if lead["brand"] else lead["asin"]
                if brand_key in seen_brands:
                    continue
                seen_brands.add(brand_key)

                lead["score"] = score_lead(lead)
                lead["source_category"] = f"Search: {search_term}"
                leads.append(lead)

    except RuntimeError as e:
        print(f"  [ERROR] {e}")

    leads.sort(key=lambda x: -x["score"])
    return leads[:top_n]


# ── Output ───────────────────────────────────────────────────────────────────

def print_leads_report(leads, show_known=False):
    """Print a formatted report of scouted leads."""
    if not leads:
        print("\n  No leads found.")
        return

    # Split into new vs already-known
    new_leads = [l for l in leads if not l["already_known"]]
    known_leads = [l for l in leads if l["already_known"]]

    print()
    print("=" * 90)
    print("  KEEPA BRAND SCOUT REPORT")
    print("=" * 90)
    print(f"  Total brands analyzed: {len(leads)}")
    print(f"  Net-new brands:       {len(new_leads)}")
    print(f"  Already known:        {len(known_leads)}")
    print()

    if new_leads:
        print("-" * 90)
        print("  NEW OUTREACH TARGETS (not in vault)")
        print("-" * 90)
        print()
        print(f"  {'#':<4} {'Score':<6} {'Brand':<25} {'BSR':<10} "
              f"{'Reviews':<9} {'Rating':<7} {'Dupe?':<6}")
        print(f"  {'─'*4} {'─'*5} {'─'*25} {'─'*9} {'─'*8} {'─'*6} {'─'*5}")

        for i, lead in enumerate(new_leads, 1):
            bsr = f"#{lead['sales_rank']:,}" if lead['sales_rank'] else "N/A"
            reviews = f"{lead['review_count']:,}" if lead['review_count'] else "0"
            rating_str = f"{lead['rating']:.1f}" if lead['rating'] else "N/A"
            dupe_flag = "YES" if lead["is_dupe"] else ""

            print(f"  {i:<4} {lead['score']:<6} {lead['brand'][:25]:<25} "
                  f"{bsr:<10} {reviews:<9} {rating_str:<7} {dupe_flag:<6}")

        print()
        print("  Product links:")
        for i, lead in enumerate(new_leads[:30], 1):
            print(f"    {i}. {lead['brand'] or 'Unknown'}: {lead['product_url']}")
            if lead["brand_search_url"]:
                print(f"       All products: {lead['brand_search_url']}")
            if lead["is_dupe"]:
                print(f"       Dupe keywords: {', '.join(lead['dupe_keywords'])}")

    if show_known and known_leads:
        print()
        print("-" * 90)
        print("  ALREADY KNOWN BRANDS (in vault — skip or re-engage)")
        print("-" * 90)
        for i, lead in enumerate(known_leads, 1):
            bsr = f"#{lead['sales_rank']:,}" if lead['sales_rank'] else "N/A"
            print(f"    {i}. {lead['brand']} — BSR {bsr}, "
                  f"{lead['review_count']:,} reviews")

    print()


def export_leads_csv(leads, output_path):
    """Export leads to CSV for agency outreach."""
    rows = []
    for lead in leads:
        rows.append({
            "brand": lead["brand"],
            "product_title": lead["title"],
            "asin": lead["asin"],
            "score": lead["score"],
            "sales_rank": lead["sales_rank"] or "",
            "review_count": lead["review_count"],
            "rating": lead["rating"],
            "is_dupe": "YES" if lead["is_dupe"] else "",
            "dupe_keywords": ", ".join(lead.get("dupe_keywords", [])),
            "already_known": "YES" if lead["already_known"] else "",
            "product_url": lead["product_url"],
            "brand_search_url": lead["brand_search_url"],
            "source_category": lead.get("source_category", ""),
            "manufacturer": lead["manufacturer"],
        })

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "brand", "product_title", "asin", "score", "sales_rank",
            "review_count", "rating", "is_dupe", "dupe_keywords",
            "already_known", "product_url", "brand_search_url",
            "source_category", "manufacturer",
        ])
        writer.writeheader()
        writer.writerows(rows)

    new_count = sum(1 for l in leads if not l["already_known"])
    print(f"  Exported {len(rows)} leads ({new_count} net-new) to: {output_path}")


def export_leads_json(leads, output_path):
    """Export leads to JSON."""
    output = {
        "generated": datetime.now().isoformat(),
        "total_leads": len(leads),
        "new_leads": sum(1 for l in leads if not l["already_known"]),
        "leads": leads,
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"  Exported to: {output_path}")


# ── Dupe-Specific Searches ──────────────────────────────────────────────────

# Pre-built keyword searches for common dupe categories
DUPE_SEARCHES = [
    "lululemon dupe leggings",
    "lululemon align dupe",
    "skims dupe bodysuit",
    "free people dupe",
    "alo yoga dupe",
    "gymshark dupe",
    "designer inspired jewelry",
    "viral tiktok fashion",
    "amazon fashion finds",
    "affordable activewear women",
]


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Scout Amazon brands via Keepa for proactive outreach"
    )
    parser.add_argument("--api-key", type=str, default=None,
                        help="Keepa API key (or set KEEPA_API_KEY env var)")
    parser.add_argument("--category", type=str, default=None,
                        choices=list(CATEGORY_PRESETS.keys()),
                        help="Scout a specific category")
    parser.add_argument("--all-categories", action="store_true",
                        help="Scout all preset categories")
    parser.add_argument("--search", type=str, default=None,
                        help="Search for products by keyword")
    parser.add_argument("--dupes", action="store_true",
                        help="Run all pre-built dupe keyword searches")
    parser.add_argument("--top", type=int, default=50,
                        help="Number of top results per category (default: 50)")
    parser.add_argument("--output", type=str, default=None,
                        help="Export leads to CSV")
    parser.add_argument("--output-json", type=str, default=None,
                        help="Export leads to JSON")
    parser.add_argument("--show-known", action="store_true",
                        help="Include already-known brands in output")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be searched without calling API")
    args = parser.parse_args()

    # Resolve API key
    api_key = args.api_key or os.environ.get("KEEPA_API_KEY", "")
    if not api_key and not args.dry_run:
        print("\n  ERROR: No Keepa API key provided.")
        print("  Set KEEPA_API_KEY env var or pass --api-key")
        print("  Get a key at: https://keepa.com/#!api")
        print("  (Use --dry-run to preview without API calls)")
        sys.exit(1)

    print()
    print("=" * 80)
    print("  Keepa Brand Scout — Amazon Brand Discovery for Agency Outreach")
    print("=" * 80)

    # Load vault cross-reference data
    print("\n  Loading vault brand data...")
    known_brands, known_domains = load_known_brands()
    print(f"  Known brands: {len(known_brands)}")
    print(f"  Known domains: {len(known_domains)}")

    # Determine what to scan
    searches_planned = []

    if args.search:
        searches_planned.append(("keyword", args.search, None))
    elif args.dupes:
        for kw in DUPE_SEARCHES:
            searches_planned.append(("keyword", kw, "fashion"))
    elif args.category:
        searches_planned.append(("category", args.category, None))
    elif args.all_categories:
        for cat_key in CATEGORY_PRESETS:
            searches_planned.append(("category", cat_key, None))
    else:
        # Default: scan fashion + activewear + beauty (highest ROI categories)
        for cat_key in ["fashion", "activewear", "beauty"]:
            searches_planned.append(("category", cat_key, None))

    print(f"\n  Planned searches: {len(searches_planned)}")
    for stype, sval, scat in searches_planned:
        if stype == "category":
            preset = CATEGORY_PRESETS[sval]
            print(f"    Category: {preset['name']} ({len(preset['category_ids'])} sub-categories)")
        else:
            print(f"    Keyword: \"{sval}\"" + (f" in {scat}" if scat else ""))

    if args.dry_run:
        print("\n  DRY RUN — no API calls made.")
        print("  Set KEEPA_API_KEY and remove --dry-run to execute.")
        return

    # Execute searches
    all_leads = []
    seen_brands_global = set()

    print()
    for stype, sval, scat in searches_planned:
        if stype == "category":
            leads = scout_category(sval, api_key, known_brands, known_domains,
                                   top_n=args.top)
        else:
            leads = scout_keyword(sval, api_key, known_brands, known_domains,
                                  category_key=scat, top_n=args.top)

        # Dedupe across searches
        for lead in leads:
            brand_key = lead["brand"].lower() if lead["brand"] else lead["asin"]
            if brand_key not in seen_brands_global:
                seen_brands_global.add(brand_key)
                all_leads.append(lead)

        time.sleep(1)  # Rate limit between categories

    # Re-sort all leads
    all_leads.sort(key=lambda x: -x["score"])

    # Report
    print_leads_report(all_leads, show_known=args.show_known)

    # Export
    if args.output:
        export_leads_csv(all_leads, args.output)

    if args.output_json:
        export_leads_json(all_leads, args.output_json)

    # Summary
    new_count = sum(1 for l in all_leads if not l["already_known"])
    dupe_count = sum(1 for l in all_leads if l["is_dupe"])

    print("-" * 80)
    print(f"  SUMMARY")
    print(f"  Total brands scouted:    {len(all_leads)}")
    print(f"  Net-new for outreach:    {new_count}")
    print(f"  Dupe/trending products:  {dupe_count}")
    print(f"  Already in vault:        {len(all_leads) - new_count}")
    print("-" * 80)
    print()


if __name__ == "__main__":
    main()
