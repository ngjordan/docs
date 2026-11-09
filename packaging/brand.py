#!/usr/bin/env python3
"""Apply packaging/brand.json to the tree: render the icons, propagate the values.

    python3 packaging/brand.py            # render icons + apply all values
    python3 packaging/brand.py --icons    # render icons only
    python3 packaging/brand.py --check    # report drift, change nothing

The icons are the mechanical part: the master SVG named in brand.json is rendered to
every size the platform wants (hicolor PNGs for Linux, .icns for macOS, .ico for
Windows) and the files are renamed to match `slug`/`app_id`.

The app id, accent colour and Windows version info are propagated into the places
that hardcode them. The product NAME is not propagated: it appears as translatable
UI string literals, and a runtime brand struct would have to thread through the
whole UI for a value that changes far less often than the icon.

Idempotent: running it twice changes nothing the second time. `--check` exits 1 if
the tree has drifted from brand.json, so CI can catch a hand-edited icon path.
"""

import argparse
import json
import pathlib
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = pathlib.Path(__file__).resolve().parent.parent
BRAND = ROOT / "packaging" / "brand.json"
ICON_DIR = ROOT / "assets" / "app-icon"

HICOLOR_SIZES = [16, 24, 32, 48, 64, 128, 256, 512]
ICO_SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]
MACOS_SIZES = [16, 32, 128, 256, 512]

TEXT_SUFFIXES = {
    ".rs", ".toml", ".sh", ".bash", ".py", ".json", ".yaml", ".yml", ".html",
    ".md", ".txt", ".xml", ".in", ".plist", ".wxs", ".ps1", ".desktop", ".svg",
    ".css", ".js", ".ts", ".cfg", ".conf", ".properties", ".env", ".example",
    ".gitignore", ".gitattributes", ".editorconfig", ".lock",
}

# The app id only ever appears in packaging, the installers and the app's own
# sources. A blanket regex over the whole tree would corrupt unrelated ids that
# happen to look like reverse-DNS names: org.freedesktop.portal, com.microsoft.word.doc,
# org.openxmlformats.*, and the sibling apps' icons (ph.iridium.sheets.png,
# ph.iridium.cad.png). Those must not move.
#
# The files are found by GLOB, not by a hardcoded path: the packaging files are
# themselves named after the app id (ph.docs.desktop), so a hardcoded path
# would stop matching after the first rebrand and the rule would silently skip them.
APP_ID_GLOBS = [
    "packaging/linux/*.desktop",
    "packaging/linux/*.xml.in",
    "packaging/linux/*.xml",
    "packaging/linux/*.yaml",
    "packaging/linux/*.sh",
    "packaging/linux/flatpak/*.yml",
    "packaging/freebsd/*.sh",
    "packaging/macos/*.sh",
    "packaging/macos/*.in",
    "packaging/windows/*.ps1",
    "packaging/windows/*.json",
    "packaging/windows/*.wxs",
    "apps/iridium-docs/src/main.rs",
    "apps/iridium-docs/src/default_apps.rs",
    "apps/iridium-docs/src/apple_events.rs",
    "apps/iridium-docs/build.rs",
    "crates/control-key/src/lib.rs",
    "crates/ui-egui/src/i18n/tests.rs",
]

changes = []
drift = []


def note(rel, what):
    changes.append((rel, what))


def read_text_safe(path):
    """Read a file as UTF-8 text, or None if it is binary."""
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None


def sub(path, old, new, what, required=False, check_only=False):
    """Regex-replace `old` with `new` in `path`. Records drift when the file still matches."""
    p = ROOT / path
    if not p.exists():
        if required:
            print(f"FAIL missing file: {path}", file=sys.stderr)
            sys.exit(1)
        return
    text = read_text_safe(p)
    if text is None:
        return
    text2, n = re.subn(old, new, text)
    if n == 0:
        if required:
            print(f"FAIL no match in {path}: {old!r}", file=sys.stderr)
            sys.exit(1)
        return
    if text2 == text:
        # Already carries the desired value: nothing to do, not drift.
        return
    if check_only:
        drift.append((path, what))
        return
    p.write_text(text2, encoding="utf-8")
    note(path, what)


