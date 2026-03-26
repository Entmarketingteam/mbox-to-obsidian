"""
Merge duplicate vault folders (old structure → new structure).
Moves unique content from old folders into new ones, then optionally
deletes the empty old folders.

Run with --dry-run first to see what would happen.

Usage:
  python merge_vault_folders.py                          # auto-detect vault
  python merge_vault_folders.py --vault ~/Documents/Ent-Agency-vault
  python merge_vault_folders.py --dry-run                # preview only
  python merge_vault_folders.py --pair "02-Creators:08-Talent"  # merge one pair
"""

import os
import sys
import shutil
import argparse
import platform
import hashlib

# ── Config ──────────────────────────────────────────────────────────────────

if platform.system() == "Darwin":
    DEFAULT_VAULT = "/Users/ethanatchley/Documents/obsidian-vault"
elif os.path.exists(r"C:\Users\ejatc"):
    DEFAULT_VAULT = r"C:\Users\ejatc\Documents\Ent-Agency-vault"
else:
    DEFAULT_VAULT = r"C:\Users\ethan.atchley\Documents\1st vault"

# Old folder → New folder mapping
# Content from old gets merged INTO new, then old gets deleted
MERGE_PAIRS = [
    ("01-Inbox",                "09-Email-Archive"),
    ("02-Creators",             "08-Talent"),
    ("03-Brands",               "01-Brands-Contacts"),
    ("04-Campaigns",            "02-Campaigns"),
    ("05-ENT-Agency",           "06-Agency-Ops"),
    ("06-Beauty-Creatine-Plus", "03-Products/Beauty-Creatine-Plus"),
    ("07-Technical",            "07-Knowledge-Base"),
]

# Special handling for 01-Inbox: it has Gmail-Captures with 8000+ emails
# These go into a subfolder to keep 09-Email-Archive clean
INBOX_SUBFOLDER_MAP = {
    "Gmail-Captures": "Gmail-Captures",
    "Quick-Notes": "Quick-Notes",
    "Text-Captures": "Text-Captures",
}


# ── Helpers ────────────────────────────────────────────────────────────────

def file_hash(filepath):
    """Get SHA-256 hash of a file for duplicate detection."""
    h = hashlib.sha256()
    try:
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def count_files(path):
    """Count all files recursively."""
    count = 0
    if os.path.exists(path):
        for root, dirs, files in os.walk(path):
            count += len(files)
    return count


def get_all_files(path):
    """Get all files with relative paths."""
    files = []
    if os.path.exists(path):
        for root, dirs, filenames in os.walk(path):
            for fn in filenames:
                full = os.path.join(root, fn)
                rel = os.path.relpath(full, path)
                files.append(rel)
    return files


def move_file(src, dst, dry_run=False):
    """Move a file, creating parent dirs as needed."""
    if dry_run:
        return "would_move"

    dst_dir = os.path.dirname(dst)
    os.makedirs(dst_dir, exist_ok=True)

    if os.path.exists(dst):
        # Check if identical
        if file_hash(src) == file_hash(dst):
            os.remove(src)
            return "duplicate_removed"
        else:
            # Rename to avoid collision
            base, ext = os.path.splitext(dst)
            counter = 1
            while os.path.exists(f"{base}_{counter}{ext}"):
                counter += 1
            dst = f"{base}_{counter}{ext}"

    shutil.move(src, dst)
    return "moved"


# ── Merge Logic ────────────────────────────────────────────────────────────

def merge_pair(vault_path, old_name, new_name, dry_run=False):
    """Merge old folder into new folder."""
    old_path = os.path.join(vault_path, old_name)
    new_path = os.path.join(vault_path, new_name)

    if not os.path.exists(old_path):
        return {"status": "old_not_found", "old": old_name}

    old_count = count_files(old_path)
    new_count = count_files(new_path)

    print(f"\n{'='*60}")
    print(f"MERGE: {old_name} → {new_name}")
    print(f"  Old: {old_count} files")
    print(f"  New: {new_count} files")

    if old_count == 0:
        print(f"  Old folder is empty — safe to delete")
        if not dry_run:
            shutil.rmtree(old_path)
            print(f"  DELETED {old_name}")
        else:
            print(f"  Would delete {old_name}")
        return {"status": "deleted_empty", "old": old_name}

    # Create new folder if it doesn't exist
    if not dry_run:
        os.makedirs(new_path, exist_ok=True)

    # Get all files from old folder
    old_files = get_all_files(old_path)
    stats = {"moved": 0, "duplicate_removed": 0, "would_move": 0, "errors": 0}

    for rel_path in old_files:
        src = os.path.join(old_path, rel_path)
        dst = os.path.join(new_path, rel_path)

        try:
            result = move_file(src, dst, dry_run)
            stats[result] = stats.get(result, 0) + 1
        except Exception as e:
            stats["errors"] += 1
            if stats["errors"] <= 5:
                print(f"  Error: {rel_path}: {e}")

    if dry_run:
        print(f"  Would move: {stats.get('would_move', 0)} files")
    else:
        print(f"  Moved: {stats.get('moved', 0)}")
        print(f"  Duplicates removed: {stats.get('duplicate_removed', 0)}")
        if stats.get("errors"):
            print(f"  Errors: {stats['errors']}")

        # Check if old folder is now empty
        remaining = count_files(old_path)
        if remaining == 0:
            shutil.rmtree(old_path)
            print(f"  DELETED empty {old_name}")
        else:
            print(f"  WARNING: {remaining} files remain in {old_name}")

    stats["old"] = old_name
    stats["new"] = new_name
    return stats


