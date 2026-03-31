"""
Clean attachment stub .md files from 09-Email-Archive to reduce Obsidian graph noise.

Identifies .md files that are attachment stubs (binary content dumped into markdown)
and moves them to 09-Email-Archive/attachment-stubs/ folder.

Criteria for attachment stubs:
1. File content is less than 200 bytes
2. File contains binary content (PNG, PDF, JPEG signatures at start of body)
3. File content is only frontmatter with no meaningful body
4. Filename matches attachment patterns AND body is very short

Run with --restore first to undo previous run, then --clean to re-run.
"""

import os
import re
import sys
import shutil
from pathlib import Path
from collections import defaultdict

VAULT_DIR = Path(r"C:\Users\ejatc\Documents\ENT-Agency-Vault")
ARCHIVE_DIR = VAULT_DIR / "09-Email-Archive"
STUBS_DIR = ARCHIVE_DIR / "attachment-stubs"
GMAIL_DIR = ARCHIVE_DIR / "Gmail-Captures"

# Filename patterns that indicate attachment stubs
ATTACHMENT_FILENAME_PATTERNS = [
    r'IMG_\d+',
    r'image\d*',
    r'Outlook-',
    r'Screenshot',
    r'attachment[-_]',
    r'\.HEIC$',
    r'\.JPG$',
    r'\.PNG$',
    r'\.jpeg$',
    r'\.gif$',
    r'\.mov$',
    r'\.MOV$',
    r'\.pdf$',
]

# Binary signatures that MUST appear at the very start of body content.
# These are actual file magic bytes for binary formats.
BINARY_START_SIGNATURES = [
    b'\x89PNG',          # PNG magic bytes
    b'%PDF',             # PDF magic bytes
    b'\xff\xd8\xff',     # JPEG magic bytes
    b'GIF87a',           # GIF87
    b'GIF89a',           # GIF89
    b'RIFF',             # AVI/WEBP
    b'PK\x03\x04',      # ZIP/DOCX/XLSX
]

# Text-based indicators of binary content dumped as text.
# Strong indicators are specific enough that one match suffices.
# Weak indicators need 2+ matches together.
BINARY_TEXT_INDICATORS_STRONG = [
    'IHDR',             # PNG chunk identifier
    'IDATx',            # PNG data chunk
    '/FlateDecode',     # PDF compression filter
    'JFIF',             # JPEG APP0 marker - very specific to JPEG files
]

BINARY_TEXT_INDICATORS_WEAK = [
    'endobj',           # PDF object end
    'endstream',        # PDF stream end
    'iCCProfile',       # ICC color profile
    '/ColorSpace',      # PDF color
    '/Subtype /Image',  # PDF image marker
]


def has_attachment_filename(filename):
    """Check if filename matches common attachment patterns."""
    basename = os.path.splitext(filename)[0]
    # Remove numeric prefix like "0006_"
    name_part = re.sub(r'^\d+_', '', basename)

    for pattern in ATTACHMENT_FILENAME_PATTERNS:
        if re.search(pattern, name_part, re.IGNORECASE):
            return True
    return False


def get_body_after_frontmatter(content_bytes):
    """Extract body text after YAML frontmatter, returns (frontmatter, body) as strings."""
    try:
        text = content_bytes.decode('utf-8', errors='replace')
    except Exception:
        return '', ''

    # Check for frontmatter
    if text.startswith('---'):
        # Find end of frontmatter
        end_idx = text.find('---', 3)
        if end_idx != -1:
            frontmatter = text[:end_idx + 3]
            body = text[end_idx + 3:]
            return frontmatter, body

    return '', text