def sub_all(paths, pattern, new, what, check_only=False):
    """Regex replace across several files."""
    for path in paths:
        p = ROOT / path
        if not p.exists() or not p.is_file():
            continue
        text = read_text_safe(p)
        if text is None:
            continue
        text2, n = re.subn(pattern, new, text)
        if n == 0:
            continue
        if text2 == text:
            # Already carries the desired value: nothing to do, not drift.
            continue
        if check_only:
            drift.append((path, what))
            continue
        p.write_text(text2, encoding="utf-8")
        note(path, f"{what} ({n})")


def find_files(*globs):
    """Text files matching the globs, excluding binaries, build output and this script."""
    out = []
    for g in globs:
        for p in ROOT.glob(g):
            if "target" in p.parts or ".git" in p.parts:
                continue
            if not p.is_file():
                continue
            if p.resolve() in (BRAND.resolve(), Path(__file__).resolve()):
                continue
            if p.suffix.lower() not in TEXT_SUFFIXES and not p.name.startswith("."):
                continue
            if read_text_safe(p) is None:
                continue
            out.append(p.relative_to(ROOT).as_posix())
    return sorted(set(out))


# ---------------------------------------------------------------- discovery
def find_current_slug(brand):
    """Discover the icon slug the tree currently uses.

    The slug is the file stem of the generated icons (acme-word-1024.png,
    acme-word.ico). Read from the generated files, NOT from the master SVG: the
    master SVG is the NEW brand's artwork, so its stem is the slug we are moving
    TO, not the one we are moving from.
    """
    for p in sorted(ICON_DIR.glob("*.ico")):
        return p.stem
    for p in sorted(ICON_DIR.glob("*-1024.png")):
        return p.stem.replace("-1024", "")
    return "iridium-docs"


def find_current_app_id(brand):
    """Discover the app id the tree currently carries.

    The id is whatever the last rebrand left behind, so it is read from the files
    that carry it rather than hardcoded. Several sources are consulted, because
    different files spell the id differently: main.rs carries the bare id
    (ph.docs), the desktop entry is named with the id plus a suffix
    (ph.docs.desktop), and the icons are named with the id plus .png.

    The desktop-entry name is preferred: it is the form that has the fewest other
    spellings to reconcile, and it is the file that gets renamed.
    """
    # The desktop entry file name: ph.docs.desktop -> ph.docs
    for p in sorted((ROOT / "packaging" / "linux").glob("*.desktop")):
        stem = p.stem
        if stem.endswith(".desktop"):
            stem = stem[: -len(".desktop")]
        if stem.count(".") >= 2:
            return stem

    # The app's own with_app_id().
    m = re.search(r'with_app_id\("([^"]+)"\)',
                  read_text_safe(ROOT / "apps/iridium-docs/src/main.rs") or "")
    if m:
        return m.group(1).strip()

    # Fallback: the hicolor icon filenames carry the id.
    for p in sorted((ICON_DIR / "hicolor").rglob("*.png")):
        if p.stem.count(".") >= 2:
            return p.stem
    return "ai.storyteller.iridium-docs"


def rename_id_files(stale_ids, app_id, check_only=False):
    """Rename the packaging files that are named after the app id.

    ph.docs.desktop -> com.acme.word.desktop, and so on. Without this the
    next run's glob would not find the file and the id inside it would freeze.
    """
    if not app_id:
        return
    for p in sorted(ROOT.glob("packaging/**/*")):
        if not p.is_file():
            continue
        new_name = p.name
        for s in stale_ids:
            if s and s != app_id:
                new_name = new_name.replace(s, app_id)
        if new_name == p.name:
            continue
        target = p.with_name(new_name)
        if target.exists():
            continue
        if check_only:
            drift.append((str(p.relative_to(ROOT)), "app id filename"))
            continue
        p.rename(target)
        note(str(p.relative_to(ROOT)), "app id filename renamed")


