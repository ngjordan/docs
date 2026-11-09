#!/usr/bin/env python3
"""Rebrand Docs -> Docs.

Deterministic, idempotent, auditable. Every change is an explicit (old, new) pair
applied to an explicit file list. Prints a change log; exits non-zero if a
required substitution did not apply.

Naming:
  product name  : Docs  -> Docs
  binary/app id : iridium-docs   -> iridium-docs
  reverse-DNS id: ai.storyteller.iridium-docs -> ph.docs
  settings dir  : iridium-docs   -> iridium-docs
  accent colour : #3B5BDB     -> #0B6E4F  (Iridium green-teal)
"""

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
CHANGES = []


def sub(rel, old, new, count=None, required=True, note=""):
    """Replace `old` with `new` in file `rel`. `count` = exact expected replacements."""
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
    """Regex replace in a file, or in every file under a directory (rel may be a dir)."""
    p = ROOT / rel
    if p.is_dir():
        total = 0
        for f in sorted(p.rglob("*.rs")):
            text = f.read_text(encoding="utf-8")
            text2, n = re.subn(pattern, new, text)
            if n:
                f.write_text(text2, encoding="utf-8")
                total += n
                CHANGES.append((str(f.relative_to(ROOT)), f"regex {pattern}", new, n, note))
        if total == 0 and required:
            print(f"FAIL no regex match under {rel}: {pattern}")
            sys.exit(1)
        return
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


# ---------------------------------------------------------------- 1. brand files
# the upstream project marks are trademarks, not open source: docs/brand/LICENSE-brand.txt
# requires a fork to remove them. This is mandatory, not cosmetic.
brand = ROOT / "docs" / "brand"
if brand.is_dir():
    for f in sorted(brand.iterdir()):
        f.unlink()
    brand.rmdir()
    CHANGES.append(("docs/brand/", "the upstream project marks (8 files)", "DELETED", 8,
                    "mandatory: trademark, not covered by MIT/Apache"))

# ---------------------------------------------------------------- 2. product name
# UI-visible product name. Tests that assert the old name are updated too.
NAME_SITES = [
    ("crates/ui-egui/src/chrome.rs", '"Docs".to_string()', '"Docs".to_string()'),
    ("crates/ui-egui/src/dialogs/chrome.rs", '=> "Docs",', '=> "Docs",'),
    ("crates/ui-egui/src/dialogs/dispatch.rs", 'tl!("Docs")', 'tl!("Docs")'),
    ("crates/ui-egui/src/windows.rs", 'return "Docs".to_string();', 'return "Docs".to_string();'),
    ("crates/ui-egui/src/windows.rs", 'with_title("Docs")', 'with_title("Docs")'),
    ("crates/pdf/src/metadata.rs", 'creator: "Docs".into(), producer: "Docs".into()',
     'creator: "Docs".into(), producer: "Docs".into()'),
    ("crates/engine/src/sample.rs", 'd.core.creator = "Docs".into();', 'd.core.creator = "Docs".into();'),
    ("crates/docx/src/write/settings.rs", 'w.leaf("Application", &[], "Docs");',
     'w.leaf("Application", &[], "Docs");'),
    ("apps/iridium-docs/src/main.rs", '.with_title("Docs")', '.with_title("Docs")'),
    ("apps/iridium-docs/build.rs", '.set("ProductName", "Docs")', '.set("ProductName", "Docs")'),
]
for rel, old, new in NAME_SITES:
    sub(rel, old, new, note="product name")

# The i18n allow-list treats the product name as a non-translatable literal.
sub("crates/ui-egui/src/i18n/audit.rs",
    'matches!(plain, "Docs" | "Docs User" |',
    'matches!(plain, "Docs" | "Docs User" |',
    note="i18n literal allow-list")

# The default tracked-changes author name.
sub_regex(r"crates/engine/src/", r'"Docs User"', '"Docs User"',
          note="tracked-change author (all crates/engine/src)")

# ---------------------------------------------------------------- 3. app id / paths
sub_regex("crates/ui-egui/src/i18n/tests.rs",
          r"ai\.storyteller\.iridium-docs", "ph.docs", note="app id in i18n test")
sub_regex("crates/control-key/src/lib.rs",
          r"ai\.storyteller\.iridium-docs", "ph.docs", note="app id in control-key test")
sub_regex("apps/iridium-docs/src/default_apps.rs",
          r"ai\.storyteller\.iridium-docs", "ph.docs", note="desktop entry id")

# ---------------------------------------------------------------- 4. settings dir
sub("crates/control-key/src/lib.rs",
    'PathBuf::from(h).join("Library/Application Support/Docs")',
    'PathBuf::from(h).join("Library/Application Support/Docs")',
    note="macOS settings dir")
sub("crates/control-key/src/lib.rs",
    'PathBuf::from(a).join("Docs")',
    'PathBuf::from(a).join("Docs")',
    note="Windows settings dir")
sub("crates/control-key/src/lib.rs",
    '.map(|c| c.join("iridium-docs"))',
    '.map(|c| c.join("iridium-docs"))',
    note="Linux settings dir")
sub("crates/control-key/src/lib.rs",
    'assert!(name == "iridium-docs" || name == "Docs", "{}"',
    'assert!(name == "iridium-docs" || name == "Docs", "{}"',
    note="settings dir test")