def get_body_content_bytes(content_bytes):
    """Get the actual content bytes after frontmatter, heading, and horizontal rules.
    Returns decoded-then-reencoded bytes (for text analysis)."""
    frontmatter, body = get_body_after_frontmatter(content_bytes)
    if not frontmatter:
        return content_bytes, False

    body_bytes = content_bytes[len(frontmatter.encode('utf-8', errors='replace')):]
    body_bytes_stripped = body_bytes.lstrip()

    try:
        body_text = body_bytes_stripped.decode('utf-8', errors='replace')
        lines = body_text.split('\n')
        content_start = 0
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith('#') or stripped == '---' or stripped == '':
                content_start = i + 1
                continue
            break

        if content_start < len(lines):
            remaining = '\n'.join(lines[content_start:])
            remaining_bytes = remaining.encode('utf-8', errors='replace')
        else:
            remaining_bytes = b''
    except Exception:
        remaining_bytes = body_bytes_stripped

    return remaining_bytes, True


def get_raw_body_bytes(content_bytes):
    """Get raw body bytes after frontmatter/heading, WITHOUT decode/reencode.
    This preserves original binary signatures for detection."""
    # Find end of frontmatter in raw bytes
    if not content_bytes.startswith(b'---'):
        return content_bytes, False

    # Find second --- in raw bytes
    idx = content_bytes.find(b'---', 3)
    if idx == -1:
        return content_bytes, False

    body_start = idx + 3
    body = content_bytes[body_start:]

    # Skip past heading line and horizontal rules in raw bytes
    # Look for lines starting with # or --- or empty, working byte by byte
    pos = 0
    while pos < len(body):
        # Skip whitespace/newlines
        while pos < len(body) and body[pos:pos+1] in (b'\r', b'\n', b' ', b'\t'):
            pos += 1
        if pos >= len(body):
            break

        # Check if this line is a heading or rule
        line_start = pos
        line_end = body.find(b'\n', pos)
        if line_end == -1:
            line_end = len(body)

        line = body[line_start:line_end].strip()
        if line.startswith(b'#') or line == b'---' or line == b'':
            pos = line_end + 1
            continue
        else:
            # This is the start of actual content
            break

    return body[pos:], True


def is_frontmatter_only(content_bytes):
    """Check if file is just frontmatter with no meaningful body."""
    remaining_bytes, has_fm = get_body_content_bytes(content_bytes)
    if not has_fm:
        return False

    # If what remains is very short (less than 20 chars of actual text), it's a stub
    return len(remaining_bytes.strip()) < 20


def has_binary_content(content_bytes):
    """Check if the file body contains binary data (images/PDFs dumped as markdown).

    Uses strict checks to avoid false positives:
    - Binary magic bytes checked in RAW bytes (not decode/re-encoded)
    - Text-based indicators for binary formats
    - Exif header detection for JPEG files whose magic bytes got corrupted
    - High non-printable byte ratio in raw bytes
    """
    # Use RAW bytes for binary signature detection (preserves original magic bytes)
    raw_bytes, has_fm = get_raw_body_bytes(content_bytes)
    if not has_fm or len(raw_bytes) < 10:
        return False

    # Check 1: Binary magic bytes in the first 100 raw bytes
    # Raw bytes preserve the original file signatures without UTF-8 corruption
    raw_head = raw_bytes[:100]
    for sig in BINARY_START_SIGNATURES:
        if sig in raw_head:
            return True

    # Check 2: Exif header detection (JPEG files whose \xff\xd8\xff got corrupted)
    if b'Exif' in raw_bytes[:200]:
        return True

    # Check 3: Text-based binary indicators (works on decoded text)
    remaining_bytes, _ = get_body_content_bytes(content_bytes)
    if len(remaining_bytes) < 10:
        return False

    try:
        remaining_text = remaining_bytes[:5000].decode('utf-8', errors='replace')

        strong_count = sum(1 for ind in BINARY_TEXT_INDICATORS_STRONG if ind in remaining_text)
        weak_count = sum(1 for ind in BINARY_TEXT_INDICATORS_WEAK if ind in remaining_text)

        # One strong indicator is enough (IHDR, IDATx, /FlateDecode, JFIF are specific)
        if strong_count >= 1:
            return True
        # Need 2+ weak indicators together
        if weak_count >= 2:
            return True
    except Exception:
        pass

    # Check 4: High ratio of non-printable characters in RAW bytes
    # Use raw bytes to get accurate count (decoded bytes inflate replacement chars)
    if len(raw_bytes) > 200:
        sample = raw_bytes[:5000]
        non_printable = sum(1 for b in sample if b < 32 and b not in (9, 10, 13))
        ratio = non_printable / len(sample)
        if ratio > 0.08:  # 8% threshold on raw bytes is safe
            return True

    return False


