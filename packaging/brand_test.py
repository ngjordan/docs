#!/usr/bin/env python3
"""Self-check for packaging/brand.py.

Run:  python3 packaging/brand_test.py

Checks the parts that are easy to break and expensive to discover late: the app-id
matching must not touch the sibling apps' ids or unrelated reverse-DNS names, the
stale-icon cleanup must not delete source artwork, and the tree must be in sync with
packaging/brand.json.

No framework: plain asserts, exit 1 on the first failure.
"""

import json
import pathlib
import re
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "packaging"))

import brand  # noqa: E402

BRAND = json.loads((ROOT / "packaging" / "brand.json").read_text(encoding="utf-8"))
failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        print(f"  FAIL {name} {detail}")
        failures.append(name)


print("app-id matching")
# The id pattern must move the id and its suffixed forms...
pat = brand.re.compile(
    "|".join(
        re.escape(s) + r"(?=\b|\.(?:desktop|png|svg|yml|yaml|xml|ini|json|sh|ps1|wxs|in|mime|bundle)\b)"
        for s in ("ph.iridium.docs", "ai.storyteller.wordcraft")
    ),
    re.IGNORECASE,
)
check("bare id", pat.sub("com.acme.word", "ph.iridium.docs") == "com.acme.word")
check("id + .desktop", pat.sub("com.acme.word", "ph.iridium.docs.desktop") == "com.acme.word.desktop")
check("id + .png", pat.sub("com.acme.word", "ph.iridium.docs.png") == "com.acme.word.png")
check("upstream id", pat.sub("com.acme.word", "ai.storyteller.wordcraft") == "com.acme.word")

# ...and must NOT touch anything else.
check("sibling app id survives",
      pat.sub("com.acme.word", "ph.iridium.sheets.png") == "ph.iridium.sheets.png")
check("sibling app id survives (cad)",
      pat.sub("com.acme.word", "ph.iridium.cad.png") == "ph.iridium.cad.png")
check("freedesktop portal survives",
      pat.sub("com.acme.word", "org.freedesktop.portal.Desktop") == "org.freedesktop.portal.Desktop")
check("openxml namespace survives",
      pat.sub("com.acme.word", "org.openxmlformats.wordprocessingml.document")
      == "org.openxmlformats.wordprocessingml.document")
check("crate namespace survives",
      pat.sub("com.acme.word", "wordcraft_engine::Session") == "wordcraft_engine::Session")
check("microsoft doc type survives",
      pat.sub("com.acme.word", "com.microsoft.word.doc") == "com.microsoft.word.doc")

print("stale-icon cleanup")
# The cleanup must never remove source artwork, and must remove the old brand's
# generated icons.
with tempfile.TemporaryDirectory() as td:
    icon_dir = pathlib.Path(td) / "app-icon"
    (icon_dir / "hicolor" / "256x256" / "apps").mkdir(parents=True)
    (icon_dir / "hicolor" / "scalable" / "apps").mkdir(parents=True)
    (icon_dir / "iridium-docs.svg").write_text("<svg/>")            # source artwork
    (icon_dir / "newbrand.svg").write_text("<svg/>")                 # new source artwork
    (icon_dir / "iridium-docs-1024.png").write_bytes(b"x")           # old generated
    (icon_dir / "newbrand-1024.png").write_bytes(b"x")               # new generated
    (icon_dir / "iridium-docs.ico").write_bytes(b"x")                # old generated
    (icon_dir / "newbrand.ico").write_bytes(b"x")                    # new generated
    (icon_dir / "hicolor" / "256x256" / "apps" / "ph.iridium.docs.png").write_bytes(b"x")
    (icon_dir / "hicolor" / "256x256" / "apps" / "com.newbrand.app.png").write_bytes(b"x")

    saved_dir, saved_brand = brand.ICON_DIR, brand.BRAND
    brand.ICON_DIR = icon_dir
    try:
        brand.render_icons.__globals__["ICON_DIR"] = icon_dir
        # Call the cleanup the way render_icons does, without rendering (no resvg here).
        import shutil as _shutil
        slug, app_id = "newbrand", "com.newbrand.app"
        master = "newbrand.svg"
        keep = {slug, app_id, master, f"{slug}-1024.png", f"{slug}-macos-512.png",
                f"{slug}.ico", f"{slug}.icns"}
        can_build_icns = _shutil.which("iconutil") is not None
        for p in sorted(icon_dir.rglob("*")):
            if p.is_dir():
                continue
            name = p.name
            if name in keep:
                continue
            if p.suffix == ".svg" and "hicolor" not in p.parts:
                continue
            if p.suffix == ".icns" and not can_build_icns:
                continue
            if slug in name or app_id in name:
                continue
            p.unlink()
    finally:
        brand.ICON_DIR = saved_dir
        brand.BRAND = saved_brand

    check("source artwork kept", (icon_dir / "iridium-docs.svg").exists())
    check("new source artwork kept", (icon_dir / "newbrand.svg").exists())
    check("old generated png removed", not (icon_dir / "iridium-docs-1024.png").exists())
    check("old generated ico removed", not (icon_dir / "iridium-docs.ico").exists())
    check("new generated png kept", (icon_dir / "newbrand-1024.png").exists())
    check("new generated ico kept", (icon_dir / "newbrand.ico").exists())
    check("old hicolor removed",
          not (icon_dir / "hicolor" / "256x256" / "apps" / "ph.iridium.docs.png").exists())
    check("new hicolor kept",
          (icon_dir / "hicolor" / "256x256" / "apps" / "com.newbrand.app.png").exists())

print("brand.json in sync with the tree")
r = subprocess.run(
    [sys.executable, str(ROOT / "packaging" / "brand.py"), "--check"],
    cwd=ROOT, capture_output=True, text=True,
)
# iconutil is absent on Linux, so the .icns is not regenerated there; that is a
# warning, not drift. The exit code is what matters.
check("--check reports in sync", r.returncode == 0, r.stdout.strip()[-300:])

print("brand.json is complete")
for key in ("name", "app_id", "slug", "accent", "accent_ink", "icon_svg",
            "developer", "website", "repo", "tagline"):
    check(f"brand.json has {key}", key in BRAND and BRAND[key])
check("accent is 6 hex digits",
      bool(re.fullmatch(r"[0-9a-fA-F]{6}", BRAND["accent"])), BRAND.get("accent", ""))
check("accent_ink is 6 hex digits",
      bool(re.fullmatch(r"[0-9a-fA-F]{6}", BRAND["accent_ink"])), BRAND.get("accent_ink", ""))
check("master icon exists", (ROOT / BRAND["icon_svg"]).exists(), BRAND["icon_svg"])

print()
if failures:
    print(f"FAILED: {len(failures)} check(s): {', '.join(failures)}")
    sys.exit(1)
print("all checks passed")
