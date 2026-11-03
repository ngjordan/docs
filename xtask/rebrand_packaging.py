#!/usr/bin/env python3
"""Rebrand: phase 2 - packaging files, icon pipeline, docs metadata.

Run after xtask/rebrand_iridium.py.
"""

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
CHANGES = []


def sub(rel, old, new, count=None, required=True, note=""):
    p = ROOT / rel
    if not p.exists():
        if required:
            print(f"FAIL missing file: {rel}")
            sys.exit(1)
        return
    text = p.read_text(encoding="utf-8")
    n = text.count(old)
    if n == 0:
        if required:
            print(f"FAIL no match in {rel}: {old!r}")
            sys.exit(1)
        return
    if count is not None and n != count:
        print(f"FAIL {rel}: expected {count} of {old!r}, found {n}")
        sys.exit(1)
    p.write_text(text.replace(old, new), encoding="utf-8")
    CHANGES.append((rel, old, new, n, note))


def sub_regex(rel, pattern, new, count=None, required=True, note=""):
    p = ROOT / rel
    if not p.exists():
        if required:
            print(f"FAIL missing file: {rel}")
            sys.exit(1)
        return
    text = p.read_text(encoding="utf-8")
    text2, n = re.subn(pattern, new, text)
    if n == 0:
        if required:
            print(f"FAIL no regex match in {rel}: {pattern}")
            sys.exit(1)
        return
    if count is not None and n != count:
        print(f"FAIL {rel}: expected {count} matches of {pattern}, found {n}")
        sys.exit(1)
    p.write_text(text2, encoding="utf-8")
    CHANGES.append((rel, f"regex {pattern}", new, n, note))


# ---- 1. Linux desktop entry -------------------------------------------------
sub("packaging/linux/ph.iridium.docs.desktop",
    "Icon=ai.storyteller.wordcraft", "Icon=ph.iridium.docs", required=False, note="desktop Icon")
sub("packaging/linux/ph.iridium.docs.desktop",
    "StartupWMClass=ai.storyteller.wordcraft", "StartupWMClass=ph.iridium.docs",
    required=False, note="desktop StartupWMClass")
sub("packaging/linux/ph.iridium.docs.desktop",
    "Name=WordCraft", "Name=Iridium Docs", required=False, note="desktop Name")
sub("packaging/linux/ph.iridium.docs.desktop",
    "Comment=Write and design documents; open and save Word files",
    "Comment=Write and design documents; open and save Word files", required=False, note="desktop Comment")

# ---- 2. Linux packaging scripts ---------------------------------------------
for f in ["packaging/linux/package.sh", "packaging/linux/flatpak-bundle.sh"]:
    sub_regex(f, r"ai\.storyteller\.wordcraft", "ph.iridium.docs", required=False, note="app id")
    sub_regex(f, r"WORDCRAFT_MAINTAINER", "IRIDIUM_DOCS_MAINTAINER",
              required=False, note="maintainer var")
    sub_regex(f, r'WordCraft maintainers <wordcraft@storyteller\.ai>',
              "Iridium maintainers <docs@iridium.ph>", required=False, note="maintainer")

sub("packaging/linux/nfpm.yaml", "name: wordcraft", "name: iridium-docs", required=False, note="pkg name")
sub("packaging/linux/nfpm.yaml",
    "homepage: https://getartcraft.com/apps/wordcraft",
    "homepage: https://iridium.ph", required=False, note="pkg homepage")

# ---- 3. flatpak manifests ---------------------------------------------------
for f in ["packaging/linux/flatpak/ph.iridium.docs.yml",
          "packaging/linux/flatpak/ph.iridium.docs.bundle.yml"]:
    sub_regex(f, r"ai\.storyteller\.wordcraft", "ph.iridium.docs", required=False, note="app id")

# ---- 4. icon pipeline -------------------------------------------------------
sub("packaging/icons.sh", 'ID="ai.storyteller.wordcraft"', 'ID="ph.iridium.docs"',
    required=False, note="icon app id")

# ---- 5. macOS packaging -----------------------------------------------------
sub_regex("packaging/macos/package.sh", r'WordCraft\.icns', "Iridium Docs.icns",
          required=False, note="macOS icns name")

# ---- 6. NOTICE / attribution ------------------------------------------------
sub("NOTICE", "WordCraft\nCopyright (c) 2026 ArtCraft Team and the WordCraft contributors.",
    "Iridium Docs\nCopyright (c) 2026 Iridium Technologies, Inc.\n"
    "Based on WordCraft (https://github.com/storytold/wordcraft), Copyright (c) 2026 ArtCraft Team\n"
    "and the WordCraft contributors.", required=False, note="NOTICE header")
sub("NOTICE",
    "The ArtCraft name, wordmark and logos in docs/brand/ are trademarks of the ArtCraft Team. They are\n"
    "not open source and are not covered by the license above; their terms are in\n"
    "docs/brand/LICENSE-brand.txt.",
    "This is a modified distribution. The ArtCraft name, wordmark and logos (docs/brand/) have been\n"
    "removed, as docs/brand/LICENSE-brand.txt requires for forks and modified versions. The\n"
    "WordCraft source code remains under the MIT License or the Apache License, Version 2.0.",
    required=False, note="NOTICE brand paragraph")

print(f"{'FILE':58s} {'N':>3s}  NOTE")
print("-" * 100)
total = 0
for rel, old, new, n, note in CHANGES:
    total += n
    print(f"{rel:58s} {n:3d}  {note}")
print("-" * 100)
print(f"total substitutions: {total}")
