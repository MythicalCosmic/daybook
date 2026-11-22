#!/bin/sh
# Packages the Windows release build into an installer and a portable zip.
# Runs inside the crm-build container after:
#   cargo build --release -p daybook-crm --no-default-features --features desktop --target x86_64-pc-windows-gnu
# usage: sh crm/tools/package-windows.sh [version]
set -e
VERSION="${1:-0.1.0}"
TARGET="${CARGO_TARGET_DIR:-/target/win}"
OUT=/target/dist/win
rm -rf "$OUT" && mkdir -p "$OUT"
cp "$TARGET/x86_64-pc-windows-gnu/release/daybook-crm.exe" "$OUT/"
# MinGW builds load WebView2 through Microsoft's redistributable loader DLL.
cp "$(find /usr/local/cargo/registry -path '*webview2-com-sys*/x64/WebView2Loader.dll' | head -1)" "$OUT/"
cp /src/crm/app/assets/icons/icon.ico "$OUT/"
cp /src/crm/tools/installer.nsi "$OUT/"
cd "$OUT"
makensis -V2 -DVERSION="$VERSION" installer.nsi
mkdir -p "portable/Daybook CRM"
cp daybook-crm.exe WebView2Loader.dll icon.ico "portable/Daybook CRM/"
(cd portable && zip -qr "../DaybookCRM-$VERSION-windows-portable.zip" "Daybook CRM")
ls -la "$OUT"