def is_attachment_stub(filepath):
    """Determine if a .md file is an attachment stub."""
    try:
        content = filepath.read_bytes()
    except (PermissionError, OSError):
        return False, "read_error"

    file_size = len(content)

    # Check 1: File size < 200 bytes
    if file_size < 200:
        return True, "tiny_file"

    # Check 2: Contains binary content (PNG/PDF/JPEG data in body)
    if has_binary_content(content):
        return True, "binary_content"

    # Check 3: Frontmatter only with no meaningful body
    if is_frontmatter_only(content):
        return True, "frontmatter_only"

    # Check 4: Filename pattern match + content is not a real email
    # Only flag filename matches if file doesn't have substantial text body
    if has_attachment_filename(filepath.name):
        frontmatter, body = get_body_after_frontmatter(content)
        if frontmatter:
            body_clean = re.sub(r'^#\s+.*$', '', body, flags=re.MULTILINE)
            body_clean = re.sub(r'^---+\s*$', '', body_clean, flags=re.MULTILINE)
            body_clean = body_clean.strip()
            if len(body_clean) < 100:
                return True, "attachment_filename_short_body"

    return False, "kept"


def restore_stubs():
    """Move all files from attachment-stubs/ back to their original locations."""
    if not STUBS_DIR.exists():
        print("No attachment-stubs/ directory found. Nothing to restore.")
        return 0

    restored = 0
    errors = 0

    for filepath in sorted(STUBS_DIR.rglob('*.md')):
        rel_path = filepath.relative_to(STUBS_DIR)
        dest_path = ARCHIVE_DIR / rel_path

        # Make sure parent exists
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        # Handle name collisions (shouldn't happen normally)
        if dest_path.exists():
            stem = dest_path.stem
            suffix = dest_path.suffix
            counter = 1
            while dest_path.exists():
                dest_path = dest_path.parent / f"{stem}_restored_{counter}{suffix}"
                counter += 1

        try:
            shutil.move(str(filepath), str(dest_path))
            restored += 1
        except (PermissionError, OSError) as e:
            errors += 1
            print(f"  ERROR restoring {filepath.name}: {e}")

    # Clean up empty directories in stubs
    for dirpath in sorted(STUBS_DIR.rglob('*'), reverse=True):
        if dirpath.is_dir():
            try:
                dirpath.rmdir()
            except OSError:
                pass
    try:
        STUBS_DIR.rmdir()
    except OSError:
        pass

    print(f"Restored {restored} files back to original locations ({errors} errors)")
    return restored


