#!/usr/bin/env python3

from pathlib import Path
import shutil
import json

# Current directory where the script is run
ROOT = Path.cwd()

metadata = []
counter = 1

for sgf in ROOT.rglob("*.sgf"):
    # Skip files already in the root with target names
    if sgf.parent == ROOT and sgf.stem.startswith("G"):
        continue

    new_name = f"G{counter}.sgf"
    dest = ROOT / new_name

    # Avoid accidental overwrite
    while dest.exists():
        counter += 1
        new_name = f"G{counter}.sgf"
        dest = ROOT / new_name

    metadata.append({
        "id": counter,
        "filename": new_name,
        "original_path": str(sgf.relative_to(ROOT)),
        "original_directory": str(sgf.parent.relative_to(ROOT)),
        "size_bytes": sgf.stat().st_size,
    })

    shutil.move(str(sgf), str(dest))
    print(f"{sgf} -> {dest}")

    counter += 1

# Write a Python-compatible metadata file
with open(ROOT / "sgf_directory.py", "w", encoding="utf-8") as f:
    f.write("# Auto-generated SGF directory\n")
    f.write("SGF_FILES = ")
    f.write(json.dumps(metadata, indent=4))
    f.write("\n")

print(f"\nMoved {len(metadata)} SGF files.")
print("Metadata written to sgf_directory.py")