# ── Audit ──────────────────────────────────────────────────────────────────

def audit_vault(vault_path):
    """Show current state of all folders."""
    print(f"\nVault: {vault_path}")
    print(f"{'='*60}")

    all_folders = sorted([
        d for d in os.listdir(vault_path)
        if os.path.isdir(os.path.join(vault_path, d))
        and not d.startswith(".")
    ])

    old_folders = set()
    new_folders = set()
    for old, new in MERGE_PAIRS:
        old_folders.add(old)
        new_folders.add(new.split("/")[0])

    for folder in all_folders:
        count = count_files(os.path.join(vault_path, folder))
        tag = ""
        if folder in old_folders:
            tag = " ← OLD (merge into new)"
        elif folder in new_folders:
            tag = " ← NEW (keep)"
        print(f"  {folder:35s} {count:6d} files{tag}")

    print()
    print("Merge pairs:")
    for old, new in MERGE_PAIRS:
        old_exists = os.path.exists(os.path.join(vault_path, old))
        new_exists = os.path.exists(os.path.join(vault_path, new))
        print(f"  {old:35s} {'✓' if old_exists else '✗'}  →  {new:35s} {'✓' if new_exists else '✗'}")


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Merge duplicate vault folders")
    parser.add_argument("--vault", default=DEFAULT_VAULT,
                        help=f"Path to vault (default: {DEFAULT_VAULT})")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview only — don't move or delete anything")
    parser.add_argument("--pair", type=str, default=None,
                        help="Only merge a specific pair (e.g., '02-Creators:08-Talent')")
    parser.add_argument("--audit", action="store_true",
                        help="Just show current folder state, don't merge anything")
    args = parser.parse_args()

    vault = args.vault

    if not os.path.exists(vault):
        print(f"ERROR: Vault not found at {vault}")
        print("Pass --vault with the correct path.")
        sys.exit(1)

    if args.audit:
        audit_vault(vault)
        return

    print(f"Merge Duplicate Vault Folders")
    print(f"{'='*60}")
    print(f"Vault:   {vault}")
    print(f"Dry run: {args.dry_run}")

    if args.dry_run:
        print(f"\n*** DRY RUN — nothing will be moved or deleted ***")

    # Show current state first
    audit_vault(vault)

    # Determine which pairs to merge
    if args.pair:
        parts = args.pair.split(":")
        if len(parts) != 2:
            print("ERROR: --pair format should be 'old:new' (e.g., '02-Creators:08-Talent')")
            sys.exit(1)
        pairs = [(parts[0], parts[1])]
    else:
        pairs = MERGE_PAIRS

    # Confirm if not dry run
    if not args.dry_run:
        print(f"\nThis will merge {len(pairs)} folder pairs.")
        print("Files from old folders will be MOVED into new folders.")
        print("Empty old folders will be DELETED.")
        print()
        response = input("Continue? [y/N] ").strip().lower()
        if response != "y":
            print("Aborted.")
            return

    # Do the merges
    results = []
    for old_name, new_name in pairs:
        result = merge_pair(vault, old_name, new_name, args.dry_run)
        results.append(result)

    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    for r in results:
        old = r.get("old", "?")
        status = r.get("status", "merged")
        if status == "old_not_found":
            print(f"  {old}: not found (already merged or doesn't exist)")
        elif status == "deleted_empty":
            print(f"  {old}: was empty, deleted")
        else:
            moved = r.get("moved", 0) + r.get("would_move", 0)
            dupes = r.get("duplicate_removed", 0)
            new = r.get("new", "?")
            print(f"  {old} → {new}: {moved} files, {dupes} duplicates removed")

    if not args.dry_run:
        print(f"\nDone! Now commit the changes:")
        print(f"  cd {vault}")
        print(f"  git add -A")
        print(f"  git status")
        print(f"  git commit -m 'Consolidate vault: merge old folders into new structure'")
        print(f"  git push")


if __name__ == "__main__":
    main()
