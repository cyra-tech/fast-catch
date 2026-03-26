#!/bin/zsh
set -e
cd "$(dirname "$0")"

echo "[1/5] Creating .venv if needed..."
python3 -m venv .venv
source .venv/bin/activate

echo "[2/5] Installing dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

echo "[3/5] Generating app icon..."
mkdir -p app_resources
if [[ -f app_resources/menubar_icon_source.png ]]; then
  rm -rf build/icon.iconset
  mkdir -p build/icon.iconset
  sips -z 16 16     app_resources/menubar_icon_source.png --out build/icon.iconset/icon_16x16.png >/dev/null
  sips -z 32 32     app_resources/menubar_icon_source.png --out build/icon.iconset/icon_16x16@2x.png >/dev/null
  sips -z 32 32     app_resources/menubar_icon_source.png --out build/icon.iconset/icon_32x32.png >/dev/null
  sips -z 64 64     app_resources/menubar_icon_source.png --out build/icon.iconset/icon_32x32@2x.png >/dev/null
  sips -z 128 128   app_resources/menubar_icon_source.png --out build/icon.iconset/icon_128x128.png >/dev/null
  sips -z 256 256   app_resources/menubar_icon_source.png --out build/icon.iconset/icon_128x128@2x.png >/dev/null
  sips -z 256 256   app_resources/menubar_icon_source.png --out build/icon.iconset/icon_256x256.png >/dev/null
  sips -z 512 512   app_resources/menubar_icon_source.png --out build/icon.iconset/icon_256x256@2x.png >/dev/null
  sips -z 512 512   app_resources/menubar_icon_source.png --out build/icon.iconset/icon_512x512.png >/dev/null
  cp app_resources/menubar_icon_source.png build/icon.iconset/icon_512x512@2x.png
  iconutil -c icns build/icon.iconset -o app_resources/menubar_icon.icns
else
  echo "Icon source not found: app_resources/menubar_icon_source.png"
fi

echo "[4/5] Cleaning previous build..."
rm -rf build/dist dist

echo "[5/5] Building app..."
.venv/bin/pyinstaller FastCatch.spec --noconfirm

echo "Done: dist/Fast Catch.app"
