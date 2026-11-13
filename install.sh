#!/usr/bin/env bash
# Installs StarDeck for the current user on Ubuntu/Debian (venv in ~/.local/share/stardeck).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
PREFIX="$HOME/.local/share/stardeck"

echo "==> System dependencies (needs sudo)"
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip \
    libxcb-cursor0 libxkbcommon-x11-0 libegl1 libgl1 libdbus-1-3 libfontconfig1

echo "==> Virtual environment and package"
python3 -m venv "$PREFIX/venv"
"$PREFIX/venv/bin/pip" install --upgrade pip
"$PREFIX/venv/bin/pip" install "$HERE"

echo "==> Launcher and icon"
mkdir -p "$HOME/.local/bin" "$HOME/.local/share/applications" "$HOME/.local/share/icons/hicolor/scalable/apps"
ln -sf "$PREFIX/venv/bin/stardeck" "$HOME/.local/bin/stardeck"
cp "$HERE/packaging/stardeck.svg" "$HOME/.local/share/icons/hicolor/scalable/apps/stardeck.svg"
sed -e "s|@EXEC@|$PREFIX/venv/bin/stardeck|" -e "s|@ICON@|stardeck|" "$HERE/packaging/stardeck.desktop" \
    > "$HOME/.local/share/applications/stardeck.desktop"
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
gtk-update-icon-cache -q -t -f "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
echo "Done. Start 'stardeck' from the applications menu or from a terminal."