# ---------------------------------------------------------------- icons
def render_icons(brand, check_only=False):
    """Render every platform icon from the master SVG and rename to match the brand."""
    svg_rel = brand["icon_svg"]
    svg = ROOT / svg_rel
    if not svg.exists():
        print(f"FAIL master icon missing: {svg_rel}", file=sys.stderr)
        sys.exit(1)
    src = svg.read_text(encoding="utf-8")
    if 'viewBox="0 0 512 512"' not in src:
        print(f"FAIL {svg_rel}: expected viewBox=\"0 0 512 512\"", file=sys.stderr)
        sys.exit(1)

    slug = brand["slug"]
    app_id = brand["app_id"]

    if shutil.which("resvg") is None:
        print("error: resvg not found (brew install resvg / cargo install resvg)", file=sys.stderr)
        sys.exit(1)

    tmp = ROOT / "target" / "brand-icons"
    tmp.mkdir(parents=True, exist_ok=True)

    def resvg(src_svg, size, dst):
        subprocess.run(
            ["resvg", "-w", str(size), "-h", str(size), str(src_svg), str(dst)],
            check=True, stdout=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
        )

    # macOS icons sit on Apple's grid: an 824/1024 body with a transparent margin.
    mac_svg = tmp / "mac.svg"
    mac_svg.write_text(
        src.replace('viewBox="0 0 512 512"', 'viewBox="-62.136 -62.136 636.272 636.272"'),
        encoding="utf-8",
    )

    wanted = {}

    # Linux hicolor theme + the two flat PNGs the apps embed.
    for s in HICOLOR_SIZES:
        wanted[f"hicolor/{s}x{s}/apps/{app_id}.png"] = (svg, s)
    wanted[f"hicolor/scalable/apps/{app_id}.svg"] = None
    wanted[f"{slug}-1024.png"] = (svg, 1024)
    wanted[f"{slug}-macos-512.png"] = (mac_svg, 512)

    if check_only:
        for rel in wanted:
            if not (ICON_DIR / rel).exists():
                drift.append((f"assets/app-icon/{rel}", "icon missing"))
    else:
        for rel, spec in wanted.items():
            dst = ICON_DIR / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            if spec is None:
                shutil.copyfile(svg, dst)
            else:
                src_svg, size = spec
                resvg(src_svg, size, dst)
            note(f"assets/app-icon/{rel}", "icon")

    # Windows .ico
    if check_only:
        if not (ICON_DIR / f"{slug}.ico").exists():
            drift.append((f"assets/app-icon/{slug}.ico", "icon missing"))
    else:
        ico_pngs = []
        for s in ICO_SIZES:
            p = tmp / f"ico-{s}.png"
            resvg(svg, s, p)
            ico_pngs.append(str(p))
        subprocess.run(
            ["cargo", "run", "-q", "-p", "xtask", "--", "ico",
             str(ICON_DIR / f"{slug}.ico"), *ico_pngs],
            cwd=ROOT, check=True,
        )
        note(f"assets/app-icon/{slug}.ico", "icon")

    # macOS .icns. Only regenerated where iconutil exists (macOS). On other hosts the
    # committed .icns is left alone: deleting it and not being able to rebuild it
    # would lose the artwork, and the file is committed so builds never need it.
    icns = ICON_DIR / f"{slug}.icns"
    if shutil.which("iconutil"):
        if check_only:
            if not icns.exists():
                drift.append((f"assets/app-icon/{slug}.icns", "icon missing"))
        else:
            set_dir = tmp / f"{slug}.iconset"
            if set_dir.exists():
                shutil.rmtree(set_dir)
            set_dir.mkdir(parents=True)
            for s in MACOS_SIZES:
                resvg(mac_svg, s, set_dir / f"icon_{s}x{s}.png")
                resvg(mac_svg, s * 2, set_dir / f"icon_{s}x{s}@2x.png")
            subprocess.run(
                ["iconutil", "-c", "icns", "-o", str(icns), str(set_dir)],
                check=True,
            )
            note(f"assets/app-icon/{slug}.icns", "icon")
    else:
        print(f"warning: iconutil not found (macOS only); {slug}.icns not regenerated", file=sys.stderr)

    # Remove GENERATED icons left over from a previous brand so a rename does not
    # orphan files. Source artwork is never removed: the master SVG is the input the
    # next rebrand starts from, and deleting it would lose the design.
    #
    # "Left over" is decided by comparing against the brand we are applying, not by
    # a hardcoded list of past brands: any generated file whose name does not match
    # the current slug/app id is stale. That keeps working after two or three
    # rebrands, which a hardcoded list does not.
    if not check_only:
        master = Path(brand["icon_svg"]).name
        keep = {slug, app_id, master, f"{slug}-1024.png", f"{slug}-macos-512.png",
                f"{slug}.ico", f"{slug}.icns"}
        # A .icns can only be rebuilt where iconutil exists (macOS). On other hosts
        # it is left in place: removing it would lose artwork that cannot be
        # regenerated here.
        can_build_icns = shutil.which("iconutil") is not None
        for p in sorted(ICON_DIR.rglob("*")):
            if p.is_dir():
                continue
            name = p.name
            if name in keep:
                continue
            # Never remove a source SVG: only the generated hicolor scalable copy
            # and the master are .svg files here, and the scalable copy is inside
            # hicolor/scalable/apps.
            if p.suffix == ".svg" and "hicolor" not in p.parts:
                continue
            if p.suffix == ".icns" and not can_build_icns:
                continue
            # A generated file belongs to the current brand if it carries the current
            # slug or app id; anything else is from an older brand.
            if slug in name or app_id in name:
                continue
            p.unlink()
            note(str(p.relative_to(ROOT)), "stale icon removed")
    shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- propagation
