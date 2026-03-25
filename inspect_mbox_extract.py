"""
Run this on the ejatc Windows machine to inspect what's in mbox_extract/
and report back the structure so we know how to migrate.

Usage:
  python inspect_mbox_extract.py
  python inspect_mbox_extract.py "D:\path\to\mbox_extract"
"""

import os
import sys
import json
from collections import Counter

BASE = r"C:\Users\ejatc\Documents\mbox_extract"
if len(sys.argv) > 1:
    BASE = sys.argv[1]

def inspect_folder(path, max_sample=3):
    """Inspect a folder and return structure info."""
    info = {
        "path": path,
        "total_files": 0,
        "extensions": Counter(),
        "subfolders": [],
        "sample_files": [],
        "sample_content": [],
        "total_size_mb": 0,
    }

    if not os.path.exists(path):
        info["error"] = "NOT FOUND"
        return info

    for item in os.listdir(path):
        full = os.path.join(path, item)
        if os.path.isdir(full):
            info["subfolders"].append(item)
        elif os.path.isfile(full):
            info["total_files"] += 1
            _, ext = os.path.splitext(item)
            info["extensions"][ext.lower()] += 1
            info["total_size_mb"] += os.path.getsize(full) / (1024 * 1024)

            if len(info["sample_files"]) < max_sample:
                info["sample_files"].append(item)

    # Read first few lines of sample files to detect format
    for sf in info["sample_files"][:2]:
        full = os.path.join(path, sf)
        try:
            with open(full, "r", encoding="utf-8", errors="replace") as f:
                preview = f.read(500)
                info["sample_content"].append({
                    "file": sf,
                    "first_500_chars": preview
                })
        except Exception as e:
            info["sample_content"].append({
                "file": sf,
                "error": str(e)
            })

    info["extensions"] = dict(info["extensions"])
    info["total_size_mb"] = round(info["total_size_mb"], 1)
    return info


def main():
    print(f"Inspecting: {BASE}")
    print("=" * 60)

    if not os.path.exists(BASE):
        print(f"ERROR: {BASE} does not exist!")
        print("Pass the correct path as an argument:")
        print(f"  python inspect_mbox_extract.py \"C:\\path\\to\\mbox_extract\"")
        sys.exit(1)

    # Top level
    top_items = os.listdir(BASE)
    folders = [f for f in top_items if os.path.isdir(os.path.join(BASE, f))]

    print(f"Found {len(folders)} folders:")
    for f in sorted(folders):
        print(f"  {f}/")
    print()

    # Inspect each folder
    report = {}
    for folder in sorted(folders):
        path = os.path.join(BASE, folder)
        info = inspect_folder(path)
        report[folder] = info

        print(f"--- {folder} ---")
        print(f"  Files: {info['total_files']}")
        print(f"  Size: {info['total_size_mb']} MB")
        print(f"  Extensions: {info['extensions']}")
        if info['subfolders']:
            print(f"  Subfolders: {info['subfolders'][:5]}")
        if info['sample_files']:
            print(f"  Sample files: {info['sample_files']}")
        print()

    # Also check for loose files at top level
    loose = [f for f in top_items if os.path.isfile(os.path.join(BASE, f))]
    if loose:
        print(f"--- Loose files at top level ---")
        for f in loose[:10]:
            print(f"  {f}")
        print()

    # Save full report as JSON
    report_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mbox_extract_report.json")
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"Full report saved to: {report_path}")
    print("Push this file to GitHub so we can build the migration script:")
    print(f"  git add mbox_extract_report.json && git commit -m 'mbox_extract inspection report' && git push")

    # Also print sample content so we can see the format
    print()
    print("=" * 60)
    print("SAMPLE CONTENT PREVIEWS")
    print("=" * 60)
    for folder, info in report.items():
        for sample in info.get("sample_content", []):
            print(f"\n--- {folder}/{sample['file']} ---")
            if "error" in sample:
                print(f"  ERROR: {sample['error']}")
            else:
                print(sample["first_500_chars"])
            print()


if __name__ == "__main__":
    main()
