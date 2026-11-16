#!/usr/bin/env bash
# Builds a Debian/Ubuntu package that uses the distribution's PySide6. Output: dist/stardeck_<version>_all.deb
#
#   packaging/build-deb.sh            # needs: bash, dpkg-deb, python3
#   sudo apt install ./dist/stardeck_<version>_all.deb
#   sudo apt remove stardeck
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
VERSION="$(python3 -c 'import re;print(re.search(r"\"([^\"]+)\"", open("stardeck/__init__.py").read()).group(1))')"
PKG="stardeck_${VERSION}_all"
STAGE="$ROOT/build/deb/$PKG"
MAINT="Stefano Ciurleo <105057757+stefanolmo@users.noreply.github.com>"

rm -rf "$STAGE"
install -d "$STAGE/DEBIAN" "$STAGE/usr/bin" "$STAGE/usr/lib/python3/dist-packages" "$STAGE/usr/share/applications" \
    "$STAGE/usr/share/icons/hicolor/scalable/apps" "$STAGE/usr/share/doc/stardeck" "$STAGE/usr/share/man/man1"
cp -r stardeck "$STAGE/usr/lib/python3/dist-packages/stardeck"
find "$STAGE" -name '__pycache__' -type d -prune -exec rm -rf {} +

cat > "$STAGE/usr/bin/stardeck" <<'PY'
#!/usr/bin/python3
import sys

from stardeck.__main__ import main

sys.exit(main())
PY
chmod 755 "$STAGE/usr/bin/stardeck"
sed -e 's|^Exec=.*|Exec=stardeck|' -e 's|^Icon=.*|Icon=stardeck|' packaging/stardeck.desktop > "$STAGE/usr/share/applications/stardeck.desktop"
cp packaging/stardeck.svg "$STAGE/usr/share/icons/hicolor/scalable/apps/stardeck.svg"
cp README.md "$STAGE/usr/share/doc/stardeck/README.md"
gzip -9n -c packaging/stardeck.1 > "$STAGE/usr/share/man/man1/stardeck.1.gz"

cat > "$STAGE/usr/share/doc/stardeck/copyright" <<TXT
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: stardeck
Files: *
Copyright: 2026 Stefano Ciurleo
License: MIT
TXT
{
  echo "stardeck ($VERSION) stable; urgency=medium"
  echo
  echo "  * Debian/Ubuntu package of StarDeck $VERSION."
  echo
  echo " -- $MAINT  $(date -R)"
} | gzip -9n > "$STAGE/usr/share/doc/stardeck/changelog.gz"

cat > "$STAGE/DEBIAN/control" <<TXT
Package: stardeck
Version: $VERSION
Section: science
Priority: optional
Architecture: all
Depends: python3 (>= 3.10), python3-pyside6.qtcore, python3-pyside6.qtgui, python3-pyside6.qtwidgets, tzdata
Recommends: libxcb-cursor0, libxkbcommon-x11-0
Maintainer: $MAINT
Installed-Size: $(du -sk "$STAGE" | cut -f1)
Description: Virtual planetarium: stars, constellations, planets, Sun and Moon
 StarDeck shows the sky for any date and place: about 5000 stars, the
 constellation figures, Messier and bright NGC objects, the Milky Way, the Sun,
 the Moon with its phase and the planets. Time can run forward or backward.
TXT

cat > "$STAGE/DEBIAN/postinst" <<'SH'
#!/bin/sh
set -e
if command -v py3compile >/dev/null 2>&1; then py3compile -p stardeck || true; fi
if command -v update-desktop-database >/dev/null 2>&1; then update-desktop-database -q /usr/share/applications || true; fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || true; fi
exit 0
SH
cat > "$STAGE/DEBIAN/prerm" <<'SH'
#!/bin/sh
set -e
if command -v py3clean >/dev/null 2>&1; then py3clean -p stardeck || true; fi
exit 0
SH
chmod 755 "$STAGE/DEBIAN/postinst" "$STAGE/DEBIAN/prerm"
find "$STAGE" -type d -exec chmod 755 {} +
find "$STAGE" -type f ! -perm -111 -exec chmod 644 {} +
chmod 755 "$STAGE/usr/bin/stardeck"

mkdir -p dist
dpkg-deb --root-owner-group --build "$STAGE" "dist/$PKG.deb" >/dev/null
echo "Created dist/$PKG.deb ($(du -h "dist/$PKG.deb" | cut -f1))"
