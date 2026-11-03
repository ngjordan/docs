#!/usr/bin/env python3
"""Rebrand: phase 3 - remaining user-visible product-name strings.

Replaces the product name inside user-facing message strings and the About dialog.
Internal identifiers (crate names, log targets, egui Ids, file paths) keep the
lowercase `wordcraft` token: they are not user-visible and renaming them would
churn tests and config paths for no benefit.
"""

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
CHANGES = []

# Files where a "WordCraft" inside a string literal is shown to the user.
# Test files are excluded: their assertions are updated by the same rule, so
# sweeping them too keeps the suite green.
TARGETS = [
    "crates/ui-egui/src/chrome.rs",
    "crates/ui-egui/src/app/commands.rs",
    "crates/ui-egui/src/language_packs.rs",
    "crates/ui-egui/src/zotero.rs",
    "crates/ui-egui/src/dialogs/chrome.rs",
    "crates/ui-egui/src/dialogs/dispatch.rs",
    "crates/ui-egui/src/windows.rs",
    "crates/ui-egui/src/ibeam.rs",
    "crates/ui-egui/src/backstage.rs",
    "crates/ui-egui/src/i18n/audit.rs",
    "crates/ui-egui/src/lib.rs",
    "crates/mcp/src/server.rs",
]

# The product name inside string literals -> "Iridium Docs".
# WORDCRAFT_DICTIONARIES is an env var name: handled separately, below.
NAME_RE = re.compile(r'(?<![\w/-])WordCraft(?![\w])')

for rel in TARGETS:
    p = ROOT / rel
    if not p.exists():
        print(f"FAIL missing {rel}")
        sys.exit(1)
    text = p.read_text(encoding="utf-8")

    # Protect the env var name and the dictionary folder name.
    text = text.replace("WORDCRAFT_DICTIONARIES", "\x00DICTVAR\x00")
    text = text.replace("WORDCRAFT_PROFILE_DIR", "\x00PROFILEVAR\x00")

    text2, n = NAME_RE.subn("Iridium Docs", text)

    # Restore, renamed to our own env vars.
    text2 = text2.replace("\x00DICTVAR\x00", "IRIDIUM_DOCS_DICTIONARIES")
    text2 = text2.replace("\x00PROFILEVAR\x00", "IRIDIUM_DOCS_PROFILE_DIR")

    if n:
        p.write_text(text2, encoding="utf-8")
        CHANGES.append((rel, n))

# The About dialog copyright line: we are not ArtCraft, and we must credit them.
about = ROOT / "crates/ui-egui/src/dialogs/dispatch.rs"
t = about.read_text(encoding="utf-8")
old = ('tl!("MIT OR Apache-2.0. Copyright (c) 2026 ArtCraft Team and the WordCraft contributors.")')
new = ('tl!("MIT OR Apache-2.0. Copyright (c) 2026 Iridium Technologies, Inc. '
       'Based on WordCraft (c) 2026 ArtCraft Team and the WordCraft contributors.")')
if old in t:
    about.write_text(t.replace(old, new), encoding="utf-8")
    CHANGES.append((about.relative_to(ROOT).as_posix(), 1))
    print("updated About copyright")
else:
    print("note: About copyright line not found (may already be updated)")

# The dictionary-folder env var is read somewhere; find and rename it there too.
for p in ROOT.rglob("*.rs"):
    if "target" in p.parts:
        continue
    t = p.read_text(encoding="utf-8")
    if "WORDCRAFT_DICTIONARIES" in t:
        p.write_text(t.replace("WORDCRAFT_DICTIONARIES", "IRIDIUM_DOCS_DICTIONARIES"), encoding="utf-8")
        CHANGES.append((p.relative_to(ROOT).as_posix(), 1))

print()
print(f"{'FILE':56s} {'N':>3s}")
print("-" * 64)
for rel, n in CHANGES:
    print(f"{rel:56s} {n:3d}")
print("-" * 64)
print(f"files touched: {len(CHANGES)}, replacements: {sum(n for _, n in CHANGES)}")
