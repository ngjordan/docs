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
sub("packaging/linux/ph.docs.desktop",
    "Icon=ai.storyteller.iridium-docs", "Icon=ph.docs", required=False, note="desktop Icon")
sub("packaging/linux/ph.docs.desktop",
    "StartupWMClass=ai.storyteller.iridium-docs", "StartupWMClass=ph.docs",
    required=False, note="desktop StartupWMClass")
sub("packaging/linux/ph.docs.desktop",
    "Name=Docs", "Name=Docs", required=False, note="desktop Name")
sub("packaging/linux/ph.docs.desktop",
    "Comment=Write and design documents; open and save Word files",
    "Comment=Write and design documents; open and save Word files", required=False, note="desktop Comment")

# ---- 2. Linux packaging scripts ---------------------------------------------
for f in ["packaging/linux/package.sh", "packaging/linux/flatpak-bundle.sh"]:
    sub_regex(f, r"ai\.storyteller\.iridium-docs", "ph.docs", required=False, note="app id")
    sub_regex(f, r"IRIDIUM_DOCS_MAINTAINER", "IRIDIUM_DOCS_MAINTAINER",
              required=False, note="maintainer var")
    sub_regex(f, r'Docs maintainers <iridium-docs@storyteller\.ai>',
              "Iridium maintainers <docs@iridium.ph>", required=False, note="maintainer")

sub("packaging/linux/nfpm.yaml", "name: iridium-docs", "name: iridium-docs", required=False, note="pkg name")
sub("packaging/linux/nfpm.yaml",
    "homepage: https://iridium.ph/apps/iridium-docs",
    "homepage: https://iridium.ph", required=False, note="pkg homepage")

# ---- 3. flatpak manifests ---------------------------------------------------
for f in ["packaging/linux/flatpak/ph.docs.yml",
          "packaging/linux/flatpak/ph.docs.bundle.yml"]:
    sub_regex(f, r"ai\.storyteller\.iridium-docs", "ph.docs", required=False, note="app id")

# ---- 4. icon pipeline -------------------------------------------------------
sub("packaging/icons.sh", 'ID="ai.storyteller.iridium-docs"', 'ID="ph.docs"',
    required=False, note="icon app id")

# ---- 5. macOS packaging -----------------------------------------------------
sub_regex("packaging/macos/package.sh", r'Docs\.icns', "Docs.icns",
          required=False, note="macOS icns name")

# ---- 6. NOTICE / attribution ------------------------------------------------
sub("NOTICE", "Docs\nCopyright (c) 2026 the upstream project Team and the Docs contributors.",
    "Docs\nCopyright (c) 2026 Iridium Technologies, Inc.\n"
    "Based on Docs (https://github.com/ngjordan/iridium-docs), Copyright (c) 2026 the upstream project Team\n"
    "and the Docs contributors.", required=False, note="NOTICE header")
sub("NOTICE",
    "The the upstream project name, wordmark and logos in docs/brand/ are trademarks of the the upstream project Team. They are\n"
    "not open source and are not covered by the license above; their terms are in\n"
    "docs/brand/LICENSE-brand.txt.",
    "This is a modified distribution. The the upstream project name, wordmark and logos (docs/brand/) have been\n"
    "removed, as docs/brand/LICENSE-brand.txt requires for forks and modified versions. The\n"
    "Docs source code remains under the MIT License or the Apache License, Version 2.0.",
    required=False, note="NOTICE brand paragraph")

print(f"{'FILE':58s} {'N':>3s}  NOTE")
print("-" * 100)
total = 0
for rel, old, new, n, note in CHANGES:
    total += n
    print(f"{rel:58s} {n:3d}  {note}")
print("-" * 100)
print(f"total substitutions: {total}")