sub_regex("crates/control-key/src/lib.rs",
          r'IRIDIUM_DOCS_PROFILE_DIR', 'IRIDIUM_DOCS_PROFILE_DIR',
          note="profile dir env var")

# ---------------------------------------------------------------- 5. icon asset paths
# The PNG files are renamed below; the include_bytes! paths must follow.
sub_regex("crates/ui-egui/src/lib.rs",
          r"assets/app-icon/hicolor/128x128/apps/ai\.storyteller\.iridium-docs\.png",
          "assets/app-icon/hicolor/128x128/apps/ph.docs.png",
          note="icon path (ui-egui)")
sub_regex("apps/iridium-docs/src/main.rs",
          r"assets/app-icon/hicolor/256x256/apps/ai\.storyteller\.iridium-docs\.png",
          "assets/app-icon/hicolor/256x256/apps/ph.docs.png",
          note="icon path (desktop)")
# The desktop-file path in default_apps.rs is covered by the app-id rename above.
# (Keep this rule non-fatal so the script stays idempotent on re-runs.)

# ---------------------------------------------------------------- 6. MCP server info
sub("crates/mcp/src/server.rs",
    '"name": "iridium-docs", "title": "Docs", "version": env!("CARGO_PKG_VERSION"), '
    '"websiteUrl": "https://iridium.ph/apps/iridium-docs"',
    '"name": "iridium-docs", "title": "Docs", "version": env!("CARGO_PKG_VERSION"), '
    '"websiteUrl": "https://iridium.ph"',
    note="MCP server identity")
sub_regex("crates/mcp/src/server.rs",
          r"discord\.gg/artcraft", "iridium.ph", note="MCP community link")
sub_regex("crates/mcp/src/server.rs",
          r"getartcraft\.com/apps/iridium-docs", "iridium.ph", note="MCP community link 2")

# ---------------------------------------------------------------- 7. accent colour
sub("crates/ui-egui/src/theme.rs",
    "pub const APP_COLOR: Color32 = Color32::from_rgb(0x3B, 0x5B, 0xDB);",
    "pub const APP_COLOR: Color32 = Color32::from_rgb(0x0B, 0x6E, 0x4F);",
    note="accent colour")
sub("crates/ui-egui/src/theme.rs",
    "pub const APP_INK: Color32 = Color32::from_rgb(0x2B, 0x47, 0xB5);",
    "pub const APP_INK: Color32 = Color32::from_rgb(0x08, 0x4F, 0x39);",
    note="accent ink")
sub("crates/ui-egui/src/lib.rs",
    "accent: Some([0x3f, 0x5f, 0xe0]),",
    "accent: Some([0x0b, 0x6e, 0x4f]),",
    note="update-dialog accent")

# ---------------------------------------------------------------- 8. icon assets
# The upstream icon is an original placeholder (document + pen) under MIT/Apache,
# but it is still the upstream artwork. Replace with our own: a white sheet with a
# green "I" on the Iridium green tile.
#
# The raster icons are NOT deleted: apps/iridium-docs/build.rs and main.rs
# include_bytes! them, so the build breaks without them. They are regenerated
# from our SVG by packaging/icons.sh (resvg), which this script calls.
ICON_DIR = ROOT / "assets" / "app-icon"

# The master SVG: our own mark - a document sheet with an "I" and a fold.
SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
  <!-- Docs icon (original artwork; MIT OR Apache-2.0). -->
  <rect width="512" height="512" rx="112" fill="#0B6E4F"/>
  <g transform="rotate(-6 256 256)">
    <path d="M150 92 H322 L384 154 V420 H150 Z" fill="#ffffff" stroke="#062a1f" stroke-width="14" stroke-linejoin="round"/>
    <path d="M322 92 V154 H384" fill="none" stroke="#062a1f" stroke-width="14" stroke-linejoin="round"/>
    <g stroke="#0B6E4F" stroke-width="22" stroke-linecap="round">
      <line x1="212" y1="212" x2="212" y2="356"/>
      <line x1="212" y1="212" x2="300" y2="212"/>
      <line x1="212" y1="356" x2="300" y2="356"/>
    </g>
  </g>
</svg>
'''
# Keep the same filename so packaging/icons.sh and the include_bytes! paths stay valid.
(ICON_DIR / "iridium-docs.svg").write_text(SVG, encoding="utf-8")
CHANGES.append(("assets/app-icon/iridium-docs.svg", "upstream placeholder", "Docs mark", 1, "own icon"))

# The hicolor PNG filenames change with the app id, so the old ones must go.
HIC = ICON_DIR / "hicolor"
for p in sorted(HIC.rglob("ai.storyteller.iridium-docs.*")):
    p.unlink()
    CHANGES.append((str(p.relative_to(ROOT)), "upstream icon", "removed", 1, "renamed to ph.docs"))

# ---------------------------------------------------------------- 9. summary
print(f"{'FILE':62s} {'N':>3s}  CHANGE")
print("-" * 100)
total = 0
for rel, old, new, n, note in CHANGES:
    total += n
    print(f"{rel:62s} {n:3d}  {old[:30]!r} -> {new[:30]!r}  ({note})")
print("-" * 100)
print(f"total substitutions: {total}")