def analyze_gmail_captures():
    """Analyze Gmail-Captures folder to determine meaningful notes vs stubs."""
    stats = {
        'total': 0,
        'meaningful': 0,
        'stubs': defaultdict(int),
        'stub_files': [],
    }

    if not GMAIL_DIR.exists():
        return stats

    for filepath in sorted(GMAIL_DIR.rglob('*.md')):
        stats['total'] += 1
        is_stub, reason = is_attachment_stub(filepath)
        if is_stub:
            stats['stubs'][reason] += 1
            stats['stub_files'].append((filepath, reason))
        else:
            stats['meaningful'] += 1

    return stats


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "--clean"

    if mode == "--restore":
        print("=" * 70)
        print("RESTORING: Moving stubs back to original locations")
        print("=" * 70)
        restore_stubs()
        return

    if mode == "--dry-run":
        dry_run = True
        print("DRY RUN MODE -- no files will be moved")
    else:
        dry_run = False

    print("=" * 70)
    print("OBSIDIAN ATTACHMENT STUB CLEANER (v2 - fixed binary detection)")
    print("=" * 70)
    print(f"\nScanning: {ARCHIVE_DIR}")
    print()

    # Create stubs directory
    if not dry_run:
        STUBS_DIR.mkdir(parents=True, exist_ok=True)
        print(f"Created/verified stub archive: {STUBS_DIR}")

    # --- Phase 1: Scan all .md files (excluding attachments/ and attachment-stubs/) ---

    total_scanned = 0
    stubs_found = 0
    stubs_moved = 0
    stubs_by_reason = defaultdict(int)
    kept_count = 0
    errors = 0
    moved_files = []

    skip_dirs = {
        ARCHIVE_DIR / "attachments",
        STUBS_DIR,
    }

    all_md_files = []
    for filepath in sorted(ARCHIVE_DIR.rglob('*.md')):
        skip = False
        for skip_dir in skip_dirs:
            try:
                filepath.relative_to(skip_dir)
                skip = True
                break
            except ValueError:
                continue
        if skip:
            continue
        all_md_files.append(filepath)

    print(f"Total .md files to scan (excluding attachments/, attachment-stubs/): {len(all_md_files)}")
    print()

    # Process files
    for filepath in all_md_files:
        total_scanned += 1

        is_stub, reason = is_attachment_stub(filepath)

        if reason == "read_error":
            errors += 1
            continue

        if is_stub:
            stubs_found += 1
            stubs_by_reason[reason] += 1

            if not dry_run:
                rel_path = filepath.relative_to(ARCHIVE_DIR)
                dest_path = STUBS_DIR / rel_path
                dest_path.parent.mkdir(parents=True, exist_ok=True)

                if dest_path.exists():
                    stem = dest_path.stem
                    suffix = dest_path.suffix
                    counter = 1
                    while dest_path.exists():
                        dest_path = dest_path.parent / f"{stem}_{counter}{suffix}"
                        counter += 1

                try:
                    shutil.move(str(filepath), str(dest_path))
                    stubs_moved += 1
                    moved_files.append((filepath, dest_path, reason))
                except (PermissionError, OSError) as e:
                    errors += 1
                    print(f"  ERROR moving {filepath.name}: {e}")
        else:
            kept_count += 1

    # --- Phase 2: Check attachments/ directory ---

    attachments_dir = ARCHIVE_DIR / "attachments"
    att_total = 0
    att_md = 0
    att_binary = 0
    att_extensions = defaultdict(int)

    if attachments_dir.exists():
        for filepath in attachments_dir.rglob('*'):
            if filepath.is_file():
                att_total += 1
                ext = filepath.suffix.lower()
                att_extensions[ext] += 1
                if ext == '.md':
                    att_md += 1
                else:
                    att_binary += 1

    # --- Phase 3: Analyze Gmail-Captures (BEFORE moving, uses current state) ---
    # Note: Gmail stubs were already moved in Phase 1 if --clean mode.
    # The analysis here shows what's LEFT in Gmail-Captures.
    print("Analyzing Gmail-Captures folder (post-cleanup)...")
    gmail_stats = analyze_gmail_captures()

    # --- REPORT ---

    print("\n" + "=" * 70)
    print("REPORT: ATTACHMENT STUB CLEANUP")
    print("=" * 70)

    action_word = "identified" if dry_run else "moved"

    print(f"\n{'SCAN SUMMARY':=^50}")
    print(f"  Total .md files scanned:      {total_scanned:,}")
    print(f"  Attachment stubs {action_word}:    {stubs_found:,}")
    print(f"  Meaningful notes kept:         {kept_count:,}")
    print(f"  Read errors:                   {errors:,}")

    print(f"\n{'STUBS BY REASON':=^50}")
    for reason, count in sorted(stubs_by_reason.items(), key=lambda x: -x[1]):
        label = {
            'binary_content': 'Binary data in body (PNG/PDF/JPEG)',
            'tiny_file': 'File under 200 bytes',
            'frontmatter_only': 'Frontmatter only, no body',
            'attachment_filename_short_body': 'Attachment filename + short body',
        }.get(reason, reason)
        print(f"  {label:45s} {count:,}")

    if not dry_run:
        print(f"\n{'DESTINATION':=^50}")
        print(f"  Stubs archived to: {STUBS_DIR}")

    print(f"\n{'ATTACHMENTS/ DIRECTORY':=^50}")
    print(f"  Total files:                   {att_total:,}")
    print(f"  Binary files (not in graph):   {att_binary:,}")
    print(f"  Markdown files (in graph):     {att_md:,}")
    if att_extensions:
        print(f"  Top extensions:")
        for ext, count in sorted(att_extensions.items(), key=lambda x: -x[1])[:10]:
            ext_display = ext if ext else '(no extension)'
            print(f"    {ext_display:20s} {count:,}")
    print(f"\n  NOTE: Binary files (.png, .pdf, .jpg, etc.) in attachments/ do NOT")
    print(f"  appear as nodes in the Obsidian graph. Only .md files create graph nodes.")
    if att_md == 0:
        print(f"  Result: attachments/ adds ZERO graph noise. No action needed.")

    print(f"\n{'GMAIL-CAPTURES (post-cleanup)':=^50}")
    print(f"  Total .md files remaining:     {gmail_stats['total']:,}")
    print(f"  Meaningful email notes:        {gmail_stats['meaningful']:,}")
    print(f"  Remaining stubs:               {sum(gmail_stats['stubs'].values()):,}")
    if gmail_stats['stubs']:
        for reason, count in sorted(gmail_stats['stubs'].items(), key=lambda x: -x[1]):
            label = {
                'binary_content': 'Binary data in body',
                'tiny_file': 'File under 200 bytes',
                'frontmatter_only': 'Frontmatter only',
                'attachment_filename_short_body': 'Attachment filename + short body',
            }.get(reason, reason)
            print(f"    {label:43s} {count:,}")

    meaningful_pct = (gmail_stats['meaningful'] / gmail_stats['total'] * 100) if gmail_stats['total'] > 0 else 0
    print(f"\n  Gmail-Captures quality: {meaningful_pct:.1f}% meaningful email notes")

    # Location breakdown
    print(f"\n{'STUBS BY SOURCE LOCATION':=^50}")
    location_counts = defaultdict(int)
    for src, dst, reason in moved_files:
        rel = src.relative_to(ARCHIVE_DIR)
        parts = rel.parts
        if len(parts) > 1:
            location_counts[parts[0]] += 1
        else:
            location_counts["(top-level)"] += 1

    # In dry-run, count from stubs_by_reason per location
    if dry_run:
        # Re-scan to get location info
        for filepath in all_md_files:
            is_stub, reason = is_attachment_stub(filepath)
            if is_stub:
                rel = filepath.relative_to(ARCHIVE_DIR)
                parts = rel.parts
                if len(parts) > 1:
                    location_counts[parts[0]] += 1
                else:
                    location_counts["(top-level)"] += 1

    for loc, count in sorted(location_counts.items(), key=lambda x: -x[1]):
        print(f"  {loc:40s} {count:,}")

    print(f"\n{'GRAPH IMPACT':=^50}")
    print(f"  Disconnected nodes removed:    {stubs_found:,}")
    print(f"  Remaining meaningful notes:    {kept_count:,}")
    print(f"  Graph noise reduction:         ~{stubs_found / max(total_scanned, 1) * 100:.1f}%")

    print("\n" + "=" * 70)
    print("DONE")
    print("=" * 70)


if __name__ == "__main__":
    main()
