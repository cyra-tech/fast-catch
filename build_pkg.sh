#!/bin/zsh
set -e
cd "$(dirname "$0")"

APP_PATH="dist/Fast Catch.app"
PKG_PATH="Fast-Catch-Installer.pkg"

if [[ ! -d "$APP_PATH" ]]; then
  echo "App not found: $APP_PATH"
  echo "Run ./build_app.sh first."
  exit 1
fi

rm -f "$PKG_PATH"
pkgbuild --component "$APP_PATH" --install-location /Applications "$PKG_PATH"
echo "PKG created: $PKG_PATH"