def propagate(brand, check_only=False):
    """Push the app id, slug and accent colour into the places that hardcode them."""
    app_id = brand["app_id"]
    slug = brand["slug"]
    accent = brand["accent"]
    accent_ink = brand["accent_ink"]
    name = brand["name"]

    # The id and slug the tree currently carries: what this run replaces.
    old_id = find_current_app_id(brand)
    old_slug = find_current_slug(brand)

    # --- app id (reverse-DNS). Every stale spelling has to go: the tree may carry
    #     more than one (the upstream id ai.storyteller.iridium-docs in main.rs, and
    #     the id the last rebrand left in the desktop entry and the icons).
    #
    #     The match is exact on a full id, never a loose prefix: a prefix match on
    #     "ph.iridium" would rewrite the sibling apps' ids (ph.iridium.sheets.png).
    #     The bare word "iridium-docs" is NOT an id - it is the crate namespace
    #     (iridium-docs_engine, iridium-docs_ui_egui) and must not move.
    stale_ids = {old_id, "ai.storyteller.iridium-docs"}
    stale_ids |= {s for s in stale_ids if s and s != app_id}
    id_pattern = re.compile(
        "|".join(
            re.escape(s) + r"(?=\b|\.(?:desktop|png|svg|yml|yaml|xml|ini|json|sh|ps1|wxs|in|mime|bundle)\b)"
            for s in sorted(stale_ids, key=len, reverse=True)
        ),
        re.IGNORECASE,
    )

    # --- the packaging files are NAMED after the app id. Rename them FIRST, so the
    #     glob below finds them under their new names in the same run.
    rename_id_files(stale_ids, app_id, check_only)

    for path in find_files(*APP_ID_GLOBS):
        p = ROOT / path
        text = read_text_safe(p)
        if text is None:
            continue
        text2, n = id_pattern.subn(app_id, text)
        if n == 0 or text2 == text:
            continue
        if check_only:
            drift.append((path, "app id"))
            continue
        p.write_text(text2, encoding="utf-8")
        note(path, f"app id ({n})")

    # --- the packaging files are NAMED after the app id. Renamed above, before the
    #     glob, so the glob finds them under their new names in the same run.

    # --- include_str!/include_bytes! paths that name an id-named file.
    for s in sorted(stale_ids, key=len, reverse=True):
        if not s or s == app_id:
            continue
        sub_all(find_files("apps/**/*.rs", "crates/**/*.rs"),
                re.escape(f"packaging/linux/{s}.desktop"),
                f"packaging/linux/{app_id}.desktop", "include path (desktop entry)", check_only)
        sub_all(find_files("apps/**/*.rs", "crates/**/*.rs"),
                re.escape(f"packaging/linux/flatpak/{s}.yml"),
                f"packaging/linux/flatpak/{app_id}.yml", "include path (flatpak)", check_only)

    # --- icon file names. Only the icon asset paths carry the slug; the bare word
    #     also appears in the package name and the MCP id, which are separate fields
    #     handled below.
    icon_files = find_files(
        "apps/**/*.rs", "apps/**/*.html", "packaging/**/*", "xtask/**/*.rs",
        "apps/**/build.rs",
    )
    sub_all(icon_files, re.escape(f"app-icon/{old_slug}"), f"app-icon/{slug}",
            "icon filename", check_only)

    # --- this app's own icon paths in the docs and the web shell. Scoped to the
    #     icon path, not the bare app id, so the sibling apps' icons in README.md
    #     (ph.iridium.sheets.png, ph.iridium.cad.png, ph.iridium.decks.png) stay.
    doc_icon_files = find_files("README.md", "apps/iridium-docs-web/index.html")
    sub_all(doc_icon_files,
            re.escape(f"app-icon/hicolor/256x256/apps/{old_id}.png"),
            f"app-icon/hicolor/256x256/apps/{app_id}.png", "icon path (readme)", check_only)
    sub_all(doc_icon_files,
            re.escape(f"app-icon/hicolor/64x64/apps/{old_id}.png"),
            f"app-icon/hicolor/64x64/apps/{app_id}.png", "icon path (readme)", check_only)
    sub_all(doc_icon_files,
            re.escape(f"app-icon/{old_slug}"), f"app-icon/{slug}",
            "icon path (readme)", check_only)

    # --- accent colour. Matched by shape, not by literal, so a rebrand from any
    #     previous accent works. Uppercase hex, matching the file's existing style.
    sub("crates/ui-egui/src/theme.rs",
        r"pub const APP_COLOR: Color32 = Color32::from_rgb\(0x[0-9A-Fa-f]{2}, 0x[0-9A-Fa-f]{2}, 0x[0-9A-Fa-f]{2}\);",
        f"pub const APP_COLOR: Color32 = Color32::from_rgb(0x{accent[0:2].upper()}, 0x{accent[2:4].upper()}, 0x{accent[4:6].upper()});",
        "accent colour", check_only=check_only)
    sub("crates/ui-egui/src/theme.rs",
        r"pub const APP_INK: Color32 = Color32::from_rgb\(0x[0-9A-Fa-f]{2}, 0x[0-9A-Fa-f]{2}, 0x[0-9A-Fa-f]{2}\);",
        f"pub const APP_INK: Color32 = Color32::from_rgb(0x{accent_ink[0:2].upper()}, 0x{accent_ink[2:4].upper()}, 0x{accent_ink[4:6].upper()});",
        "accent ink", check_only=check_only)
    sub("crates/ui-egui/src/lib.rs",
        r"accent: Some\(\[0x[0-9a-f]{2}, 0x[0-9a-f]{2}, 0x[0-9a-f]{2}\]\),",
        f"accent: Some([0x{accent[0:2]}, 0x{accent[2:4]}, 0x{accent[4:6]}]),",
        "update-dialog accent", check_only=check_only)

    # --- the update-feed identity (id, name, tagline, repo, developer).
    sub("crates/ui-egui/src/lib.rs",
        r'id: "[^"]*",\n    name: "[^"]*",\n    tagline: "[^"]*",\n    repo: "[^"]*",',
        f'id: "{slug}",\n    name: "{name}",\n    tagline: "{brand["tagline"]}",\n    repo: "{brand["repo"]}",',
        "update identity", check_only=check_only)
    sub("crates/ui-egui/src/lib.rs",
        r'developer: "[^"]*",',
        f'developer: "{brand["developer"]}",',
        "update developer", check_only=check_only)

    # --- MCP server identity.
    sub("crates/mcp/src/server.rs",
        r'"name": "[^"]*", "title": "[^"]*", "version": env!\("CARGO_PKG_VERSION"\), '
        r'"websiteUrl": "[^"]*"',
        f'"name": "{slug}", "title": "{name}", "version": env!("CARGO_PKG_VERSION"), '
        f'"websiteUrl": "{brand["website"]}"',
        "MCP identity", check_only=check_only)

    # --- Windows version info.
    sub("apps/iridium-docs/build.rs",
        r'\.set\("ProductName", "[^"]*"\)',
        f'.set("ProductName", "{name}")', "Windows product name", check_only=check_only)
    sub("apps/iridium-docs/build.rs",
        r'\.set\("FileDescription", "[^"]*"\)',
        f'.set("FileDescription", "{name} word processor")', "Windows description", check_only=check_only)
    sub("apps/iridium-docs/build.rs",
        r'\.set\("CompanyName", "[^"]*"\)',
        f'.set("CompanyName", "{brand["developer"]}")', "Windows company", check_only=check_only)

    # --- the icon paths the Rust sources embed.
    sub("crates/ui-egui/src/lib.rs",
        r'assets/app-icon/hicolor/128x128/apps/[A-Za-z0-9._-]+\.png',
        f'assets/app-icon/hicolor/128x128/apps/{app_id}.png', "icon path (ui-egui)", check_only=check_only)
    sub("apps/iridium-docs/src/main.rs",
        r'assets/app-icon/hicolor/256x256/apps/[A-Za-z0-9._-]+\.png',
        f'assets/app-icon/hicolor/256x256/apps/{app_id}.png', "icon path (desktop)", check_only=check_only)
    sub("apps/iridium-docs/src/main.rs",
        r'assets/app-icon/[A-Za-z0-9._-]+-macos-512\.png',
        f'assets/app-icon/{slug}-macos-512.png', "icon path (macos)", check_only=check_only)
    sub("apps/iridium-docs/build.rs",
        r'assets/app-icon/[A-Za-z0-9._-]+\.ico',
        f'assets/app-icon/{slug}.ico', "icon path (windows)", check_only=check_only)

    # --- packaging scripts that name the icon files.
    sub("packaging/icons.sh", r'ID="[A-Za-z0-9._-]+"', f'ID="{app_id}"',
        "icons.sh app id", check_only=check_only)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--icons", action="store_true", help="render icons only")
    ap.add_argument("--check", action="store_true", help="report drift, change nothing")
    args = ap.parse_args()

    brand = json.loads(BRAND.read_text(encoding="utf-8"))
    for key in ("name", "app_id", "slug", "accent", "accent_ink", "icon_svg"):
        if key not in brand:
            print(f"FAIL brand.json: missing {key!r}", file=sys.stderr)
            sys.exit(1)

    render_icons(brand, check_only=args.check)
    if not args.icons:
        propagate(brand, check_only=args.check)

    if args.check:
        if drift:
            print("DRIFT from packaging/brand.json:")
            for path, what in drift:
                print(f"  {path}: {what}")
            sys.exit(1)
        print("in sync with packaging/brand.json")
        return

    print(f"{'FILE':60s}  CHANGE")
    print("-" * 100)
    for rel, what in changes:
        print(f"{rel:60s}  {what}")
    print("-" * 100)
    print(f"files touched: {len(changes)}")


if __name__ == "__main__":
    main()
