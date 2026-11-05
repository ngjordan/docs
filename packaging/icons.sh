#!/usr/bin/env bash
# Regenerate every app icon from the master SVG named in packaging/brand.json.
#
# Needs: resvg (brew install resvg / cargo install resvg). On macOS, iconutil also writes the
# .icns. The outputs are committed, so builds and packaging never need these tools.
#
#   packaging/icons.sh
#
# This is the standalone path. `python3 packaging/brand.py` does the same work plus the
# propagation of the app id and accent colour; use that one to change the brand.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIR="$ROOT/assets/app-icon"

command -v resvg >/dev/null || { echo "error: resvg not found (brew install resvg)" >&2; exit 1; }
command -v python3 >/dev/null || { echo "error: python3 not found" >&2; exit 1; }

# brand.json is the source of truth for the master SVG, the app id and the slug.
read -r SVG_NAME ID SLUG < <(python3 - "$ROOT" <<'PY'
import json, pathlib, sys
brand = json.loads((pathlib.Path(sys.argv[1]) / "packaging" / "brand.json").read_text())
print(pathlib.Path(brand["icon_svg"]).name, brand["app_id"], brand["slug"])
PY
)

SVG="$DIR/$SVG_NAME"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# The artwork is a full-bleed 512 tile (rx=112). Windows and Linux use it as is. macOS icons sit on
# Apple's grid: an 824/1024 body with a transparent margin, so widen the viewBox to 512*1024/824.
MAC="$TMP/mac.svg"
sed 's/viewBox="0 0 512 512"/viewBox="-62.136 -62.136 636.272 636.272"/' "$SVG" >"$MAC"
grep -q 'viewBox="-62.136' "$MAC" || { echo "error: expected viewBox=\"0 0 512 512\" in $SVG" >&2; exit 1; }

render() {
  local src="$1" size="$2" dst="$3"
  resvg -w "$size" -h "$size" "$src" "$dst" </dev/null
  return 0
}

render "$SVG" 1024 "$DIR/$SLUG-1024.png"
# Runtime window/Dock icon on macOS (embedded by apps/wordcraft); other platforms use hicolor 256.
render "$MAC" 512 "$DIR/$SLUG-macos-512.png"

# Linux hicolor theme.
for s in 16 24 32 48 64 128 256 512; do
  mkdir -p "$DIR/hicolor/${s}x${s}/apps"
  render "$SVG" "$s" "$DIR/hicolor/${s}x${s}/apps/$ID.png"
done
mkdir -p "$DIR/hicolor/scalable/apps"
cp "$SVG" "$DIR/hicolor/scalable/apps/$ID.svg"

# Windows .ico.
ICO_PNGS=()
for s in 16 20 24 32 40 48 64 128 256; do
  render "$SVG" "$s" "$TMP/ico-$s.png"
  ICO_PNGS+=("$TMP/ico-$s.png")
done
(cd "$ROOT" && cargo run -q -p xtask -- ico "$DIR/$SLUG.ico" "${ICO_PNGS[@]}")

# macOS .icns.
if command -v iconutil >/dev/null; then
  SET="$TMP/$SLUG.iconset"
  mkdir -p "$SET"
  for s in 16 32 128 256 512; do
    render "$MAC" "$s" "$SET/icon_${s}x${s}.png"
    render "$MAC" $((s * 2)) "$SET/icon_${s}x${s}@2x.png"
  done
  iconutil -c icns -o "$DIR/$SLUG.icns" "$SET"
else
  echo "warning: iconutil not found (macOS only); $SLUG.icns not regenerated" >&2
fi
echo "icons written to $DIR"
