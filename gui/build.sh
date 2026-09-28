#!/bin/zsh
# Build "Mac Game Porter.app" (SwiftUI front end + bundled porter code and native tools).
#   gui/build.sh [output-dir]      default: build/
set -euo pipefail
REPO="${0:A:h:h}"
OUT="${1:-$REPO/build}"
APP="$OUT/Mac Game Porter.app"
TOOLS="$REPO/build/tools"

for t in fa-filter srep clshost.exe fg-arc-map; do
  [[ -x "$TOOLS/$t" ]] || { "$REPO/native/build.sh" "$TOOLS"; break; }
done

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources/porter-src" "$APP/Contents/Resources/tools"
swiftc -O -parse-as-library -target arm64-apple-macos14 "$REPO/gui/MacGamePorter.swift" -o "$APP/Contents/MacOS/MacGamePorter"
cp -R "$REPO/porter" "$REPO/templates" "$REPO/porter.sh" "$APP/Contents/Resources/porter-src/"
rm -rf "$APP/Contents/Resources/porter-src/porter/__pycache__"
cp "$TOOLS"/{fa-filter,srep,clshost.exe,fg-arc-map} "$APP/Contents/Resources/tools/"
swift "$REPO/gui/make_icon.swift" "$APP/Contents/Resources/AppIcon.icns"

cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>Mac Game Porter</string>
  <key>CFBundleIdentifier</key><string>io.github.karmsakha.macgameporter</string>
  <key>CFBundleExecutable</key><string>MacGamePorter</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>LSMinimumSystemVersion</key><string>14.0</string>
  <key>LSApplicationCategoryType</key><string>public.app-category.utilities</string>
  <key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST
codesign --force --deep -s - "$APP" >/dev/null 2>&1 || true
echo "built: $APP"
